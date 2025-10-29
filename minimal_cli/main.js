// main.js - HoloNet v2.3 client (minimal)
const LOG = document.getElementById('log');
const STAT = document.getElementById('stat');
const connectBtn = document.getElementById('connect');
const sendBtn = document.getElementById('send');

function log(...args){
  LOG.textContent += args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ') + '\n';
  LOG.scrollTop = LOG.scrollHeight;
}

// hostname and fallback based on provided LAN info
const HOSTNAME = "holonet.local";
const FALLBACK_IP = "172.20.10.3"; // user-provided
const WS_PORT = 8765;
const PATH = "/holonet?proto=1.2";

let ws = null;
let tickHz = 20;
let tickInterval = null;

function makeUrls(){
  const urls = [
    `ws://${HOSTNAME}:${WS_PORT}${PATH}`,
    `ws://${FALLBACK_IP}:${WS_PORT}${PATH}`,
    `ws://localhost:${WS_PORT}${PATH}`
  ];
  return urls;
}

async function tryConnect(){
  const urls = makeUrls();
  log("Trying endpoints:", urls.join(', '));
  for(const url of urls){
    try {
      log("attempt", url);
      const p = await connectOnce(url);
      if(p) return true;
    } catch(e){
      log("connect failed", url, e);
    }
  }
  return false;
}

function connectOnce(url){
  return new Promise((resolve, reject) => {
    try {
      const s = new WebSocket(url);
      s.onopen = () => {
        ws = s;
        STAT.textContent = "connected -> " + url;
        log("CONNECTED to", url);
        startTick();
        resolve(true);
      };
      s.onmessage = (ev) => {
        let data = ev.data;
        try { data = JSON.parse(ev.data); } catch(e){}
        log("RECV:", data);
      };
      s.onclose = () => {
        log("ws closed");
        STAT.textContent = "disconnected";
        stopTick();
        ws = null;
      };
      s.onerror = (e) => {
        log("ws error", e);
      };
      // timeout fallback
      setTimeout(()=> {
        if(ws === null) reject(new Error("timeout"));
      }, 4000);
    } catch(e){
      reject(e);
    }
  });
}

function startTick(){
  if(tickInterval) clearInterval(tickInterval);
  tickInterval = setInterval(()=> {
    if(!ws || ws.readyState !== WebSocket.OPEN) return;
    const frame = { op: "heartbeat", ts: Date.now(), phiRate:0.62 };
    ws.send(JSON.stringify(frame));
  }, 1000 / tickHz);
}

function stopTick(){
  if(tickInterval) clearInterval(tickInterval);
  tickInterval = null;
}

connectBtn.onclick = async () => {
  connectBtn.disabled = true;
  const ok = await tryConnect();
  if(!ok){
    log("all endpoints failed - check server, firewall, or use direct IP");
    connectBtn.disabled = false;
  } else {
    connectBtn.disabled = false;
  }
};

sendBtn.onclick = () => {
  if(!ws) { log("Not connected"); return; }
  ws.send(JSON.stringify({op:"status"}));
}
