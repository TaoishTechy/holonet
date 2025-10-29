
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
HoloNet CLI Client (non-GUI, v1.2)
Connects to a HoloNet WS and renders ASCII lattice slices in the terminal.

import sys, asyncio, json, time, math, threading
import argparse

try:
    import websockets
except Exception as e:
    print("ERROR: websockets not installed. pip install websockets", file=sys.stderr)
    raise

ANSI = {
    "reset": "\x1b[0m",
    "dim": "\x1b[2m",
    "bold": "\x1b[1m",
    "clear": "\x1b[2J\x1b[H",
}

def amp_to_color(amp: float) -> str:
    amp = max(0.0, min(1.0, float(amp)))
    if amp < 0.5:
        t = amp / 0.5
        code = int(36 + t * (46 - 36))
    else:
        t = (amp - 0.5) / 0.5
        code = int(46 + t * (226 - 46))
    return f"\x1b[38;5;{code}m"

def build_grid(size: int):
    return [["·" for _ in range(size)] for _ in range(size)]

def clamp_idx(i: int, size: int) -> int:
    return max(0, min(size - 1, i))

def voxel_from_center(center, size):
    sx = clamp_idx(round((center[0] + 1.0) * (size-1) / 2.0), size)
    sy = clamp_idx(round((center[1] + 1.0) * (size-1) / 2.0), size)
    sz = clamp_idx(round((center[2] + 1.0) * (size-1) / 2.0), size)
    return sx, sy, sz

def render_ascii(packet, plane: str, index: int, size: int, color: bool) -> str:
    grid = build_grid(size)
    vortices = packet.get("vortices", [])
    for v in vortices:
        center = v.get("center", [0.0, 0.0, 0.0])
        glyphs = v.get("glyphs", ["Ω","Ψ","Φ"])
        amp = float(v.get("amp", 0.5))
        sx, sy, sz = voxel_from_center(center, size)

        if plane == "xy" and sz == index:
            x, y = sx, size-1 - sy
        elif plane == "xz" and sy == index:
            x, y = sx, size-1 - sz
        elif plane == "yz" and sx == index:
            x, y = sy, size-1 - sz
        else:
            continue

        ch = glyphs[ int(time.time()*2) % len(glyphs) ]
        if color:
            grid[y][x] = amp_to_color(amp) + ch + ANSI["reset"]
        else:
            grid[y][x] = ch

    border = "+" + "-"*size + "+"
    lines = [border]
    for row in grid:
        lines.append("|" + "".join(row) + "|")
    lines.append(border)
    return "\n".join(lines)

