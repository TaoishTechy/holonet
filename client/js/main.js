// ---------- Utilities ----------
const $ = sel => document.querySelector(sel);
const logEl = $('#log');
const log = (...a) => { const s = a.map(x => typeof x==='string'?x:JSON.stringify(x)).join(' ');
  logEl.textContent = `${new Date().toISOString()} ${s}\n` + logEl.textContent.slice(0, 20000);
  console.debug('[HoloNet]', ...a);
};
const clamp = (v,min,max)=>Math.max(min,Math.min(max,v));
const lerp = (a,b,t)=>a+(b-a)*t;

// ---------- State ----------
const state = {
  ws: null,
  wsUrl: '',
  wsToken: '',
  backoff: 750,
  lastPacket: null,
  lastTS: performance.now(),
  fps: 0,
  paused: false,
  simulate: false,
  httpFallback: false,
  httpTimer: null,
  dpr: window.devicePixelRatio || 1,
  opts: { plane:'xy', slice:0, lod:1, edges:true, volition:true, useGL:false },
};

// ---------- DOM refs ----------
const hud = {
  wsurl: $('#wsurl'),
  wstoken: $('#wstoken'),
  connect: $('#connect'),
  disconnect: $('#disconnect'),
  simulate: $('#simulate'),
  httpFallback: $('#httpFallback'),
  toggleGL: $('#toggleGL'),
  plane: $('#plane'),
  slice: $('#slice'),
  lod: $('#lod'),
  edges: $('#edges'),
  volition: $('#volition'),
  pause: $('#pause'),
  httpBase: $('#httpBase'),
  fetchStatus: $('#fetchStatus'),
  fetchFrame: $('#fetchFrame'),
  fps: $('#fps'),
  coh: $('#coh'),
  ents: $('#ents'),
  net: $('#net'),
};

const c2d = $('#canvas2d');
const g2d = c2d.getContext('2d');

// ---------- Resize ----------
function resize() {
  const rect = c2d.getBoundingClientRect();
  c2d.width = Math.floor(rect.width * state.dpr);
  c2d.height = Math.floor(rect.height * state.dpr);
}
addEventListener('resize', resize);
resize();

// ---------- Networking ----------
function normalizeWsUrl(raw) {
  try {
    const u = new URL(raw, window.location.href);
    // upgrade when page is https:
    if (location.protocol === 'https:' && u.protocol === 'ws:') u.protocol = 'wss:';
    // ensure path startswith /holonet
    if (!u.pathname || !u.pathname.startsWith('/holonet')) u.pathname = '/holonet';
    return u.toString();
  } catch {
    return raw;
  }
}

async function connectWS() {
  if (state.ws) try { state.ws.close(); } catch {}
  state.wsUrl = normalizeWsUrl(hud.wsurl.value.trim());
  state.wsToken = hud.wstoken.value.trim();
  const headers = state.wsToken ? { Authorization: `Bearer ${state.wsToken}` } : undefined;

  log('Connecting WS:', state.wsUrl);
  hud.net.className = 'chip warn'; hud.net.textContent = 'connecting…';

  // Some browsers ignore headers in native WebSocket; we pass token via query too
  const urlObj = new URL(state.wsUrl);
  if (state.wsToken && !urlObj.searchParams.get('token')) {
    urlObj.searchParams.set('token', state.wsToken);
  }

  let ws;
  try {
    ws = new WebSocket(urlObj.toString(), []); // subprotocols empty
  } catch (e) {
    log('WS ctor error:', e);
    failWS();
    return;
  }

  state.ws = ws;

  ws.onopen = () => {
    hud.net.className = 'chip ok'; hud.net.textContent = 'connected';
    log('WS open');
    state.backoff = 750;
    // App-level keepalive (server ignores unknown actions safely)
    state.pingTimer = setInterval(() => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ action:'ping', t: Date.now() }));
      }
    }, 15000);
  };

  ws.onmessage = ev => {
    try {
      const pkt = JSON.parse(ev.data);
      state.lastPacket = pkt;
      renderHud(pkt);
    } catch (e) {
      log('WS parse error:', e);
    }
  };

  ws.onerror = (e) => {
    log('WS error:', e);
  };

  ws.onclose = () => {
    log('WS closed');
    if (state.pingTimer) clearInterval(state.pingTimer);
    failWS();
  };
}

function failWS() {
  state.ws = null;
  hud.net.className = 'chip bad'; hud.net.textContent = 'disconnected';
  // If fallback is enabled, HTTP polling picks up; else retry
  if (!state.httpFallback && !state.simulate) {
    const wait = clamp(state.backoff, 750, 10_000);
    state.backoff = Math.min(10_000, state.backoff * 1.6);
    setTimeout(connectWS, wait);
    hud.net.className = 'chip warn'; hud.net.textContent = `retry in ${Math.round(wait/1000)}s`;
  }
}

