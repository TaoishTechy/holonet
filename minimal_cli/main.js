/* main.js — HoloNet v2.4.2 client
   Compatible with server.py v2.3-patched-v2 (proto 1.2)
   Fixes: reliable DEBUG via ?debug=1 (or 0..4), proper level clamping,
          console mirroring, and guaranteed log panel presence.
*/

(() => {
  // ---------- DOM helpers ----------
  function $(id){ return document.getElementById(id); }
  function ensureLogPanel(){
    let node = $('log');
    if (!node){
      node = document.createElement('div');
      node.id = 'log';
      node.style.height = '150px';
      node.style.overflowY = 'auto';
      node.style.margin = '8px 0';
      node.style.fontFamily = 'monospace';
      node.style.fontSize = '12px';
      node.style.color = '#9eff9e';
      document.body.appendChild(node);
    }
    return node;
  }

  const statusEl = $('status');
  const sigilEl  = $('sigilDisplay');
  const logEl    = ensureLogPanel();
  const canvas   = $('frameCanvas');
  const overlay  = $('canvasOverlay');
  const ctx      = canvas.getContext('2d');

  const connectBtn    = $('connectBtn');
  const disconnectBtn = $('disconnectBtn');
  const transformBtn  = $('transformBtn');

  const vSlider = $('velocity');
  const zSlider = $('horizon');
  const wSlider = $('width');
  const hSlider = $('height');

  const vValue = $('vValue');
  const zValue = $('zValue');
  const wValue = $('wValue');
  const hValue = $('hValue');

  // ---------- Logging (lightweight + reliable) ----------
  const Levels = { OFF:0, ERROR:1, WARN:2, INFO:3, DEBUG:4 };
  const Names  = ['OFF','ERROR','WARN','INFO','DEBUG'];

  function parseDebugParam(){
    const m = /[?&]debug=([^&#]+)/.exec(window.location.search);
    if (!m) return null;
    const raw = decodeURIComponent(m[1]);
    if (raw === 'true' || raw === '1') return 4;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? Math.max(0, Math.min(4, n)) : null;
  }
  const urlLevel = parseDebugParam();
  let logLevel = (urlLevel != null
                  ? urlLevel
                  : (Number.isFinite(parseInt(localStorage.getItem('holonet.logLevel'),10))
                      ? Math.max(0, Math.min(4, parseInt(localStorage.getItem('holonet.logLevel'),10)))
                      : Levels.WARN));

  const RING_MAX = 800;
  const ring = [];
  let panelVisible = true;
  let lastKey = '', lastCount = 0;

  function push(level, msg){
    if (level > logLevel || level === Levels.OFF) return;
    const ts = new Date().toISOString().slice(11,19);
    const key = level + '|' + msg;
    if (key === lastKey){
      lastCount++;
      const node = logEl.lastElementChild;
      if (node) node.textContent = `${ts} x${lastCount} | ${msg}`;
      const last = ring[ring.length-1]; if (last){ last.ts = ts; last.count = lastCount; }
    } else {
      lastKey = key; lastCount = 1;
      const line = document.createElement('div');
      if (level === Levels.ERROR) line.classList.add('error');
      if (level === Levels.WARN)  line.classList.add('warn');
      line.textContent = `${ts} | ${msg}`;
      if (panelVisible){ logEl.appendChild(line); logEl.scrollTop = logEl.scrollHeight; }
      ring.push({ts,level,msg,count:1});
      if (ring.length > RING_MAX) ring.shift();
    }
    // Mirror to console for devtools visibility
    const prefix = `[${Names[level]}]`;
    if (level === Levels.ERROR) console.error(prefix, msg);
    else if (level === Levels.WARN) console.warn(prefix, msg);
    else console.log(prefix, msg);
  }
  const Log = {
    error: (m)=>push(Levels.ERROR,m),
    warn:  (m)=>push(Levels.WARN,m),
    info:  (m)=>push(Levels.INFO,m),
    debug: (m)=>push(Levels.DEBUG,m),
  };

  document.addEventListener('keydown', (e) => {
    if (!e.ctrlKey) return;
    if (e.code === 'KeyL'){ panelVisible = !panelVisible; logEl.style.display = panelVisible ? '' : 'none'; e.preventDefault(); }
    if (e.code === 'KeyD'){ logLevel = (logLevel+1)%5; localStorage.setItem('holonet.logLevel', String(logLevel)); Log.info(`Log level → ${Names[logLevel]}`); e.preventDefault(); }
    if (e.code === 'KeyS'){ saveLog(); e.preventDefault(); }
  });
  function saveLog(){
    const lines = ring.map(r => `${r.ts} [${Names[r.level]}]${r.count>1?` x${r.count}`:''} ${r.msg}`);
    const blob = new Blob([lines.join('\n')+'\n'], {type:'text/plain'});
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `holonet_client_${Date.now()}.log`; document.body.appendChild(a); a.click();
    setTimeout(()=>{ URL.revokeObjectURL(url); a.remove(); }, 0);
  }

  // ---------- Client state ----------
  let ws = null, connected = false;
  let heartbeatTimer = null, fpsTimer = null;
  let framesThisSecond = 0, fps = 0, latencyMs = 0;
  let dimW = 64, dimH = 32;
  const grid = new Map();

  // ---------- Utils ----------
  const now = () => Date.now();
  const setStatus = (t) => statusEl && (statusEl.textContent = t);
  const updateHUD = () => {
    const sess = ws ? (ws._sessionId || '—') : 'None';
    if (statusEl){
      statusEl.textContent = `Status: [${connected ? 'Connected' : 'Disconnected'}] | Session: ${sess} | Latency: ${latencyMs.toFixed(1)}ms | FPS: ${fps}`;
    }
  };

  const shades = ['#001800','#003100','#004a00','#006300','#007c00','#009500','#00ae00','#00c700','#00e000','#00ff00'];
  function drawCell(x,y,v){
    const cw = Math.max(1, Math.floor(canvas.width  / dimW));
    const ch = Math.max(1, Math.floor(canvas.height / dimH));
    const idx = Math.max(0, Math.min(9, v|0));
    ctx.fillStyle = shades[idx];
    ctx.fillRect(x*cw, y*ch, cw, ch);
  }
  function redrawAll(){
    ctx.fillStyle = '#000'; ctx.fillRect(0,0,canvas.width,canvas.height);
    for (const [k,v] of grid){ const [x,y] = k.split(',').map(Number); drawCell(x,y,v); }
  }
  function resizeCanvasToView(){
    const w = Math.max(16, parseInt(wSlider?.value||'64',10));
    const h = Math.max(8,  parseInt(hSlider?.value||'32',10));
    const mul = 8; canvas.width = w*mul; canvas.height = h*mul; redrawAll();
  }

  // ---------- WS logic ----------
  function wsUrl(){
    const host = window.location.hostname || 'localhost';
    return `ws://${host}:8765/holonet?proto=1.2`;
  }
  function send(obj){
    if (ws && ws.readyState === WebSocket.OPEN){
      ws.send(JSON.stringify(obj));
      Log.debug(`[TX] ${obj.op}`);
    }
  }
  function startHeartbeat(){
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN){
        send({ op:'heartbeat', ts: now(), phiRate: parseFloat(vSlider?.value||'0.5') });
      }
    }, 250); // 4 Hz
  }
  function stopHeartbeat(){ if (heartbeatTimer){ clearInterval(heartbeatTimer); heartbeatTimer = null; } }
  function startFpsMeter(){
    stopFpsMeter();
    fpsTimer = setInterval(()=>{ fps = framesThisSecond; framesThisSecond = 0; updateHUD(); }, 1000);
  }
  function stopFpsMeter(){ if (fpsTimer){ clearInterval(fpsTimer); fpsTimer = null; } }

  function attachEvents(){
    if (connectBtn)   connectBtn.addEventListener('click', connect);
    if (disconnectBtn)disconnectBtn.addEventListener('click', disconnect);
    if (transformBtn) transformBtn.addEventListener('click', ()=>{ send({op:'transform', z: parseInt(zSlider?.value||'0',10)}); Log.info('[TX] transform requested'); });

    const onSlider = () => {
      if (vValue) vValue.textContent = parseFloat(vSlider?.value||'0.5').toFixed(2);
      if (zValue) zValue.textContent = zSlider?.value||'0';
      if (wValue) wValue.textContent = wSlider?.value||'64';
      if (hValue) hValue.textContent = hSlider?.value||'32';
      resizeCanvasToView();
      send({ op:'view', view:{ w: parseInt(wSlider?.value||'64',10), h: parseInt(hSlider?.value||'32',10), z: parseInt(zSlider?.value||'0',10) } });
    };
    vSlider && vSlider.addEventListener('input', onSlider);
    zSlider && zSlider.addEventListener('input', onSlider);
    wSlider && wSlider.addEventListener('input', onSlider);
    hSlider && hSlider.addEventListener('input', onSlider);
    onSlider();
  }

  function connect(){
    if (connected) return;
    ws = new WebSocket(wsUrl());

    ws.addEventListener('open', () => {
      connected = true;
      setButtons(true);
      Log.info(`[OPEN] ${wsUrl()}`);
      updateHUD(); startHeartbeat(); startFpsMeter();
    });

    ws.addEventListener('message', (ev) => {
      let data = ev.data;
      try { data = JSON.parse(ev.data); } catch {}
      if (typeof data === 'string'){ Log.debug(`[RECV text] ${data}`); return; }
      Log.debug(`[RECV] ${data.op}`);

      switch (data.op){
        case 'hello':
          ws._sessionId = (Math.random().toString(16).slice(2,10));
          Log.info(`[HELLO] server=${data.server} proto=${data.proto} frames=${data.frames_version}`);
          break;
        case 'pong':
          if (typeof data.ts === 'number'){ latencyMs = now() - data.ts; updateHUD(); }
          break;
        case 'frame':
          handleFrame(data); break;
        default:
          Log.debug(JSON.stringify(data));
      }
    });

    ws.addEventListener('close', (ev) => { Log.warn(`[CLOSE] code=${ev.code} reason=${ev.reason||'—'}`); cleanup(); });
    ws.addEventListener('error', (err) => { Log.error(`[ERROR] ${err?.message||err}`); });
  }

  function handleFrame(frame){
    if (frame.dimensions){ dimW = frame.dimensions.w||dimW; dimH = frame.dimensions.h||dimH; }
    const sig = frame.layers?.Sigil?.[0]; if (sig) sigilEl && (sigilEl.textContent = `Sigil: ${sig}`);

    const delta = frame.layers?.MatrixDelta || {};
    for (const k in delta){ grid.set(k, delta[k]); }
    for (const k in delta){ const [x,y] = k.split(',').map(Number); drawCell(x,y, delta[k]); }

    if (frame.meta?.phase && statusEl){
      statusEl.textContent = statusEl.textContent.replace(/\s+\|.*$/,'') + ` | Phase: ${frame.meta.phase}`;
    }
    framesThisSecond++;
  }

  function disconnect(){ if (ws){ try{ ws.close(1000,'client going away'); }catch{} } }
  function cleanup(){ connected = false; setButtons(false); stopHeartbeat(); stopFpsMeter(); updateHUD(); }
  function setButtons(isConnected){
    if (connectBtn) connectBtn.disabled = isConnected;
    if (disconnectBtn) disconnectBtn.disabled = !isConnected;
    if (transformBtn) transformBtn.disabled = !isConnected;
    if (overlay) overlay.classList.toggle('hidden', isConnected);
  }

  // Init
  attachEvents();
  resizeCanvasToView();
  updateHUD();
  Log.info(`Log level = ${Names[logLevel]} (Ctrl+D to change, Ctrl+L to toggle, Ctrl+S to save)`);
})();
