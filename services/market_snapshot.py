"""
AURA-X — Market Snapshot (Realtime Data Fetch)
Simplified snapshot fetcher that returns live data structure
used by signal_verifier and trade_controller.
"""

import requests
import os
import time
from dotenv import load_dotenv
from config.firebase_config import get_db

load_dotenv()
db = get_db()

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")

# ✅ get_live_snapshot(): fetch LTP + Greeks + OI + IV from Firebase or mock
def get_live_snapshot(symbol: str):
    """
    Returns a fake but structured snapshot for development/demo mode.
    Replace this later with websocket/real API data.
    """
    symbol = symbol.upper()

    # 🔹 Mock index data
    index_snapshot = {
        "price": 22500 if "NIFTY" in symbol else 48500,
        "ema20": 22510 if "NIFTY" in symbol else 48620,
        "ema50": 22450 if "NIFTY" in symbol else 48400,
        "ha_last3": ["green", "green", "green"],
    }

    # 🔹 Mock option Greeks / OI / IV
    option_snapshot = {
        "ltp": 120 + (5 if "CE" in symbol else 8),
        "oi": 85000,
        "iv": 17.5,
        "iv_delta_30m_pct": 4.5,
        "delta": 0.45 if "CE" in symbol else -0.48,
        "gamma": 0.06,
        "theta": -3.5,
        "vega": 0.15,
    }

    # 🔹 Mock volume + tick data
    volume_snapshot = {
        "candle_vol": 14000,
        "avg_5": 9000
    }
    ltp_ticks = {
        "last_3_delta_pct": 3.2
    }

    # ✅ Combine
    return {
        "index": index_snapshot,
        "option": option_snapshot,
        "oi": {"atm_plus_minus_4_net_oi_delta_15m": 2300, "oi_1h_avg": 75000},
        "volume": volume_snapshot,
        "ltp_ticks": ltp_ticks,
        "timestamp": int(time.time())
    }


# ✅ get_realtime_snapshot(): alias used by trade_controller
def get_realtime_snapshot(symbol: str):
    """
    Alias to get_live_snapshot() — used by trade_controller.py
    """
    return get_live_snapshot(symbol)
