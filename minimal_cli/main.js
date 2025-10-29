/* main.js — HoloNet v2.4 client (patched to work with server.py v2.3-patched-v2)
   - Keeps existing UI/IDs from index.html & styles.css
   - Stable WS protocol: hello/pong/frame
   - Heartbeat 4 Hz with phiRate (v slider) & latency calculation
   - Graceful connect/disconnect & Close handshake
   - MatrixDelta rendering onto <canvas id="frameCanvas">
   - Throttled rendering and simple FPS meter
*/

(() => {
  // ---------- DOM ----------
  const el = (id) => document.getElementById(id);
  const statusEl = el('status');
  const sigilEl = el('sigilDisplay');
  const logEl = el('log');
  const canvas = el('frameCanvas');
  const overlay = el('canvasOverlay');
  const ctx = canvas.getContext('2d');

  const connectBtn = el('connectBtn');
  const disconnectBtn = el('disconnectBtn');
  const transformBtn = el('transformBtn');

  const vSlider = el('velocity');
  const zSlider = el('horizon');
  const wSlider = el('width');
  const hSlider = el('height');

  const vValue = el('vValue');
  const zValue = el('zValue');
  const wValue = el('wValue');
  const hValue = el('hValue');

  // ---------- State ----------
  let ws = null;
  let seq = 0;
  let connected = false;
  let heartbeatTimer = null;
  let fpsTimer = null;
  let lastFrameTs = 0;
  let framesThisSecond = 0;
  let fps = 0;
  let latencyMs = 0;

  // world grid backing store (sparse)
  let dimW = 64, dimH = 32;
  const grid = new Map(); // key "x,y" -> value 0..9

  // ---------- Utils ----------
  const now = () => Date.now();
  const log = (msg, isErr = false) => {
    const line = document.createElement('div');
    if (isErr) line.classList.add('error');
    line.textContent = msg;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
  };

  const setStatus = (text) => {
    statusEl.textContent = text;
  };

  const updateHUD = () => {
    const sess = ws ? (ws._sessionId || '—') : 'None';
    setStatus(`Status: [${connected ? 'Connected' : 'Disconnected'}] | Session: ${sess} | Latency: ${latencyMs.toFixed(1)}ms | FPS: ${fps}`);
  };

  const setButtons = (isConnected) => {
    connectBtn.disabled = isConnected;
    disconnectBtn.disabled = !isConnected;
    transformBtn.disabled = !isConnected;
    overlay.classList.toggle('hidden', isConnected);
  };

  // color palette for 0..9 (retro phosphor intensity)
  const shades = [
    '#001800', '#003100', '#004a00', '#006300', '#007c00',
    '#009500', '#00ae00', '#00c700', '#00e000', '#00ff00'
  ];

  function drawCell(x, y, v) {
    const cellW = Math.floor(canvas.width / dimW);
    const cellH = Math.floor(canvas.height / dimH);
    const val = (v|0);
    const idx = Math.max(0, Math.min(9, val));
    ctx.fillStyle = shades[idx];
    ctx.fillRect(x * cellW, y * cellH, cellW, cellH);
  }

  function redrawAll() {
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (const [k, v] of grid) {
      const [x, y] = k.split(',').map(Number);
      drawCell(x, y, v);
    }
  }

  function resizeCanvasToView() {
    // Keep aspect but fill container area (CSS confines it)
    const w = Math.max(16, parseInt(wSlider.value, 10));
    const h = Math.max(8, parseInt(hSlider.value, 10));
    // Multipliers for crisp pixel rendering
    const mul = 8;
    canvas.width = w * mul;
    canvas.height = h * mul;
    redrawAll();
  }

  // ---------- WS logic ----------
  function wsUrl() {
    const host = window.location.hostname || 'localhost';
    const port = 8765;
    return `ws://${host}:${port}/holonet?proto=1.2`;
  }

  function send(obj) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(obj));
  }

  function startHeartbeat() {
    stopHeartbeat();
    const tickHz = 4; // sane default
    heartbeatTimer = setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const frame = {
        op: 'heartbeat',
        ts: now(),
        phiRate: parseFloat(vSlider.value || '0.5')
      };
      send(frame);
    }, 1000 / tickHz);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function startFpsMeter() {
    stopFpsMeter();
    fpsTimer = setInterval(() => {
      fps = framesThisSecond;
      framesThisSecond = 0;
      updateHUD();
    }, 1000);
  }

  function stopFpsMeter() {
    if (fpsTimer) {
      clearInterval(fpsTimer);
      fpsTimer = null;
    }
  }

  function attachEvents() {
    connectBtn.addEventListener('click', connect);
    disconnectBtn.addEventListener('click', disconnect);
    transformBtn.addEventListener('click', () => {
      send({ op: 'transform', z: parseInt(zSlider.value, 10) });
      log('[TX] transform requested (symbolic relativity)');
    });

    const onSlider = () => {
      vValue.textContent = parseFloat(vSlider.value).toFixed(2);
      zValue.textContent = zSlider.value;
      wValue.textContent = wSlider.value;
      hValue.textContent = hSlider.value;
      resizeCanvasToView();
      // Send view update (server may ignore; harmless)
      send({
        op: 'view',
        view: { w: parseInt(wSlider.value, 10), h: parseInt(hSlider.value, 10), z: parseInt(zSlider.value, 10) }
      });
    };
    vSlider.addEventListener('input', onSlider);
    zSlider.addEventListener('input', onSlider);
    wSlider.addEventListener('input', onSlider);
    hSlider.addEventListener('input', onSlider);
    onSlider(); // initial
  }

  function connect() {
    if (connected) return;
    ws = new WebSocket(wsUrl());

    ws.addEventListener('open', () => {
      connected = true;
      setButtons(true);
      log(`[OPEN] Connecting to ${wsUrl()}`);
      updateHUD();
      startHeartbeat();
      startFpsMeter();
    });

    ws.addEventListener('message', (ev) => {
      let data = ev.data;
      try { data = JSON.parse(ev.data); } catch (e) { /* text log */ }

      if (typeof data === 'string') {
        log(`[RECV text] ${data}`);
        return;
      }

      const op = data.op;
      switch (op) {
        case 'hello': {
          // optional session id (client-side only)
          ws._sessionId = (Math.random().toString(16).slice(2, 10));
          log(`[HELLO] server=${data.server} proto=${data.proto} frames=${data.frames_version}`);
          break;
        }
        case 'pong': {
          if (typeof data.ts === 'number') {
            latencyMs = now() - data.ts;
            updateHUD();
          }
          break;
        }
        case 'frame': {
          handleFrame(data);
          break;
        }
        default:
          log(`[RECV] ${JSON.stringify(data)}`);
      }
    });

    ws.addEventListener('close', (ev) => {
      log(`[CLOSE] code=${ev.code} reason=${ev.reason || '—'}`);
      cleanup();
    });

    ws.addEventListener('error', (err) => {
      log(`[ERROR] ${err?.message || err}`, true);
    });
  }

  function handleFrame(frame) {
    // Keep dimensions synced (server sends real dims)
    if (frame.dimensions) {
      dimW = frame.dimensions.w || dimW;
      dimH = frame.dimensions.h || dimH;
    }

    // Update Sigil
    const sig = frame.layers?.Sigil?.[0];
    if (sig) {
      sigilEl.textContent = `Sigil: ${sig}`;
    }

    // Apply MatrixDelta
    const delta = frame.layers?.MatrixDelta || {};
    for (const k in delta) {
      grid.set(k, delta[k]);
    }
    // Draw only changed cells (fast path)
    for (const k in delta) {
      const [x, y] = k.split(',').map(Number);
      drawCell(x, y, delta[k]);
    }

    // FPS accounting
    framesThisSecond++;
    lastFrameTs = now();

    // Optional: show phase from meta
    if (frame.meta && frame.meta.phase) {
      // lightweight visual cue in status line (phase)
      statusEl.textContent = statusEl.textContent.replace(/\s+\|.*$/,'') + ` | Phase: ${frame.meta.phase}`;
    }
  }

  function disconnect() {
    if (!ws) return;
    try {
      // polite close with 1000
      ws.close(1000, 'client going away');
    } catch {}
  }

  function cleanup() {
    connected = false;
    setButtons(false);
    stopHeartbeat();
    stopFpsMeter();
    updateHUD();
  }

  // Init
  attachEvents();
  resizeCanvasToView();
  updateHUD();
})();
