# HoloNet v2.3 - Weaver Terminal (minimal working package)

You provided:
- hostname: `holonet.local`
- local IP fallback: `172.20.10.3/28` on 	`eth0`

This package contains a minimal but working server and client with:
- WebSocket server (port 8765) accepting `/holonet?proto=1.2`
- Client HTML + JS that will attempt `ws://holonet.local:8765/...` then fallback to `ws://172.20.10.3:8765/...`
- Optional HTTP status endpoint on port 8080 (requires `aiohttp`)

## Quick start (Kali / Debian / Ubuntu)

1. Extract and enter folder:
```bash
unzip holonet_v2.3.zip
cd holonet_v2.3
```

2. Create a venv and install deps:
```bash
python3 -m venv venv
. venv/bin/activate
python3 -m pip install --upgrade pip
pip install websockets zeroconf aiohttp
```
(zeroconf is optional but recommended for `holonet.local` advertisement)

3. Start the server:
```bash
python3 server.py
```

4. Open the client:
- Serve the `index.html` (simple way):
```bash
python3 -m http.server 8000
# open http://localhost:8000 in a browser on the machine (or use another machine and open http://172.20.10.3:8000)
```

5. Click **Connect** on the Weaver Terminal page. The client will attempt `holonet.local` then fallback to your provided IP.

## Notes & hardening
- If your host has multiple NICs, ensure mDNS advertises on the correct interface. Avahi may be used instead of zeroconf (system package).
- Firewall: allow ports 8765 (ws) and 8080 (http status) and 8000 (static if using python http.server).
- For production, replace simple echo logic with the full HoloFrame handling and safe parsing. Validate all incoming JSON and add authentication (ABT / archetype-bound token).

## Extras I can add on request
- Avahi systemd unit file and example `avahi.service`
- systemd unit for server.py
- JWT/ABT auth stub + example policy
- Packaging as a .deb for easy deployment

