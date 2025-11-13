"""
AURA-X Market Live Feed
SmartAPI WebSocket for Real-time Option Greeks, OI, IV, LTP feed.
Auto-reconnect, auto-resubscribe, Firebase cache sync.
"""

import json
import os
import threading
from datetime import datetime
from dotenv import load_dotenv
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config.firebase_config import get_db

load_dotenv()
db = get_db()

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")

# 🔹 Live Feed Cache
live_data = {}
JWT = None


def _get_token():
    """Fetch latest AngelOne token from Firebase"""
    global JWT
    token_data = db.child("broker_tokens").child(CLIENT_ID).get()
    if token_data:
        JWT = token_data.get("access_token")
        print("🔑 Angel Token fetched.")
    else:
        print("❌ No valid Angel token in Firebase.")
    return JWT


def init_ws():
    """Initialize & maintain SmartAPI WebSocket connection"""
    jwt = _get_token()
    if not jwt:
        return

    # ✅ Create Smart WebSocket instance
    sws = SmartWebSocketV2(API_KEY, CLIENT_ID, jwt)

    def on_open(wsapp):
        print("✅ [AURA-X FEED] WebSocket connected — subscribing…")
        # Subscribe to major contracts
        tokens = ["26009", "26037"]  # NIFTY, BANKNIFTY
        wsapp.subscribe(correlation_id="aura_sub", mode=1, token_list=tokens)

    def on_data(wsapp, message):
        """Handle incoming live ticks"""
        try:
            data = json.loads(message)
            symbol = data.get("symbolname", "UNKNOWN")
            token = str(data.get("token", ""))
            ltp = data.get("ltp", 0)
            oi = data.get("oi", 0)
            iv = data.get("iv", 0)
            delta = data.get("delta", 0)
            gamma = data.get("gamma", 0)
            theta = data.get("theta", 0)
            vega = data.get("vega", 0)
            ts = data.get("timestamp", datetime.now().isoformat())

            live_data[symbol] = {
                "token": token,
                "ltp": ltp,
                "oi": oi,
                "iv": iv,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "timestamp": ts
            }

            # Optional: push snapshot to Firebase every 5 sec
            if symbol and int(datetime.now().second) % 5 == 0:
                db.child("market_snapshots").child(symbol).set(live_data[symbol])

            print(f"📡 {symbol}: LTP={ltp} | IV={iv} | Δ={delta} | OI={oi}")

        except Exception as e:
            print("⚠️ Data parse error:", e)

    def on_error(wsapp, error):
        print("⚠️ WebSocket Error:", error)

    def on_close(wsapp):
        print("🔴 WS closed. Attempting reconnect in 5s...")
        threading.Timer(5, init_ws).start()

    # Register events
    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    sws.connect()


def get_live_snapshot(symbol):
    """Return last known snapshot for any symbol"""
    sym = symbol.upper()
    if sym in live_data:
        return live_data[sym]
    # fallback from Firebase cache if memory empty
    snap = db.child("market_snapshots").child(sym).get()
    return snap if snap else {
        "ltp": 0, "oi": 0, "iv": 0, "delta": 0,
        "gamma": 0, "theta": 0, "vega": 0
    }


if __name__ == "__main__":
    print("🚀 Starting AURA-X Market Live Feed...")
    init_ws()
