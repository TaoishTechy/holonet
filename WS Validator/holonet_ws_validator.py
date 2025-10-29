
#!/usr/bin/env python3
HoloNet WS Validator (v1.2)
Validates WebSocket JSON packets against the HoloNet v1.2 schema and can send
canonical test vectors TV-1 and TV-3 to a running server.

Usage examples:
  # Validate local JSON files (one per line on STDIN or via --file)
  python3 holonet_ws_validator.py --file tv1.json --file tv3.json

  # Connect to a server, receive 5 packets, validate each
  python3 holonet_ws_validator.py --endpoint ws://localhost:8765/holonet --recv 5

  # Connect and send TV-1 and TV-3 (and validate echoes if any)
  python3 holonet_ws_validator.py --endpoint ws://localhost:8765/holonet --send-tv1 --send-tv3

Requirements:
  - Python 3.9+
  - websockets (pip install websockets)

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Tuple, Optional

try:
    import websockets  # type: ignore
except Exception:
    websockets = None

SCHEMA_VERSION = "1.2"


# ---------- Utility ----------

def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _path(p: List[str]) -> str:
    return "/".join(p)


def _err(errors: List[str], path: List[str], msg: str) -> None:
    errors.append(f"[{_path(path)}] {msg}")


# ---------- Schema Validation ----------

