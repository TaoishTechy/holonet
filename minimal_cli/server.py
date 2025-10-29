#!/usr/bin/env python3
"""
HoloNet v2.3 — GOD-TIER SERVER (proto=1.2-compatible, websockets asyncio API)
-----------------------------------------------------
Goals
- Preserve wire-compat with v2.3 client protocol (hello/pong/frame/auth/status)
- Stronger backpressure + per-connection task model (rx/tx/pump)
- Adaptive frame cadence (PhiRate + latency) with micro-batching of deltas
- Optional AUTH (HMAC) + optional JWT (if AUTH_JWT_SECRET provided)
- Optional mDNS via zeroconf (ZEROCONF=1)
- HTTP status + Prometheus metrics (+ /sessions for live inspection)
- Graceful shutdown + structured logs
- Optional TLS for WS/HTTP (TLS_CERT/TLS_KEY)
- Permessage-deflate for WS payload compression

Runtime deps: websockets>=14.0, aiohttp (zeroconf optional)
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import time
import uuid
import hmac
import hashlib
import ssl
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Deque, Tuple
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed
from aiohttp import web

# -------------------- proto_phi integration --------------------
# Keep compatibility with the existing engine API
# (generate_frame, calculate_delta, create_enhanced_holoframe)
from proto_phi import UnifiedPhiMatrix  # type: ignore

# -------------------- Optional zeroconf ------------------------
ZEROCONF_ENABLED = os.getenv("ZEROCONF", "0") == "1"
if ZEROCONF_ENABLED:
    try:
        from zeroconf import ServiceInfo, Zeroconf  # type: ignore
    except Exception:
        ZEROCONF_ENABLED = False

# -------------------- Settings ---------------------------------
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "8765"))
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))

FRAME_HZ_MIN = float(os.getenv("FRAME_HZ_MIN", "1.0"))
FRAME_HZ_MAX = float(os.getenv("FRAME_HZ_MAX", "10.0"))
CLIENT_HEARTBEAT_TIMEOUT_SECS = float(os.getenv("CLIENT_HEARTBEAT_TIMEOUT_SECS", "20"))

# AUTH (HMAC)
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "0") == "1"
AUTH_SECRET = os.getenv("AUTH_SECRET", "")

# Optional JWT auth (header-only HMAC SHA256)
AUTH_JWT_SECRET = os.getenv("AUTH_JWT_SECRET", "")

# Delta micro-batching (reduce WS bursts)
DELTA_BATCH_WINDOW_MS = int(os.getenv("DELTA_BATCH_WINDOW_MS", "45"))  # 45ms
DELTA_BATCH_MAX = int(os.getenv("DELTA_BATCH_MAX", "4"))

# Permessage-deflate (handled by websockets library); set no context takeover for better fairness
WS_COMPRESSION_ENABLED = os.getenv("WS_COMPRESSION", "1") == "1"

# TLS (optional)
TLS_CERT = os.getenv("TLS_CERT")
TLS_KEY = os.getenv("TLS_KEY")

# Logging -------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("holonet.god")

# -------------------- Metrics ----------------------------------
class Metrics:
    __slots__ = (
        "start_ts","ws_connections_current","ws_connections_total",
        "msg_rx_total","msg_tx_total","heartbeat_total",
        "frames_total","frames_delta_total","frames_full_total",
        "errors_total","client_latency_ms","auth_fail_total",
        "backpressure_drops_total"
    )
    def __init__(self) -> None:
        self.start_ts = time.time()
        self.ws_connections_current = 0
        self.ws_connections_total = 0
        self.msg_rx_total = 0
        self.msg_tx_total = 0
        self.heartbeat_total = 0
        self.frames_total = 0
        self.frames_delta_total = 0
        self.frames_full_total = 0
        self.errors_total = 0
        self.auth_fail_total = 0
        self.backpressure_drops_total = 0
        self.client_latency_ms: Deque[float] = deque(maxlen=512)

    def prom(self) -> str:
        parts = [
            f'holonet_uptime_seconds {int(time.time()-self.start_ts)}',
            f'holonet_ws_connections_current {self.ws_connections_current}',
            f'holonet_ws_connections_total {self.ws_connections_total}',
            f'holonet_msg_rx_total {self.msg_rx_total}',
            f'holonet_msg_tx_total {self.msg_tx_total}',
            f'holonet_heartbeat_total {self.heartbeat_total}',
            f'holonet_frames_total {self.frames_total}',
            f'holonet_frames_full_total {self.frames_full_total}',
            f'holonet_frames_delta_total {self.frames_delta_total}',
            f'holonet_errors_total {self.errors_total}',
            f'holonet_auth_fail_total {self.auth_fail_total}',
            f'holonet_backpressure_drops_total {self.backpressure_drops_total}',
        ]
        if self.client_latency_ms:
            try:
                avg = sum(self.client_latency_ms) / len(self.client_latency_ms)
                parts.append(f'holonet_client_latency_ms_avg {avg:.3f}')
            except Exception:
                pass
        return "# TYPE holonet_... gauge\n" + "\n".join(parts) + "\n"

METRICS = Metrics()

# -------------------- Auth helpers ------------------------------

def compute_hmac(challenge: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), challenge.encode(), hashlib.sha256).hexdigest()

# Minimal JWT verifier (HS256) without external deps. Accepts only header/payload/signature.
def verify_jwt(token: str) -> bool:
    try:
        if not AUTH_JWT_SECRET:
            return False
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(AUTH_JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        # base64url decode sig
        pad = '=' * (-len(sig_b64) % 4)
        provided = base64.urlsafe_b64decode(sig_b64 + pad)
        return hmac.compare_digest(provided, expected)
    except Exception:
        return False

# -------------------- Engine & cadence --------------------------
PHI_ENGINE = UnifiedPhiMatrix(width=120, height=36, depth=32, seed=None)

# Map phi_rate [0..1] to [min..max], dampen by latency

def frame_interval_seconds(phi_rate: float, latency_ms: float) -> float:
    hz = FRAME_HZ_MIN + (FRAME_HZ_MAX - FRAME_HZ_MIN) * max(0.0, min(1.0, phi_rate))
    if latency_ms > 300:
        hz *= 0.5
    elif latency_ms > 150:
        hz *= 0.7
    hz = max(FRAME_HZ_MIN, min(FRAME_HZ_MAX, hz))
    return 1.0 / hz

# -------------------- Session model -----------------------------
@dataclass
class ClientSession:
    ws: ServerConnection
    session_id: str
    ip: str
    path: str
    proto: str
    auth_ok: bool = False
    observer_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    entity_link: str = "none"
    width: int = 120
    height: int = 36
    z_plane: int = 0
    last_matrix: Optional[Dict[str, Any]] = None
    last_heartbeat_ts: float = field(default_factory=time.time)
    last_frame_ts: float = 0.0
    feature_flags: Dict[str, bool] = field(default_factory=lambda: {
        "deltaFrames": True,
        "compression": False,
        "batching": True
    })
    phi_rate: float = 0.5
    latency_ms: float = 0.0
    running: bool = True
    # queues & tasks
    tx_queue: asyncio.Queue[Dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    rx_task: Optional[asyncio.Task] = None
    tx_task: Optional[asyncio.Task] = None
    pump_task: Optional[asyncio.Task] = None

# -------------------- Safe send via TX queue --------------------
async def enqueue(session: ClientSession, payload: Dict[str, Any]) -> None:
    try:
        await session.tx_queue.put(payload)
    except asyncio.QueueFull:
        METRICS.backpressure_drops_total += 1
        log.warning("tx_queue full; drop for %s", session.session_id)

async def tx_worker(session: ClientSession) -> None:
    while session.running:
        try:
            payload = await session.tx_queue.get()
            s = json.dumps(payload, separators=(",", ":"))
            await session.ws.send(s)
            METRICS.msg_tx_total += 1
        except Exception as e:
            METRICS.errors_total += 1
            log.warning("tx send failed %s: %s", session.session_id, e)
            await asyncio.sleep(0.02)

# -------------------- Frames & batching -------------------------
async def send_frame_if_due(session: ClientSession) -> bool:
    now = time.time()
    interval = frame_interval_seconds(session.phi_rate, session.latency_ms)

    # Further slow if client is silent
    if now - session.last_heartbeat_ts > CLIENT_HEARTBEAT_TIMEOUT_SECS:
        interval = max(interval, 0.75)

    if now - session.last_frame_ts < interval * 0.8:
        return False

    try:
        matrix, qdata, supers, ents = PHI_ENGINE.generate_frame(
            x_offset=0, y_offset=0, z_plane=session.z_plane,
            observer_id=session.observer_id,
            width=session.width, height=session.height,
            full_refresh=False,
        )
        delta_matrix, is_delta = PHI_ENGINE.calculate_delta(matrix, session.last_matrix)
        use_delta = is_delta and session.feature_flags.get("deltaFrames", True)

        # Micro-batch window: accumulate empty deltas and coalesce changes
        if use_delta:
            batched_delta: Dict[str, Any] = {}
            changed = False
            start = time.time()
            # take up to DELTA_BATCH_MAX bursts or until window elapsed
            for _ in range(DELTA_BATCH_MAX):
                if delta_matrix:
                    batched_delta.update(delta_matrix)
                    changed = True
                if (time.time() - start) * 1000 >= DELTA_BATCH_WINDOW_MS:
                    break
                # peek for one more immediate step (non-blocking)
                nxt_matrix, _, _, _ = PHI_ENGINE.generate_frame(
                    x_offset=0, y_offset=0, z_plane=session.z_plane,
                    observer_id=session.observer_id,
                    width=session.width, height=session.height,
                    full_refresh=False,
                )
                delta_matrix, _ = PHI_ENGINE.calculate_delta(nxt_matrix, session.last_matrix)
                if delta_matrix:
                    session.last_matrix = nxt_matrix
            payload_matrix = batched_delta if changed else {}
        else:
            payload_matrix = matrix

        frame = PHI_ENGINE.create_enhanced_holoframe(
            session=session,
            matrix=payload_matrix,
            quantum_data=qdata,
            superpositions=supers,
            entanglements=ents,
            is_delta=use_delta,
        )

        # Update last full matrix when something actually changed or when full
        if not use_delta or payload_matrix:
            session.last_matrix = matrix

        await enqueue(session, {"op": "frame", "data": frame})
        METRICS.frames_total += 1
        if use_delta:
            if payload_matrix:
                METRICS.frames_delta_total += 1
        else:
            METRICS.frames_full_total += 1
        session.last_frame_ts = now
        return True
    except Exception as e:
        METRICS.errors_total += 1
        log.warning("send_frame_if_due error %s: %s", session.session_id, e)
        return False

async def frame_pump(session: ClientSession) -> None:
    while session.running:
        interval = frame_interval_seconds(session.phi_rate, session.latency_ms)
        if time.time() - session.last_heartbeat_ts > CLIENT_HEARTBEAT_TIMEOUT_SECS:
            interval = max(interval, 0.75)
        await send_frame_if_due(session)
        await asyncio.sleep(interval)

# -------------------- Protocol handlers ------------------------
async def ws_hello(session: ClientSession) -> None:
    await enqueue(session, {
        "op": "hello",
        "server": "holonet v2.3 (god)",
        "proto": session.proto,
        "ts": time.time(),
        "motd": "welcome to holonet",
        "session": session.session_id,
        "features": session.feature_flags,
    })

async def status_snapshot(session: Optional[ClientSession] = None) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "op": "status",
        "ts": time.time(),
        "server": "holonet v2.3 (god)",
        "proto": "1.2",
        "ws_port": WS_PORT,
        "http_port": HTTP_PORT,
        "metrics": {
            "connections_current": METRICS.ws_connections_current,
            "connections_total": METRICS.ws_connections_total,
            "msg_rx_total": METRICS.msg_rx_total,
            "msg_tx_total": METRICS.msg_tx_total,
            "frames_total": METRICS.frames_total,
        },
    }
    if session:
        snap["session"] = {
            "id": session.session_id,
            "observer": session.observer_id,
            "phiRate": session.phi_rate,
            "latency_ms": session.latency_ms,
            "view": {"w": session.width, "h": session.height, "z": session.z_plane},
        }
    return snap

async def handle_op(session: ClientSession, obj: Dict[str, Any]) -> None:
    op = obj.get("op")
    if not op:
        return

    METRICS.msg_rx_total += 1

    # Gated by auth if required
    if AUTH_REQUIRED and not session.auth_ok and op != "auth":
        await enqueue(session, {"op": "error", "reason": "unauth_required", "ts": time.time()})
        return

    if op == "heartbeat":
        METRICS.heartbeat_total += 1
        session.last_heartbeat_ts = time.time()
        client_ts = obj.get("ts")
        if isinstance(client_ts, (int, float)):
            # Supports seconds or ms epoch
            if client_ts > 1e10:
                client_ts = client_ts / 1000.0
            session.latency_ms = max(0.0, (time.time() - client_ts) * 1000.0)
            METRICS.client_latency_ms.append(session.latency_ms)
        phi = obj.get("phiRate")
        if isinstance(phi, (int, float)):
            session.phi_rate = float(max(0.0, min(1.0, phi)))
        await enqueue(session, {"op": "pong", "ts": time.time(), "session": session.session_id})
        return

    if op == "auth":
        # Supports either simple HMAC challenge/response or JWT "token"
        challenge = obj.get("challenge", "")
        response = obj.get("response", "")
        token = obj.get("token", "")

        ok = False
        if token and AUTH_JWT_SECRET:
            ok = verify_jwt(token)
        elif AUTH_SECRET:
            expected = compute_hmac(challenge)
            ok = hmac.compare_digest(response, expected)
        else:
            ok = True  # auth not configured

        session.auth_ok = bool(ok)
        if not ok:
            METRICS.auth_fail_total += 1
        await enqueue(session, {"op": "auth_result", "ok": session.auth_ok, "ts": time.time()})
        return

    if op == "view":
        w = int(obj.get("width", session.width))
        h = int(obj.get("height", session.height))
        z = int(obj.get("z", session.z_plane))
        session.width = max(16, min(240, w))
        session.height = max(8, min(80, h))
        session.z_plane = max(0, min(PHI_ENGINE.depth - 1, z))
        await enqueue(session, {"op": "ack", "ts": time.time(), "view": {"w": session.width, "h": session.height, "z": session.z_plane}})
        await send_frame_if_due(session)
        return

    if op == "requestFrame":
        sent = await send_frame_if_due(session)
        await enqueue(session, {"op": "ack", "ts": time.time(), "sent": sent})
        return

    if op == "status":
        await enqueue(session, await status_snapshot(session))
        return

    await enqueue(session, {"op": "error", "reason": "unknown_operation", "ts": time.time()})

# -------------------- WS connection lifecycle ------------------
async def handle_ws(connection: ServerConnection) -> None:
    path = connection.request.path
    peer = connection.remote_address[0] if connection.remote_address else "?"

    parsed = urlparse(path)
    if not parsed.path.startswith("/holonet"):
        await connection.close(code=1008, reason="invalid path")
        return

    qp = parse_qs(parsed.query)
    proto = qp.get("proto", ["1.2"])[0]

    session = ClientSession(
        ws=connection,
        session_id=uuid.uuid4().hex[:12],
        ip=peer,
        path=parsed.path,
        proto=proto,
    )

    METRICS.ws_connections_current += 1
    METRICS.ws_connections_total += 1
    log.info("WS connect ip=%s sid=%s path=%s proto=%s", session.ip, session.session_id, session.path, session.proto)

    # Kick off per-connection tasks
    session.tx_task = asyncio.create_task(tx_worker(session), name=f"tx:{session.session_id}")
    session.pump_task = asyncio.create_task(frame_pump(session), name=f"pump:{session.session_id}")
    await ws_hello(session)

    if AUTH_REQUIRED:
        await enqueue(session, {"op": "auth_needed", "ts": time.time()})

    try:
        async for msg in connection:
            if not isinstance(msg, str):
                continue
            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                await enqueue(session, {"op": "error", "reason": "bad_json", "ts": time.time()})
                continue
            await handle_op(session, obj)

    except ConnectionClosed:
        pass
    except Exception as e:
        METRICS.errors_total += 1
        log.warning("WS exception %s: %s", session.session_id, e)
    finally:
        session.running = False
        for task in (session.pump_task, session.tx_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        METRICS.ws_connections_current -= 1
        log.info("WS closed sid=%s", session.session_id)

# -------------------- HTTP: status/metrics/sessions -------------
async def http_status(_: web.Request) -> web.Response:
    return web.json_response(await status_snapshot())

async def http_metrics(_: web.Request) -> web.Response:
    return web.Response(text=METRICS.prom(), content_type="text/plain; version=0.0.4")

# option: list active sessions (lightweight, anon by default)
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

async def http_sessions(_: web.Request) -> web.Response:
    # NOTE: This demo keeps only counters; if you want full details,
    # wire updates into _ACTIVE_SESSIONS in handle_ws lifecycle.
    return web.json_response({
        "connections_current": METRICS.ws_connections_current,
        "connections_total": METRICS.ws_connections_total,
        "avg_client_latency_ms": (sum(METRICS.client_latency_ms) / len(METRICS.client_latency_ms)) if METRICS.client_latency_ms else 0.0,
    })

async def make_http_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/status", http_status),
        web.get("/metrics", http_metrics),
        web.get("/sessions", http_sessions),
    ])
    return app

# -------------------- mDNS advertiser ---------------------------
class MDNSAdvertiser:
    def __init__(self) -> None:
        self.zc = None
        self.info = None

    def start(self) -> None:
        if not ZEROCONF_ENABLED:
            return
        try:
            from socket import inet_aton, gethostbyname, gethostname
            hostname = "holonet.local."
            stype = "_holonet._tcp.local."
            name = f"{hostname}{stype}"
            addr = inet_aton(gethostbyname(gethostname()))
            props = {"version": "2.3", "proto": "1.2"}
            self.info = ServiceInfo(
                stype,
                name,
                addresses=[addr],
                port=WS_PORT,
                properties=props,
                server=hostname,
            )
            self.zc = Zeroconf()
            self.zc.register_service(self.info)
            log.info("mDNS advertising started for holonet.local")
        except Exception as e:
            log.warning("mDNS unavailable: %s", e)

    def stop(self) -> None:
        if self.zc and self.info:
            try:
                self.zc.unregister_service(self.info)
            finally:
                self.zc.close()
                log.info("mDNS advertising stopped")

MDNS = MDNSAdvertiser()

# -------------------- Bootstrap --------------------------------
async def main() -> None:
    # HTTP
    app = await make_http_app()
    runner = web.AppRunner(app)
    await runner.setup()

    http_site: web.BaseSite
    if TLS_CERT and TLS_KEY:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        http_site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT, ssl_context=ssl_ctx)
    else:
        http_site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)

    await http_site.start()
    log.info("HTTP ready on http%s://%s:%d", "s" if TLS_CERT else "", HTTP_HOST, HTTP_PORT)

    # WS (asyncio API: handler positional, connection instead of websocket)
    compression = "deflate" if WS_COMPRESSION_ENABLED else None
    max_size = 2**20  # 1MB
    max_queue = 64

    async with serve(
        handle_ws,
        WS_HOST,
        WS_PORT,
        compression=compression,
        max_size=max_size,
        max_queue=max_queue,
        ping_interval=None,  # app-level heartbeats
        ping_timeout=None,
    ):
        log.info("WS listening on ws://%s:%d/holonet?proto=1.2", WS_HOST, WS_PORT)
        MDNS.start()

        stop_event = asyncio.Event()

        def _stop(*_: Tuple[Any, ...]) -> None:  # type: ignore[name-defined]
            log.info("shutting down")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except NotImplementedError:
                pass

        await stop_event.wait()

    await runner.cleanup()
    MDNS.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