// ---------- HTTP Fallback ----------
async function startHttpFallback() {
  stopHttpFallback();
  const base = hud.httpBase.value.replace(/\/+$/,'');
  if (!base) return;
  log('HTTP fallback polling', base);
  hud.net.className = 'chip warn'; hud.net.textContent = 'polling…';
  state.httpTimer = setInterval(async () => {
    try {
      const r = await fetch(`${base}/quantum_frame`, { cache:'no-store' });
      if (!r.ok) throw new Error(r.status);
      const pkt = await r.json();
      // Wrap into a packet-shaped object so renderer can ingest it
      state.lastPacket = frameToPacket(pkt);
      renderHud(state.lastPacket);
      hud.net.className = 'chip ok'; hud.net.textContent = 'HTTP';
    } catch (e) {
      hud.net.className = 'chip bad'; hud.net.textContent = 'HTTP err';
      log('HTTP poll error:', e);
    }
  }, 250); // 4 FPS safe for CPU
}
function stopHttpFallback() {
  if (state.httpTimer) clearInterval(state.httpTimer);
  state.httpTimer = null;
}
function frameToPacket(frame){
  // Minimal adapter to v1.2 shape
  const vortices = [];
  const M = frame?.Layers?.Matrix || {};
  let i=0;
  for (const k in M){
    if (!Object.hasOwn(M,k)) continue;
    const g = M[k];
    const [x,y] = k.slice(1,-1).split(',').map(n=>parseInt(n,10));
    // Map grid back to [-1.5,1.5] approx
    const w = frame.Dimensions?.width || 80;
    const h = frame.Dimensions?.height || 36;
    const cx = (x/(w-1))*3.0 - 1.5;
    const cy = (y/(h-1))*3.0 - 1.5;
    vortices.push({
      entity:`f${i++}`, glyphs:[String(g)], amp:0.6, phase:0.0,
      center:[cx, cy, 0], superposition:false, entangled:[]
    });
  }
  return { ver:'1.2', vortices, meta_reflection:{ coherence: 0.5 }, synchronicity_boost:1.0 };
}

// ---------- Simulator (offline) ----------
function stepSimulator(dt){
  if (!state.lastPacket){
    state.lastPacket = { ver:'1.2', vortices:[], meta_reflection:{coherence:.5} };
    for (let i=0;i<18;i++){
      const phi = (i*0.7) % (Math.PI*2);
      state.lastPacket.vortices.push({
        entity:`sim-${i+1}`,
        glyphs:['Ω','Ψ','Φ'],
        amp:0.6, phase:phi,
        center:[(i%3)-1, Math.floor(i/3)-1, (Math.floor(i/6)-.5)],
        superposition:(i%2===0),
        entangled:[]
      });
    }
  }
  const t = performance.now()/1000;
  for (const v of state.lastPacket.vortices){
    v.phase = (v.phase + 1.2*dt)%(Math.PI*2);
    v.amp = clamp(0.6 + 0.1*((t*2+v.center[0])%3) + 0.05*Math.sin(t*3+v.center[1]), 0, 1);
    v.center[0] += 0.02*Math.sin(t*2 + v.center[1]);
  }
  // couple pairs
  const vs = state.lastPacket.vortices;
  for (let i=0;i+1<vs.length;i+=2){ vs[i].entangled=[vs[i+1].entity]; vs[i+1].entangled=[vs[i].entity]; }
}

