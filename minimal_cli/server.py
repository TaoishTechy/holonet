#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HoloNet v2.3 — fully debugged server.py (websockets ≥ 12 compatible)

- WebSocket endpoint: ws://0.0.0.0:8765/holonet?proto=1.2
- HTTP status:        http://0.0.0.0:8080/status
- Works with websockets v12+ (handler(websocket), path via websocket.path)
- Clean shutdown on SIGINT/SIGTERM
- Lightweight, no extra deps beyond 'websockets' (and stdlib)
"""

import asyncio
import json
import logging
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Set
from urllib.parse import urlparse, parse_qs

try:
    # websockets 12+
    from websockets.server import serve, WebSocketServerProtocol
except Exception as e:
    print("ERROR: This server requires the 'websockets' package (v12+).", file=sys.stderr)
    raise

# -----------------------
# Configuration
# -----------------------
WS_HOST = "0.0.0.0"
WS_PORT = 8765
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
ALLOWED_PATH = "/holonet"
SERVER_VERSION = "holonet v2.3"
PING_INTERVAL = 30
PING_TIMEOUT = 30
MAX_SIZE = 1_000_000
MAX_QUEUE = 32

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("holonet")

# -----------------------
# Global state
# -----------------------
class ServerState:
    def __init__(self):
        self.start_ts: float = time.time()
        self.connections: Set[WebSocketServerProtocol] = set()
        self.lock = asyncio.Lock()
        self.msg_rx_count: int = 0
        self.msg_tx_count: int = 0
        self.last_error: str = ""
        self.last_hello_ts: float = 0.0
        self.last_client_event: float = 0.0
        self.supported_proto = "1.2"

    def snapshot(self) -> Dict:
        uptime = time.time() - self.start_ts
        return {
            "server": SERVER_VERSION,
            "uptime_sec": round(uptime, 3),
            "ws": {
                "host": WS_HOST,
                "port": WS_PORT,
                "endpoint": f"{ALLOWED_PATH}?proto={self.supported_proto}",
                "clients": len(self.connections),
                "msg_rx_count": self.msg_rx_count,
                "msg_tx_count": self.msg_tx_count,
                "last_hello_ts": self.last_hello_ts,
                "last_client_event": self.last_client_event,
            },
            "http": {
                "host": HTTP_HOST,
                "port": HTTP_PORT,
                "status_path": "/status",
            },
            "errors": {
                "last": self.last_error,
            },
        }

STATE = ServerState()
STOP = asyncio.Event()

# -----------------------
# HTTP status server
# -----------------------
class StatusHandler(BaseHTTPRequestHandler):
    # Silence default logging
    def log_message(self, format, *args):
        log.debug("HTTP: " + format % args)

    def _send_json(self, code: int, payload: Dict):
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Basic CORS for simple GETs
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                # Snapshot global state
                self._send_json(200, STATE.snapshot())
                return
            elif parsed.path == "/meta_report":
                # Minimal extra endpoint; extend as you like
                meta = STATE.snapshot()
                meta["meta"] = {
                    "python_version": sys.version.split()[0],
                    "time": time.time(),
                }
                self._send_json(200, meta)
                return
            else:
                self._send_json(404, {"error": "not_found", "path": parsed.path})
        except Exception as e:
            self._send_json(500, {"error": "internal_error", "detail": str(e)})

def run_http_server():
    httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), StatusHandler)
    log.info("HTTP status endpoint available on http://%s:%d/status", HTTP_HOST, HTTP_PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

# -----------------------
# WebSocket handler
# -----------------------
async def handle_ws(websocket: WebSocketServerProtocol):
    """
    websockets v12+ passes only the connection object; request path is at websocket.path
    """
    path = getattr(websocket, "path", "/")
    # Gate invalid path
    if not path.startswith(ALLOWED_PATH):
        await websocket.close(code=1008, reason="invalid path")
        return

    # Parse query (?proto=1.2 etc.)
    try:
        qp = parse_qs(urlparse(path).query)
        client_proto = (qp.get("proto") or ["1.0"])[0]
    except Exception:
        client_proto = "1.0"

    # Register connection
    async with STATE.lock:
        STATE.connections.add(websocket)
        STATE.last_client_event = time.time()

    peer = getattr(websocket, "remote_address", None)
    log.info("WS connect from %s path=%s proto=%s", peer, path, client_proto)

    # Send hello
    hello = {
        "op": "hello",
        "server": SERVER_VERSION,
        "proto": STATE.supported_proto,
        "ts": time.time(),
        "motd": "welcome to holonet",
    }
    try:
        await websocket.send(json.dumps(hello))
        async with STATE.lock:
            STATE.msg_tx_count += 1
            STATE.last_hello_ts = time.time()
    except Exception as e:
        log.warning("WS hello send failed: %s", e)

    # Main message loop
    try:
        async for msg in websocket:
            async with STATE.lock:
                STATE.msg_rx_count += 1
                STATE.last_client_event = time.time()

            # Try to interpret JSON frames; fallback to echo text
            response = {"op": "echo", "ts": time.time()}
            try:
                data = json.loads(msg)
                response["data"] = data
            except Exception:
                response["data"] = msg

            try:
                await websocket.send(json.dumps(response))
                async with STATE.lock:
                    STATE.msg_tx_count += 1
            except Exception as e:
                log.warning("WS send failed: %s", e)
                break

    except asyncio.CancelledError:
        # Server shutting down
        pass
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log.warning("WS error (%s): %s", peer, err)
        async with STATE.lock:
            STATE.last_error = err
    finally:
        # Unregister connection
        async with STATE.lock:
            if websocket in STATE.connections:
                STATE.connections.remove(websocket)
        try:
            await websocket.close()
        except Exception:
            pass
        log.info("WS disconnected %s", peer)

# -----------------------
# Startup / Shutdown
# -----------------------
async def ws_serve_forever():
    log.info("%s server listening on ws://%s:%d%s?proto=%s",
             SERVER_VERSION, WS_HOST, WS_PORT, ALLOWED_PATH, STATE.supported_proto)
    async with serve(
        handle_ws,
        WS_HOST,
        WS_PORT,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        max_size=MAX_SIZE,
        max_queue=MAX_QUEUE,
    ):
        await STOP.wait()

async def shutdown():
    log.info("Shutting down…")
    # Close all websockets
    async with STATE.lock:
        conns = list(STATE.connections)
    for ws in conns:
        try:
            await ws.close(code=1001, reason="server shutdown")
        except Exception:
            pass
    await asyncio.sleep(0.1)

def _install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _signal_handler(sig, frame):
        if not STOP.is_set():
            STOP.set()
    try:
        loop.add_signal_handler(signal.SIGINT, lambda: STOP.set())
        loop.add_signal_handler(signal.SIGTERM, lambda: STOP.set())
    except NotImplementedError:
        # On Windows, signals aren’t fully supported; fallback
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

def main():
    # Start HTTP status server in a background thread (no extra deps)
    http_thread = threading.Thread(target=run_http_server, name="http-status", daemon=True)
    http_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(ws_serve_forever())
    finally:
        loop.run_until_complete(shutdown())
        # Give the HTTP thread a moment to finish (it’s daemon=True, so process exit will stop it)
        time.sleep(0.1)
        loop.stop()
        loop.close()

if __name__ == "__main__":
    main()
