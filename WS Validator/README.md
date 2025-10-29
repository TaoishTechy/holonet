## 1) Validate the embedded vectors (no server needed)

python3 holonet_ws_validator.py

## 2) Validate local files

python3 holonet_ws_validator.py --file tv1.json --file tv3.json

## 3) Connect to your server, receive and validate 5 packets

python3 holonet_ws_validator.py --endpoint ws://localhost:8765/holonet --recv 5

## 4) Send TV-1 and TV-3 to your server and validate any echo

python3 holonet_ws_validator.py --endpoint ws://localhost:8765/holonet --send-tv1 --send-tv3