// ---------- Rendering (CPU 2D) ----------
function renderHud(pkt){
  const coh = pkt?.meta_reflection?.coherence ?? null;
  const n = pkt?.vortices?.length ?? 0;
  hud.coh.textContent = `Coherence: ${coh!==null?coh.toFixed(2):'--'}`;
  hud.ents.textContent = `Entities: ${n}`;
}
function project(v){
  const [x,y,z] = v.center;
  let X=0,Y=0,D=0;
  const s = parseInt(hud.slice.value,10)/6.0; // -2..2 approx
  switch(hud.plane.value){
    case 'xy': if (Math.abs(z - s) > 1.2) return null; X=x; Y=y; D=z; break;
    case 'xz': if (Math.abs(y - s) > 1.2) return null; X=x; Y=z; D=y; break;
    case 'yz': if (Math.abs(x - s) > 1.2) return null; X=y; Y=z; D=x; break;
  }
  return {X,Y,D};
}
function ampToColor(a){
  // teal -> cyan -> white ramp
  const g = Math.floor(120 + a*100);
  const b = Math.floor(180 + a*75);
  return `rgb(${Math.floor(a*90)},${g},${b})`;
}
function draw(){
  const now = performance.now();
  const dt = (now - state.lastTS)/1000;
  state.lastTS = now;

  if (state.simulate) stepSimulator(dt);

  // FPS
  const fps = 1/dt; state.fps = fps*0.08 + state.fps*0.92;
  hud.fps.textContent = `FPS: ${state.fps.toFixed(0)}`;

  // Clear
  const W = c2d.width, H = c2d.height;
  g2d.clearRect(0,0,W,H);

  // Grid
  g2d.strokeStyle = '#172027'; g2d.lineWidth = 1;
  g2d.beginPath();
  for (let i=0;i<10;i++){
    const x = Math.round((i/9)*W)+.5; g2d.moveTo(x,0); g2d.lineTo(x,H);
    const y = Math.round((i/9)*H)+.5; g2d.moveTo(0,y); g2d.lineTo(W,y);
  }
  g2d.stroke();

  const pkt = state.lastPacket;
  if (!pkt || !pkt.vortices || !pkt.vortices.length) return;

  const lod = parseInt(hud.lod.value,10);
  const step = lod; // sample every N vertices

  const nodes = [];
  // draw edges later (store projected coordinates)
  for (let i=0;i<pkt.vortices.length;i+=step){
    const v = pkt.vortices[i];
    const pr = project(v);
    if (!pr) continue;
    const X = (pr.X + 1.5) / 3.0 * W;
    const Y = (1 - (pr.Y + 1.5) / 3.0) * H;
    const r = clamp(3 + v.amp*6, 3, 12) * (state.dpr);
    const color = ampToColor(v.amp);

    // node
    g2d.fillStyle = color;
    g2d.beginPath();
    g2d.arc(X, Y, r, 0, Math.PI*2);
    g2d.fill();

    // glyph
    const glyph = v.glyphs?.[ Math.floor((Date.now()/500 + i) % (v.glyphs.length||1)) ] || 'Ω';
    g2d.fillStyle = '#0b1014';
    g2d.font = `${Math.max(10, r*1.4)}px ui-monospace,monospace`;
    g2d.textAlign = 'center'; g2d.textBaseline = 'middle';
    g2d.fillText(glyph, X, Y);

    // volition overlay
    if (hud.volition.checked && v.volition?.intent) {
      g2d.fillStyle = '#9aa4ad';
      g2d.font = `${Math.max(9, r*1.0)}px Inter,system-ui`;
      g2d.fillText(v.volition.intent, X, Y - r - 8*state.dpr);
    }

    nodes.push({ X, Y, id: v.entity });
  }

  // entanglement edges
  if (hud.edges.checked){
    g2d.strokeStyle = 'rgba(110,231,255,0.6)';
    g2d.lineWidth = 1.5*state.dpr;
    const map = new Map(nodes.map(n=>[n.id,n]));
    for (let i=0;i<pkt.vortices.length;i+=step){
      const v = pkt.vortices[i];
      if (!v.entangled || !v.entangled.length) continue;
      const a = map.get(v.entity); if (!a) continue;
      for (const eid of v.entangled){
        const b = map.get(eid); if (!b) continue;
        g2d.beginPath(); g2d.moveTo(a.X, a.Y); g2d.lineTo(b.X, b.Y); g2d.stroke();
      }
    }
  }
}

// ---------- UI wiring ----------
hud.connect.onclick = () => {
  state.simulate = hud.simulate.checked = false;
  state.httpFallback = hud.httpFallback.checked;
  if (state.httpFallback) startHttpFallback(); else stopHttpFallback();
  connectWS();
};
hud.disconnect.onclick = () => {
  stopHttpFallback();
  if (state.ws) { try{ state.ws.close(); }catch{} state.ws=null; }
  hud.net.className = 'chip idle'; hud.net.textContent = 'idle';
};
hud.simulate.onchange = () => {
  state.simulate = hud.simulate.checked;
  if (state.simulate) { stopHttpFallback(); if (state.ws) { try{state.ws.close();}catch{} state.ws=null; } }
};
hud.httpFallback.onchange = () => {
  state.httpFallback = hud.httpFallback.checked;
  if (state.httpFallback) { stopWS(); startHttpFallback(); } else { stopHttpFallback(); }
};
function stopWS(){ if (state.ws) { try{state.ws.close();}catch{} state.ws=null; } }
hud.toggleGL.onchange = () => {
  state.opts.useGL = hud.toggleGL.checked;
  $('#canvas3d').style.display = state.opts.useGL ? 'block' : 'none';
};
hud.plane.onchange = ()=>{};
hud.slice.oninput = ()=>{};
hud.lod.oninput = ()=>{};
hud.edges.onchange = ()=>{};
hud.volition.onchange = ()=>{};
hud.pause.onchange = ()=>{ state.paused = hud.pause.checked; };

hud.fetchStatus.onclick = async ()=>{
  try{
    const r = await fetch(`${hud.httpBase.value.replace(/\/+$/,'')}/status`); 
    log('STATUS:', await r.text());
  }catch(e){ log('status err', e); }
};
hud.fetchFrame.onclick = async ()=>{
  try{
    const r = await fetch(`${hud.httpBase.value.replace(/\/+$/,'')}/quantum_frame`);
    log('FRAME:', await r.text());
  }catch(e){ log('frame err', e); }
};

// ---------- Loop ----------
function loop(){
  if (!state.paused) draw();
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

// Auto-connect if default looks reachable
setTimeout(()=>{
  // If served over https, force wss in the input field
  if (location.protocol === 'https:' && hud.wsurl.value.startsWith('ws:')){
    hud.wsurl.value = hud.wsurl.value.replace(/^ws:/,'wss:');
  }
},0);
