// HoloNet v2.0 — networking utilities (WS + simulator fallback)
export class HoloNetWS {
  constructor(url, onPacket, onStatus) {
    this.url = url;
    this.onPacket = onPacket;
    this.onStatus = onStatus;
    this.ws = null;
    this.reconnectTimer = null;
  }

  connect() {
    try {
      this.ws = new WebSocket(this.url);
      this.onStatus?.(`connecting ${this.url}`);
      this.ws.addEventListener('open', () => {
        this.onStatus?.('connected');
      });
      this.ws.addEventListener('message', (ev) => {
        try {
          const pkt = JSON.parse(ev.data);
          if (pkt && pkt.vortices) this.onPacket(pkt);
        } catch (e) {
          console.warn('bad packet', e);
        }
      });
      this.ws.addEventListener('close', () => {
        this.onStatus?.('disconnected');
      });
      this.ws.addEventListener('error', (e) => {
        this.onStatus?.('error');
        console.error(e);
      });
    } catch (e) {
      this.onStatus?.('error');
      console.error(e);
    }
  }

  send(obj) {
    if (this.ws && this.ws.readyState === 1) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

// Very light CPU-first simulator (matches v1.2 schema shape)
export class Simulator {
  constructor(onPacket) {
    this.onPacket = onPacket;
    this.t = 0;
    this.timer = null;
    this.entities = 12;
  }
  start() {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), 50);
  }
  stop() {
    clearInterval(this.timer);
    this.timer = null;
  }
  tick() {
    this.t += 0.05;
    const vortices = [];
    for (let i = 0; i < this.entities; i++) {
      const amp = 0.6 + 0.2 * Math.sin(this.t * 1.2 + i);
      const phase = (this.t + i * 0.25) % (Math.PI * 2);
      const cx = ((i % 3) - 1) + 0.25 * Math.sin(this.t * 0.8 + i);
      const cy = (Math.floor(i / 3) - 1) + 0.25 * Math.cos(this.t * 0.7 + i);
      const cz = ((Math.floor(i / 6)) - 0.5);

      const glyphSets = [["Ω","Ψ","Φ"],["⊗","⊕","⦿"],["Θ","!","⟳"],["*","✶","✺"],["≡","λ","τ"],["?","…","∞"],["◈","⟡","⊻"],["≀","∴","⦿"]];
      const glyphs = glyphSets[i % glyphSets.length];

      vortices.push({
        entity: `entity-${i+1}`,
        glyphs,
        amp,
        phase,
        center: [cx, cy, cz],
        superposition: (i % 2 === 0),
        entangled: (i < this.entities - 1) ? [`entity-${i+2}`] : [],
        healing_properties: {},
        predicted: { "t+250ms": { amp: Math.min(1.0, amp + 0.02), phase: (phase + 0.25) % (Math.PI*2) } },
        volition: { intent: "observe", drive_strength: 0.0 }
      });
    }
    const pkt = { ver: "1.2", vortices, meta_reflection: { coherence: 0.82 }, synchronicity_boost: 1.0 };
    this.onPacket(pkt);
  }
}
