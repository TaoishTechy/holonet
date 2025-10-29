// 2D CPU renderer — glyph lattice, entanglement, overlays
const DPR = () => Math.max(1, Math.min(2, window.devicePixelRatio || 1));

export class Renderer2D {
  constructor(canvas, opts={}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = Object.assign({
      plane: 'xy',
      slice: 5,
      lod: 1,
      drawEdges: true,
      hud: true
    }, opts);
    this.lastPacket = null;
    this.hover = null;
    this.resize();
    window.addEventListener('resize', () => this.resize());
    canvas.addEventListener('mousemove', (e) => this.onMove(e));
    canvas.addEventListener('click', (e) => this.onClick(e));
  }

  setOptions(opts) { Object.assign(this.opts, opts); }
  setPacket(pkt) { this.lastPacket = pkt; }
  resize() {
    const dpr = DPR();
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.floor(rect.width * dpr);
    this.canvas.height = Math.floor(rect.height * dpr);
    this.ctx.setTransform(dpr,0,0,dpr,0,0);
    this.ctx.font = "16px 'JetBrains Mono', monospace";
    this.ctx.textBaseline = "middle";
    this.ctx.textAlign = "center";
  }

  worldToScreen(x, y) {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const sx = (x + 1.5) / 3.0 * (w - 40) + 20;
    const sy = (y + 1.5) / 3.0 * (h - 40) + 20;
    return [sx, sy];
  }

  projectCenter(center, plane) {
    let x=0, y=0;
    const [cx, cy, cz] = center;
    if (plane === 'xy') { x = cx; y = cy; }
    else if (plane === 'xz') { x = cx; y = cz; }
    else if (plane === 'yz') { x = cy; y = cz; }
    return [x, y];
  }

  hitTest(px, py, list) {
    for (let i = list.length - 1; i >= 0; i--) {
      const it = list[i];
      const [sx, sy] = it.screen;
      const dx = px - sx, dy = py - sy;
      if (dx*dx + dy*dy < 18*18) return it;
    }
    return null;
  }

  onMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    if (!this.lastPacket) return;
    const dots = this.computeDots();
    this.hover = this.hitTest(x, y, dots);
  }

  onClick(e) {
    // noop for now; could pin selection, send psionic_nudge, etc.
  }

  computeDots() {
    const pkt = this.lastPacket;
    const out = [];
    if (!pkt) return out;
    for (const v of pkt.vortices || []) {
      const [xw, yw] = this.projectCenter(v.center, this.opts.plane);
      const [sx, sy] = this.worldToScreen(xw, yw);
      const glyphs = Array.isArray(v.glyphs) && v.glyphs.length ? v.glyphs : ["•"];
      const idx = (Math.floor(Date.now()/500) % glyphs.length);
      const glyph = glyphs[idx];
      out.push({ entity: v.entity, glyph, amp: v.amp, phase: v.phase, screen: [sx, sy], v });
    }
    return out;
  }

  drawGrid() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    ctx.save();
    ctx.strokeStyle = "rgba(122,162,255,0.12)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 6; i++) {
      const x = 20 + i*(w-40)/6;
      const y = 20 + i*(h-40)/6;
      ctx.beginPath(); ctx.moveTo(x,20); ctx.lineTo(x,h-20); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(20,y); ctx.lineTo(w-20,y); ctx.stroke();
    }
    ctx.restore();
  }

  drawEdges(dots) {
    const ctx = this.ctx;
    const ents = new Map(dots.map(d => [d.entity, d]));
    const vort = this.lastPacket?.vortices || [];
    ctx.save();
    ctx.strokeStyle = "rgba(122,162,255,0.35)";
    ctx.lineWidth = 1.25;
    for (const v of vort) {
      if (!v.entangled || !v.entangled.length) continue;
      const a = ents.get(v.entity);
      for (const et of v.entangled) {
        const b = ents.get(et);
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.screen[0], a.screen[1]);
        ctx.lineTo(b.screen[0], b.screen[1]);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  drawDots(dots) {
    const ctx = this.ctx;
    for (const d of dots) {
      const [sx, sy] = d.screen;
      const amp = Math.max(0.1, Math.min(1, d.amp || 0.5));
      const size = 18 + 8 * amp;
      // ring
      ctx.save();
      ctx.beginPath();
      ctx.arc(sx, sy, size*0.55, 0, Math.PI*2);
      ctx.strokeStyle = "rgba(122,162,255,0.45)";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
      // glyph
      ctx.save();
      ctx.fillStyle = "#e6f1ff";
      ctx.font = `${14 + 8*amp}px 'JetBrains Mono', monospace`;
      ctx.fillText(d.glyph, sx, sy);
      ctx.restore();
    }
  }

  drawHUD() {
    if (!this.opts.hud) return;
    const el = document.getElementById('overlay');
    if (!this.hover) {
      if (el) el.remove();
      return;
    }
    const v = this.hover.v;
    let hud = document.getElementById('overlay');
    if (!hud) {
      const div = document.createElement('div');
      div.id = 'overlay';
      div.className = 'overlay';
      document.body.appendChild(div);
      hud = div;
    }
    hud.innerHTML = `<h3>${v.entity}</h3><pre>${JSON.stringify({
      amp: v.amp.toFixed ? v.amp.toFixed(3) : v.amp,
      phase: v.phase.toFixed ? v.phase.toFixed(3) : v.phase,
      center: v.center,
      superposition: v.superposition,
      entangled: v.entangled,
      volition: v.volition
    }, null, 2)}</pre>`;
  }

  frame() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    ctx.clearRect(0,0,w,h);
    this.drawGrid();
    const dots = this.computeDots();
    if (this.opts.drawEdges) this.drawEdges(dots);
    this.drawDots(dots);
    this.drawHUD();
  }
}
