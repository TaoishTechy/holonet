
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
HoloNet Server (v1.2)
WS /holonet + HTTP status; token auth; demo engine.

import asyncio, json, logging, signal, sys, time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
except Exception:
    print("Install websockets: pip install websockets", file=sys.stderr)
    raise

try:
    import yaml  # optional
except Exception:
    yaml = None

# ---------------- Config ----------------
@dataclass
class ServerConfig:
    http_port: int = 8080
    ws_port: int = 8765
    tick_hz: int = 20
    demo_entities: int = 9
    ws_token: str = ""

    @staticmethod
    def load(path: Optional[str]) -> "ServerConfig":
        cfg = ServerConfig()
        if path and yaml is not None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if "server" in data:
                    cfg.http_port = int(data["server"].get("http_port", cfg.http_port))
                    cfg.ws_port = int(data["server"].get("ws_port", cfg.ws_port))
                if "engine" in data:
                    cfg.tick_hz = int(data["engine"].get("tick_hz", cfg.tick_hz))
                    cfg.demo_entities = int(data["engine"].get("demo_entities", cfg.demo_entities))
                if "security" in data:
                    cfg.ws_token = str(data["security"].get("ws_token", cfg.ws_token))
                # flat overrides
                cfg.http_port = int(data.get("http_port", cfg.http_port))
                cfg.ws_port = int(data.get("ws_port", cfg.ws_port))
                cfg.tick_hz = int(data.get("tick_hz", cfg.tick_hz))
                cfg.demo_entities = int(data.get("demo_entities", cfg.demo_entities))
                cfg.ws_token = str(data.get("ws_token", cfg.ws_token))
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f\"WARNING: bad config: {e}\", file=sys.stderr)
        return cfg

LOG = logging.getLogger("holonet")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# --------------- Engine -----------------
GLYPH_SETS = [
    ["Ω","Ψ","Φ"], ["⊗","⊕","⦿"], ["Θ","!","⟳"],
    ["*","✶","✺"], ["≡","λ","τ"], ["?","…","∞"],
    ["◈","⟡","⊻"], ["≀","∴","⦿"], ["Ω","Ψ","Φ"]
]

from dataclasses import dataclass

@dataclass
class VortexState:
    entity: str
    glyphs: List[str]
    amp: float
    phase: float
    center: List[float]
    entangled: List[str] = field(default_factory=list)
    last_update: float = field(default_factory=time.time)

