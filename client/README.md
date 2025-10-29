# HoloNet v2.0 — CPU‑First Lattice Client

This client renders the HoloNet lattice with a **CPU‑first 2D renderer** (optional WebGL placeholder) and consumes the **v1.2 outbound schema** from your `holonet_serv.py`.

## Features
- 2D glyph lattice with amplitude (ring size) & phase (glyph spin) cues
- Entanglement edges toggle
- HUD overlay on hover with entity details
- Plane selection (XY/XZ/YZ), slice slider, LOD stub
- Live WebSocket stream or local **Simulator** fallback
- WebGL toggle (placeholder renderer; add your shaders later)

## Quickstart
1. Start your server (example):
   ```bash
   python3 holonet_serv.py --tick-hz 20
   ```
2. Open `index.html` in a local HTTP server (recommended to avoid CORS issues):
   ```bash
   python3 -m http.server 8888
   # then visit http://localhost:8888/
   ```
3. Paste your WS URL (default `ws://localhost:8765/holonet`) and click **Connect**.
4. Or enable **Simulate** to run the local generator.

## Files
- `index.html` — UI + canvases
- `css/styles.css` — visual styling
- `js/main.js` — app wiring, UI handlers, frame loop
- `js/net.js` — WebSocket client + Simulator
- `js/render2d.js` — CPU glyph renderer (science‑grade & efficient)
- `js/render3d.js` — WebGL placeholder class
- `assets/glyphs.json` — sample glyph library (optional)

## Notes
- The renderer uses device‑pixel‑ratio aware scaling and avoids re‑allocations in the hot path.
- The packet shape expected is: `{ ver, vortices:[{ entity, glyphs[], amp, phase, center[3], superposition, entangled[], healing_properties, predicted, volition }], meta_reflection, synchronicity_boost }`.

