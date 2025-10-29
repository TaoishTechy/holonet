#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HoloNet v2.3 (proto=1.2) — Φ-integrated server (patched v2)

Fixes:
- asyncio.wait() now receives only Tasks (no bare coroutines)
- Graceful task cancellation/await on WS close
- Catch ConnectionClosed in producer/consumer
- Guard sends after ws.close
"""

import asyncio
import json
import os
import random
import signal
import time
import hashlib
from typing import Dict, Any, List

import aiohttp
from aiohttp import web
import websockets
from websockets.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed

# ---------------- Settings (env-safe) ----------------
def _f(env: str, default: float) -> float:
    try:
        return float(os.getenv(env, str(default)))
    except Exception:
        return default

def _i(env: str, default: int) -> int:
    try:
        return int(os.getenv(env, str(default)))
    except Exception:
        return default

def _b(env: str, default: bool) -> bool:
    v = os.getenv(env, None)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")

WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = _i("WS_PORT", 8765)

HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = _i("HTTP_PORT", 8080)

# Cadence bounds (Hz)
FRAME_HZ_MIN = _f("FRAME_HZ_MIN", 1.0)
FRAME_HZ_MAX = _f("FRAME_HZ_MAX", 10.0)

# Anchor cadence bounds (seconds)
ANCHOR_MIN_S = _f("ANCHOR_MIN_S", 3.0)
ANCHOR_MAX_S = _f("ANCHOR_MAX_S", 15.0)

# Heartbeat timeout
CLIENT_HEARTBEAT_TIMEOUT_SECS = _f("CLIENT_HEARTBEAT_TIMEOUT_SECS", 20.0)

# Workspace size
WORKSPACE_SIZE = _i("WORKSPACE_SIZE", 9)

# ---------------- Global state ----------------
STOP_EVENT = asyncio.Event()

METRICS = {
    "frames_total": 0,
    "frames_delta_total": 0,
    "anchors_total": 0,
    "clients_connected": 0,
    "clients_total": 0,
}

WORKSPACE: List[Dict[str, Any]] = []

def workspace_push(item: Dict[str, Any]) -> None:
    WORKSPACE.append(item)
    if len(WORKSPACE) > WORKSPACE_SIZE:
        del WORKSPACE[0]

def digest_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def merkle_root(items: List[str]) -> str:
    if not items:
        return digest_str("empty")
    level = [bytes.fromhex(x) for x in items]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i+1] if i + 1 < len(level) else a
            nxt.append(hashlib.sha256(a + b).digest())
        level = nxt
    return level[0].hex()

# ---------------- HTTP ----------------
async def handle_status(request: web.Request) -> web.Response:
    body = {
        "server": "holonet",
        "version": "2.3-patched-v2",
        "proto": "1.2",
        "ws": {"host": WS_HOST, "port": WS_PORT, "path": "/holonet"},
        "metrics": METRICS,
        "workspace_size": WORKSPACE_SIZE,
        "frame_hz_bounds": [FRAME_HZ_MIN, FRAME_HZ_MAX],
        "anchor_bounds_s": [ANCHOR_MIN_S, ANCHOR_MAX_S],
    }
    return web.json_response(body)

async def handle_metrics(request: web.Request) -> web.Response:
    lines = [
        "# HELP holonet_frames_total Frames sent",
        "# TYPE holonet_frames_total counter",
        f"holonet_frames_total {METRICS['frames_total']}",
        "# HELP holonet_frames_delta_total Delta frames sent",
        "# TYPE holonet_frames_delta_total counter",
        f"holonet_frames_delta_total {METRICS['frames_delta_total']}",
        "# HELP holonet_anchors_total Anchors emitted",
        "# TYPE holonet_anchors_total counter",
        f"holonet_anchors_total {METRICS['anchors_total']}",
        "# HELP holonet_clients_connected Clients currently connected",
        "# TYPE holonet_clients_connected gauge",
        f"holonet_clients_connected {METRICS['clients_connected']}",
        "# HELP holonet_clients_total Total clients connected during lifetime",
        "# TYPE holonet_clients_total counter",
        f"holonet_clients_total {METRICS['clients_total']}",
    ]
    text = "\n".join(lines) + "\n"
    return web.Response(text=text, content_type="text/plain; version=0.0.4")

async def handle_workspace(request: web.Request) -> web.Response:
    return web.json_response({"workspace": WORKSPACE[-WORKSPACE_SIZE:]})

def build_http_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/status", handle_status),
        web.get("/metrics", handle_metrics),
        web.get("/workspace", handle_workspace),
    ])
    return app

# ---------------- WebSocket session ----------------
class Session:
    def __init__(self, ws):
        self.ws = ws
        self.sid = f"{random.randrange(16**8):08x}"
        self.connected_at = time.time()
        self.last_heartbeat = time.time()
        self.client_phi_rate = 0.62
        self.client_latency_ms = 0.0
        self.seq = 0
        self.matrix_state = {}
        self.recent_events: List[str] = []
        self.next_anchor_at = time.time() + random.uniform(ANCHOR_MIN_S, ANCHOR_MIN_S+1)

    def frame_interval(self) -> float:
        phi = max(0.0, min(1.0, float(self.client_phi_rate)))
        hz = FRAME_HZ_MIN + (FRAME_HZ_MAX - FRAME_HZ_MIN) * phi
        if self.client_latency_ms > 0:
            damp = 1.0 / (1.0 + (self.client_latency_ms / 200.0))
            hz *= damp
        hz = max(FRAME_HZ_MIN, min(FRAME_HZ_MAX, hz))
        return 1.0 / hz

    def stale(self) -> bool:
        return (time.time() - self.last_heartbeat) > CLIENT_HEARTBEAT_TIMEOUT_SECS

    def quantum_state(self) -> Dict[str, int]:
        if (self.seq // 16) % 2 == 0:
            return {"S": 0, "E": random.randint(5, 9)}
        else:
            return {"S": random.randint(5, 9), "E": 0}

    def sigil(self) -> str:
        return "Ω Emergence: INITIATE_PHASE_SEQUENCE {•}{←}"

    def next_frame(self) -> Dict[str, Any]:
        self.seq += 1
        changed = {}
        for _ in range(random.randint(1, 5)):
            x = random.randint(0, 63)
            y = random.randint(0, 31)
            val = random.randint(0, 9)
            key = f"{x},{y}"
            self.matrix_state[key] = val
            changed[key] = val

        q = self.quantum_state()
        frame = {
            "op": "frame",
            "server": "holonet",
            "proto": "1.2",
            "sequence": self.seq,
            "dimensions": {"w": 64, "h": 32},
            "layers": {
                "Sigil": [self.sigil()],
                "Quantum": [q],
                "MatrixDelta": changed,
            },
            "status": {
                "phiRate": self.client_phi_rate,
                "latency_ms": self.client_latency_ms,
                "stale": self.stale(),
            },
            "meta": {
                "phase": "integration" if (q.get("E", 0) > 0 and q.get("S", 0) == 0) else "broadcast",
            }
        }
        workspace_push({"seq": self.seq, "salience": len(changed), "ts": time.time()})
        concise = json.dumps({"seq": self.seq, "changed": list(changed.items())}, separators=(",", ":"), sort_keys=True)
        self.recent_events.append(digest_str(concise))
        if len(self.recent_events) > 2048:
            self.recent_events.pop(0)
        return frame

async def rx_loop(session: Session):
    ws = session.ws
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except Exception:
                continue

            op = data.get("op")
            if op == "heartbeat":
                session.last_heartbeat = time.time()
                cts = data.get("ts")
                if isinstance(cts, (int, float)):
                    session.client_latency_ms = max(0.0, (time.time() * 1000.0) - float(cts))
                try:
                    session.client_phi_rate = float(data.get("phiRate", session.client_phi_rate))
                except Exception:
                    pass
                if not ws.closed:
                    await ws.send(json.dumps({"op": "pong", "ts": data.get("ts", int(time.time() * 1000))}))

            elif op == "view":
                # view updates would go here
                pass

            elif op == "close":
                await ws.close(code=1000)
                break
    except ConnectionClosed:
        # normal during shutdown/close
        return

async def frame_loop(session: Session):
    ws = session.ws
    try:
        while not STOP_EVENT.is_set() and not ws.closed:
            interval = session.frame_interval()
            if session.stale():
                interval = max(interval, 1.0)
            await asyncio.sleep(interval)

            if ws.closed:
                break
            frame = session.next_frame()
            try:
                await ws.send(json.dumps(frame))
            except ConnectionClosed:
                break

            METRICS["frames_total"] += 1
            METRICS["frames_delta_total"] += 1
    except ConnectionClosed:
        return

async def anchor_loop(session: Session):
    while not STOP_EVENT.is_set():
        now = time.time()
        if now >= session.next_anchor_at and session.recent_events:
            root = merkle_root(session.recent_events[-512:])
            METRICS["anchors_total"] += 1
            print(f"Simulated on-chain anchor: root={root}")
            session.next_anchor_at = now + random.uniform(ANCHOR_MIN_S, ANCHOR_MAX_S)
        await asyncio.sleep(0.1)

async def ws_handler(websocket):
    METRICS["clients_connected"] += 1
    METRICS["clients_total"] += 1
    session = Session(websocket)
    peer = websocket.remote_address[0] if websocket.remote_address else "unknown"
    print(f"WS connect ip={peer} sid={session.sid} path=/holonet proto=1.2")

    hello = {
        "op": "hello",
        "server": "holonet",
        "proto": "1.2",
        "features": {"deltaFrames": True, "batching": True, "compression": False},
        "frames_version": "4.3",
    }
    if not websocket.closed:
        await websocket.send(json.dumps(hello))

    # Create tasks explicitly
    producer_task = asyncio.create_task(frame_loop(session), name=f"frame_loop:{session.sid}")
    consumer_task = asyncio.create_task(rx_loop(session), name=f"rx_loop:{session.sid}")
    anchor_task = asyncio.create_task(anchor_loop(session), name=f"anchor_loop:{session.sid}")
    stop_task = asyncio.create_task(STOP_EVENT.wait(), name="global_stop_wait")

    try:
        done, pending = await asyncio.wait(
            {producer_task, consumer_task, anchor_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # If global stop fired, close ws
        if stop_task in done and not websocket.closed:
            await websocket.close(code=1001, reason="server shutting down")
    finally:
        # Cancel remaining tasks and await them
        for t in (producer_task, consumer_task, anchor_task, stop_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(producer_task, consumer_task, anchor_task, stop_task, return_exceptions=True)

        METRICS["clients_connected"] -= 1
        if not websocket.closed:
            try:
                await websocket.close(code=1001, reason="server shutting down")
            except Exception:
                pass
        print(f"WS closed sid={session.sid}")

# ---------------- Server bootstrap ----------------
async def start_http():
    app = build_http_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    print(f"HTTP ready on http://{HTTP_HOST}:{HTTP_PORT}")
    return runner

async def start_ws():
    async def _accept(ws):
        await ws_handler(ws)

    server = await ws_serve(_accept, WS_HOST, WS_PORT, process_request=None)
    print(f"WS listening on ws://{WS_HOST}:{WS_PORT}/holonet?proto=1.2")
    return server

async def amain():
    http_runner = await start_http()
    ws_server = await start_ws()

    loop = asyncio.get_running_loop()

    def _graceful(*_):
        if not STOP_EVENT.is_set():
            print("shutting down")
            STOP_EVENT.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _graceful)
        except NotImplementedError:
            pass

    await STOP_EVENT.wait()
    print("server closing")
    ws_server.close()
    await ws_server.wait_closed()
    await http_runner.cleanup()
    print("server closed")

def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