def validate_vortex(v: Dict[str, Any], path: List[str], errors: List[str]) -> None:
    # Required
    for key, typ in (("entity", str), ("glyphs", list), ("amp", (int, float)), ("phase", (int, float)), ("center", list)):
        if key not in v:
            _err(errors, path + [key], "missing required field")
            continue
        if not isinstance(v[key], typ) or (key in ("amp","phase") and isinstance(v[key], bool)):
            _err(errors, path + [key], f"must be of type {typ}")
    # glyphs
    if "glyphs" in v and isinstance(v["glyphs"], list):
        if len(v["glyphs"]) == 0:
            _err(errors, path + ["glyphs"], "must not be empty")
        for i,g in enumerate(v["glyphs"]):
            if not isinstance(g, str):
                _err(errors, path + ["glyphs", str(i)], "must be string")
    # amp range
    if "amp" in v and _is_num(v["amp"]):
        if not (0.0 <= float(v["amp"]) <= 1.0):
            _err(errors, path + ["amp"], "must be in [0,1]")
    # center
    if "center" in v and isinstance(v["center"], list):
        if len(v["center"]) != 3:
            _err(errors, path + ["center"], "must be length-3 list [x,y,z]")
        else:
            for i,c in enumerate(v["center"]):
                if not _is_num(c):
                    _err(errors, path + ["center", str(i)], "must be numeric")
    # Optional: superposition/timelines
    if "superposition" in v and not isinstance(v["superposition"], bool):
        _err(errors, path + ["superposition"], "must be boolean")
    if "timelines" in v:
        if not isinstance(v["timelines"], list):
            _err(errors, path + ["timelines"], "must be array")
        else:
            for i,t in enumerate(v["timelines"]):
                if not isinstance(t, dict):
                    _err(errors, path + ["timelines", str(i)], "must be object")
                    continue
                if "glyphs" in t and not isinstance(t["glyphs"], list):
                    _err(errors, path + ["timelines", str(i), "glyphs"], "must be array")
                if "prob" in t and not _is_num(t["prob"]):
                    _err(errors, path + ["timelines", str(i), "prob"], "must be numeric")
                if "prob" in t and _is_num(t["prob"]) and not (0.0 <= float(t["prob"]) <= 1.0):
                    _err(errors, path + ["timelines", str(i), "prob"], "must be in [0,1]")
                if "narrative" in t and not isinstance(t["narrative"], str):
                    _err(errors, path + ["timelines", str(i), "narrative"], "must be string")
    # Optional: temporal_echo
    if "temporal_echo" in v:
        te = v["temporal_echo"]
        if not isinstance(te, dict):
            _err(errors, path + ["temporal_echo"], "must be object")
        else:
            if "past_phase" in te and not _is_num(te["past_phase"]):
                _err(errors, path + ["temporal_echo","past_phase"], "must be numeric")
            if "future_hint" in te and not _is_num(te["future_hint"]):
                _err(errors, path + ["temporal_echo","future_hint"], "must be numeric")
    # Optional: neuro_map
    if "neuro_map" in v:
        nm = v["neuro_map"]
        if not isinstance(nm, dict):
            _err(errors, path + ["neuro_map"], "must be object")
        else:
            if "brainwave" in nm and not isinstance(nm["brainwave"], str):
                _err(errors, path + ["neuro_map","brainwave"], "must be string")
            if "glyphs" in nm:
                if not isinstance(nm["glyphs"], list):
                    _err(errors, path + ["neuro_map","glyphs"], "must be array")
                else:
                    for i,g in enumerate(nm["glyphs"]):
                        if not isinstance(g, str):
                            _err(errors, path + ["neuro_map","glyphs",str(i)], "must be string")
    # Optional: reality_layers
    if "reality_layers" in v:
        if not isinstance(v["reality_layers"], list):
            _err(errors, path + ["reality_layers"], "must be array")
        else:
            for i,rl in enumerate(v["reality_layers"]):
                if not isinstance(rl, dict):
                    _err(errors, path + ["reality_layers",str(i)], "must be object")
                    continue
                if "layer" in rl and not isinstance(rl["layer"], str):
                    _err(errors, path + ["reality_layers",str(i),"layer"], "must be string")
                if "interference" in rl and not _is_num(rl["interference"]):
                    _err(errors, path + ["reality_layers",str(i),"interference"], "must be numeric")
    # Optional: volition
    if "volition" in v:
        vol = v["volition"]
        if not isinstance(vol, dict):
            _err(errors, path + ["volition"], "must be object")
        else:
            if "intent" in vol and not isinstance(vol["intent"], str):
                _err(errors, path + ["volition","intent"], "must be string")
            if "drive_strength" in vol and not _is_num(vol["drive_strength"]):
                _err(errors, path + ["volition","drive_strength"], "must be numeric")
            if "drive_strength" in vol and _is_num(vol["drive_strength"]) and not (0.0 <= float(vol["drive_strength"]) <= 1.0):
                _err(errors, path + ["volition","drive_strength"], "must be in [0,1]")
    # Optional: predicted
    if "predicted" in v:
        if not isinstance(v["predicted"], list):
            _err(errors, path + ["predicted"], "must be array")
        else:
            for i,pred in enumerate(v["predicted"]):
                if not isinstance(pred, dict):
                    _err(errors, path + ["predicted",str(i)], "must be object")
                    continue
                if "t_ms" in pred and not isinstance(pred["t_ms"], int):
                    _err(errors, path + ["predicted",str(i),"t_ms"], "must be int")
                if "amp" in pred and not _is_num(pred["amp"]):
                    _err(errors, path + ["predicted",str(i),"amp"], "must be numeric")
                if "phase" in pred and not _is_num(pred["phase"]):
                    _err(errors, path + ["predicted",str(i),"phase"], "must be numeric")
    # Optional: entangled
    if "entangled" in v:
        if not isinstance(v["entangled"], list):
            _err(errors, path + ["entangled"], "must be array")
        else:
            for i,eid in enumerate(v["entangled"]):
                if not isinstance(eid, str):
                    _err(errors, path + ["entangled",str(i)], "must be string")
    # Optional: tunneled
    if "tunneled" in v and v["tunneled"] is not None:
        tun = v["tunneled"]
        if not isinstance(tun, dict):
            _err(errors, path + ["tunneled"], "must be object")
        else:
            if "sim_id" in tun and not isinstance(tun["sim_id"], str):
                _err(errors, path + ["tunneled","sim_id"], "must be string")
            if "projected_state" in tun and not isinstance(tun["projected_state"], str):
                _err(errors, path + ["tunneled","projected_state"], "must be string")