class UnifiedPhiMatrixLite:
    def __init__(self, n:int):
        self.vortices: Dict[str,VortexState] = {}
        self._seed(n)

    def _seed(self, n:int):
        for i in range(n):
            g = GLYPH_SETS[i % len(GLYPH_SETS)].copy()
            self.vortices[f"entity-{i+1}"] = VortexState(
                entity=f"entity-{i+1}",
                glyphs=g,
                amp=0.6, phase=(i*0.7)%(6.28318),
                center=[ (i%3)-1, (i//3)-1, ((i//6)-0.5) ],
            )

    def psionic_nudge(self, entity:str, force:float=0.2, dphi:float=0.6):
        v = self.vortices.get(entity); 
        if not v: return
        v.amp = max(0.0, min(1.0, v.amp + force*0.1))
        v.phase = (v.phase + dphi*force) % 6.28318

    def tick(self, dt:float):
        t = time.time()
        keys = list(self.vortices.keys())
        for i,k in enumerate(keys):
            v = self.vortices[k]
            v.phase = (v.phase + dt*1.2) % 6.28318
            v.amp = max(0.0, min(1.0, 0.6 + 0.1*(i%3) + 0.05*((-1)**(int(t*2+i)))))
            v.center[0] += 0.02 * ((-1)**(int(t*3+i)))
            v.last_update = t
        if int(t)%2==0 and len(keys)>=2:
            for i in range(0, len(keys)-1, 2):
                a = self.vortices[keys[i]]; b = self.vortices[keys[i+1]]
                a.entangled = [b.entity]; b.entangled = [a.entity]

    def snapshot(self)->Dict[str,Any]:
        out = []
        for v in self.vortices.values():
            out.append({
                "entity": v.entity, "glyphs": v.glyphs,
                "amp": float(v.amp), "phase": float(v.phase),
                "center": [float(v.center[0]), float(v.center[1]), float(v.center[2])],
                "entangled": v.entangled[:]
            })
        return {"ver":"1.2","vortices": out, "meta_reflection":{"coherence":0.82,"entities":len(out)}, "synchronicity_boost":1.0}

# --------------- HTTP -------------------
class StatusHandler(BaseHTTPRequestHandler):
    engine_ref: Optional[UnifiedPhiMatrixLite] = None
    start_time: float = time.time()
    def _send(self, code:int, ctype:str, body:bytes):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path.startswith("/status"):
            up = time.time()-StatusHandler.start_time
            msg = f"HoloNet v1.2 OK | up {up:.1f}s | entities {len(StatusHandler.engine_ref.vortices) if StatusHandler.engine_ref else 0}\\n"
            self._send(200,"text/plain; charset=utf-8", msg.encode("utf-8"))
        elif self.path.startswith("/meta_report"):
            pkt = StatusHandler.engine_ref.snapshot() if StatusHandler.engine_ref else {"ver":"1.2","vortices":[]}
            body = json.dumps({"ver":"1.2","consciousness_metrics":pkt.get("meta_reflection",{}),"entities":len(pkt.get("vortices",[]))}).encode("utf-8")
            self._send(200,"application/json; charset=utf-8", body)
        else:
            self._send(404,"text/plain; charset=utf-8", b"Not Found\\n")

def start_http(port:int, engine:UnifiedPhiMatrixLite)->HTTPServer:
    StatusHandler.engine_ref = engine
    httpd = HTTPServer(("0.0.0.0", port), StatusHandler)
    Thread(target=httpd.serve_forever, daemon=True).start()
    LOG.info("HTTP on :%d", port)
    return httpd

# --------------- WS ---------------------
class WSHub:
    def __init__(self, token:str=""):
        self.clients:Set[WebSocketServerProtocol] = set()
        self.token = token
    async def register(self, ws:WebSocketServerProtocol):
        self.clients.add(ws); LOG.info("WS connected (%d)", len(self.clients))
    async def unregister(self, ws:WebSocketServerProtocol):
        self.clients.discard(ws); LOG.info("WS disconnected (%d)", len(self.clients))
    def _authorized(self, ws:WebSocketServerProtocol, path:str)->bool:
        if not self.token: return True
        try:
            qs = parse_qs(urlparse(path).query)
            if qs.get("token",[""])[0]==self.token: return True
        except Exception: pass
        try:
            auth = ws.request_headers.get("Authorization","")
            if auth.startswith("Bearer ") and auth.split(" ",1)[1]==self.token: return True
        except Exception: pass
        return False
    async def handler(self, ws:WebSocketServerProtocol, path:str, engine:UnifiedPhiMatrixLite):
        if not path.startswith("/holonet"):
            await ws.close(code=4404, reason="not found"); return
        if not self._authorized(ws, path):
            await ws.close(code=4401, reason="unauthorized"); return
        await self.register(ws)
        try:
            await ws.send(json.dumps(engine.snapshot(), ensure_ascii=False))
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if isinstance(data, dict) and data.get("action") in ("psionic_nudge","nudge","control"):
                        ent = data.get("target_entity") or data.get("entity") or "entity-1"
                        force = float(data.get("force", 0.2)); dphi = float(data.get("dphi", 0.6))
                        engine.psionic_nudge(ent, force=force, dphi=dphi)
                except Exception:
                    continue
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(ws)
    async def broadcast(self, engine:UnifiedPhiMatrixLite, tick_hz:int):
        dt = 1.0/max(1,tick_hz)
        try:
            while True:
                t0 = time.time()
                engine.tick(dt)
                pkt = engine.snapshot()
                if self.clients:
                    payload = json.dumps(pkt, ensure_ascii=False)
                    await asyncio.gather(*(c.send(payload) for c in list(self.clients) if not c.closed), return_exceptions=True)
                el = time.time()-t0
                await asyncio.sleep(max(0.0, dt-el))
        except asyncio.CancelledError:
            return

# --------------- Main -------------------
async def main_async(cfg:ServerConfig):
    engine = UnifiedPhiMatrixLite(cfg.demo_entities)
    httpd = start_http(cfg.http_port, engine)
    hub = WSHub(cfg.ws_token)
    async def ws_handler(ws, path): await hub.handler(ws, path, engine)
    ws_server = await websockets.serve(ws_handler, "0.0.0.0", cfg.ws_port, max_size=4_194_304)
    LOG.info("WS on :%d /holonet", cfg.ws_port)
    btask = asyncio.create_task(hub.broadcast(engine, cfg.tick_hz))
    loop = asyncio.get_running_loop(); stop = asyncio.Future()
    def _sig(*_): 
        if not stop.done(): stop.set_result(None)
    for s in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(s, _sig)
        except NotImplementedError: pass
    await stop
    btask.cancel(); await asyncio.sleep(0.05)
    ws_server.close(); await ws_server.wait_closed()
    httpd.shutdown()

def main():
    import argparse
    ap = argparse.ArgumentParser(description="HoloNet Server v1.2")
    ap.add_argument("--config", default=None)
    ap.add_argument("--http-port", type=int)
    ap.add_argument("--ws-port", type=int)
    ap.add_argument("--tick-hz", type=int)
    ap.add_argument("--demo-entities", type=int)
    ap.add_argument("--ws-token", type=str)
    a = ap.parse_args()
    cfg = ServerConfig.load(a.config)
    if a.http_port: cfg.http_port=a.http_port
    if a.ws_port: cfg.ws_port=a.ws_port
    if a.tick_hz: cfg.tick_hz=a.tick_hz
    if a.demo_entities: cfg.demo_entities=a.demo_entities
    if a.ws_token: cfg.ws_token=a.ws_token
    LOG.info("Config http=%d ws=%d tick=%d demo=%d auth=%s", cfg.http_port,cfg.ws_port,cfg.tick_hz,cfg.demo_entities,"ON" if cfg.ws_token else "OFF")
    try:
        asyncio.run(main_async(cfg))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