class CLIClient:
    def __init__(self, ws_url: str, token: str = "", plane: str = "xy", index: int = 1, size: int = 3, fps: int = 10, color: bool = True):
        self.ws_url = ws_url
        self.token = token
        self.plane = plane
        self.index = index
        self.size = size
        self.fps = max(1, fps)
        self.color = color
        self.paused = False
        self.latest_packet = {"ver":"1.2","vortices":[]}
        self._stop = False
        self._ws = None

    async def _rx_loop(self):
        url = self.ws_url
        if self.token and "token=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}token={self.token}"
        async with websockets.connect(url, max_size=4_194_304) as ws:
            self._ws = ws
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if isinstance(data, dict) and "vortices" in data:
                        self.latest_packet = data
                except Exception:
                    continue

    async def _tx_nudge(self, entity: str, force: float = 0.2, dphi: float = 0.6):
        if not self._ws: return
        payload = {"action":"psionic_nudge","target_entity":entity,"force":float(force),"dphi":float(dphi)}
        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            pass

    def _print_help(self):
        print("Commands:")
        print("  h                 help")
        print("  q                 quit")
        print("  p                 pause/resume rendering")
        print("  plane xy|xz|yz    switch projection plane")
        print("  index N           set slice index (0..size-1)")
        print("  size N            set lattice render size (3/5/12 etc.)")
        print("  color on|off      toggle ANSI coloring")
        print("  nudge <entity> <force> <dphi>")
        print("  snap              write holonet_snapshot.json")

    def _reader_thread(self, loop):
        while not self._stop:
            try:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.05); continue
                parts = line.strip().split()
                if not parts: continue
                cmd = parts[0].lower()

                if cmd == "q":
                    self._stop = True
                elif cmd == "h":
                    self._print_help()
                elif cmd == "p":
                    self.paused = not self.paused
                elif cmd == "plane" and len(parts)>=2:
                    if parts[1] in ("xy","xz","yz"):
                        self.plane = parts[1]
                        print(f"plane -> {self.plane}")
                elif cmd == "index" and len(parts)>=2:
                    try:
                        n = int(parts[1]); self.index = max(0, min(self.size-1, n)); print(f"index -> {self.index}")
                    except ValueError:
                        print("index expects integer")
                elif cmd == "size" and len(parts)>=2:
                    try:
                        n = int(parts[1]); self.size = max(1, min(64, n)); print(f"size -> {self.size}")
                    except ValueError:
                        print("size expects integer")
                elif cmd == "color" and len(parts)>=2:
                    self.color = (parts[1].lower()=="on"); print(f"color -> {'on' if self.color else 'off'}")
                elif cmd == "nudge" and len(parts)>=2:
                    ent = parts[1]
                    force = float(parts[2]) if len(parts)>=3 else 0.2
                    dphi = float(parts[3]) if len(parts)>=4 else 0.6
                    asyncio.run_coroutine_threadsafe(self._tx_nudge(ent, force, dphi), loop)
                elif cmd == "snap":
                    try:
                        with open("holonet_snapshot.json","w",encoding="utf-8") as f:
                            json.dump(self.latest_packet, f, ensure_ascii=False, indent=2)
                        print("snapshot -> holonet_snapshot.json")
                    except Exception as e:
                        print(f"snapshot failed: {e}")
                else:
                    print("unknown command; 'h' for help")
            except Exception:
                time.sleep(0.05)

    async def run(self):
        loop = asyncio.get_event_loop()
        t = threading.Thread(target=self._reader_thread, args=(loop,), daemon=True)
        t.start()

        rx = asyncio.create_task(self._rx_loop())
        last = 0.0
        try:
            while not self._stop:
                now = time.time()
                if now - last >= 1.0/self.fps:
                    last = now
                    if not self.paused:
                        sys.stdout.write(ANSI["clear"])
                        sys.stdout.write(f"HoloNet CLI v1.2  |  plane {self.plane}  index {self.index}  size {self.size}  fps {self.fps}  color {'on' if self.color else 'off'}\n")
                        sys.stdout.write("Commands: h help • q quit • p pause • plane xy|xz|yz • index N • size N • color on|off • nudge <ent> [force dphi] • snap\n\n")
                        frame = render_ascii(self.latest_packet, self.plane, self.index, self.size, self.color)
                        sys.stdout.write(frame + "\n")
                        ents = len(self.latest_packet.get("vortices", []))
                        coh = self.latest_packet.get("meta_reflection",{}).get("coherence","?")
                        sys.stdout.write(f"\nentities {ents}  coherence {coh}\n")
                        sys.stdout.flush()
                await asyncio.sleep(0.005)
        finally:
            rx.cancel()
            try:
                await rx
            except asyncio.CancelledError:
                pass
            self._stop = True

def main():
    ap = argparse.ArgumentParser(description="HoloNet CLI (non-GUI)")
    ap.add_argument("--ws", required=True, help="WebSocket URL, e.g., ws://localhost:8765/holonet")
    ap.add_argument("--token", default="", help="Bearer token (also appended as ?token=)")
    ap.add_argument("--plane", default="xy", choices=["xy","xz","yz"])
    ap.add_argument("--index", type=int, default=1)
    ap.add_argument("--size", type=int, default=3)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = ap.parse_args()

    client = CLIClient(ws_url=args.ws, token=args.token, plane=args.plane, index=args.index, size=args.size, fps=args.fps, color=(not args.no_color))
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