def validate_packet(pkt: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    path: List[str] = ["$"]
    # Version string
    if "ver" not in pkt:
        _err(errors, path + ["ver"], "missing required field")
    elif not isinstance(pkt["ver"], str):
        _err(errors, path + ["ver"], "must be string")
    # vortices
    if "vortices" not in pkt:
        _err(errors, path + ["vortices"], "missing required field")
    elif not isinstance(pkt["vortices"], list):
        _err(errors, path + ["vortices"], "must be array")
    else:
        for i,v in enumerate(pkt["vortices"]):
            if not isinstance(v, dict):
                _err(errors, path + ["vortices", str(i)], "must be object")
            else:
                validate_vortex(v, path + ["vortices", str(i)], errors)
    # meta_reflection (optional)
    if "meta_reflection" in pkt and not isinstance(pkt["meta_reflection"], dict):
        _err(errors, path + ["meta_reflection"], "must be object")
    # synchronicity_boost (optional)
    if "synchronicity_boost" in pkt and not _is_num(pkt["synchronicity_boost"]):
        _err(errors, path + ["synchronicity_boost"], "must be numeric")
    # caps (optional)
    if "caps" in pkt:
        if not isinstance(pkt["caps"], list):
            _err(errors, path + ["caps"], "must be array")
        else:
            for i,c in enumerate(pkt["caps"]):
                if not isinstance(c, str):
                    _err(errors, path + ["caps",str(i)], "must be string")
    return errors


# ---------- Test Vectors ----------

TV1 = {
  "ver":"1.2",
  "vortices":[
    {"entity":"e1","glyphs":["Ω","Ψ","Φ"],"amp":0.5,"phase":0.0,"center":[0,0,0]}
  ]
}

TV3 = {
  "ver":"1.2",
  "vortices":[
    {"entity":"e3","glyphs":["Φ","⊗","⊕"],"amp":0.77,"phase":1.23,"center":[0.5,-0.5,0.2],
     "tunneled":{"sim_id":"qutip-1","projected_state":"<opaque>"}
    }
  ]
}


# ---------- I/O helpers ----------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_and_print(pkt: Dict[str, Any], label: str = "packet") -> bool:
    errors = validate_packet(pkt)
    if errors:
        print(f"[FAIL] {label}: {len(errors)} error(s)")
        for e in errors:
            print("  -", e)
        return False
    else:
        print(f"[PASS] {label}: schema-valid")
        return True


async def ws_send(endpoint: str, payload: Dict[str, Any], label: str) -> None:
    if websockets is None:
        print("[WARN] websockets not available; cannot connect.")
        return
    async with websockets.connect(endpoint, max_size=4_194_304) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print(f"[WS] Sent {label}.")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            # Try to parse and validate echoes
            try:
                pkt = json.loads(msg)
                validate_and_print(pkt, f"echo_from_server({label})")
            except Exception:
                print("[WS] Received non-JSON response (ignored).")
        except asyncio.TimeoutError:
            print("[WS] No echo within 1s (ok if server is broadcast-only).")


async def ws_recv(endpoint: str, n: int) -> None:
    if websockets is None:
        print("[WARN] websockets not available; cannot connect.")
        return
    async with websockets.connect(endpoint, max_size=4_194_304) as ws:
        for i in range(n):
            msg = await ws.recv()
            try:
                pkt = json.loads(msg)
                validate_and_print(pkt, f"recv[{i}]")
            except Exception as e:
                print(f"[FAIL] recv[{i}]: not valid JSON ({e})")


def main() -> None:
    ap = argparse.ArgumentParser(description="HoloNet v1.2 WebSocket Validator")
    ap.add_argument("--endpoint", help="ws://host:port/holonet (optional)")
    ap.add_argument("--recv", type=int, default=0, help="receive N packets and validate")
    ap.add_argument("--send-tv1", action="store_true", help="send TV-1 to endpoint")
    ap.add_argument("--send-tv3", action="store_true", help="send TV-3 to endpoint")
    ap.add_argument("--file", action="append", help="validate JSON file(s) locally (can repeat)")
    args = ap.parse_args()

    ok_all = True

    # Local file validation
    if args.file:
        for p in args.file:
            try:
                pkt = load_json(p)
                ok = validate_and_print(pkt, p)
                ok_all = ok_all and ok
            except Exception as e:
                print(f"[FAIL] {p}: {e}")
                ok_all = False

    # Endpoint interactions
    if args.endpoint:
        loop = asyncio.get_event_loop()
        if args.send_tv1:
            loop.run_until_complete(ws_send(args.endpoint, TV1, "TV-1"))
        if args.send_tv3:
            loop.run_until_complete(ws_send(args.endpoint, TV3, "TV-3"))
        if args.recv > 0:
            loop.run_until_complete(ws_recv(args.endpoint, args.recv))

    if not args.file and not args.endpoint:
        # Default: validate embedded TV-1 and TV-3
        ok1 = validate_and_print(TV1, "TV-1 (embedded)")
        ok3 = validate_and_print(TV3, "TV-3 (embedded)")
        ok_all = ok1 and ok3

    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
