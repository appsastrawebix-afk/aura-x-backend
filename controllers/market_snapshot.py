"""
services/market_snapshot.py
AURA-X — Market Snapshot Aggregator
Live + Cached market context for signal verification
"""

import time
import json
import math
import os
import requests
from statistics import mean
from dotenv import load_dotenv
from services.angel_api import AngelSmartAPI

load_dotenv()

# 🔑 Angel credentials
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")

# Firebase / cache can also be used later for efficiency
angel = AngelSmartAPI()


# ===================== Utility =====================

def safe_get(url, headers=None):
    """Handle errors gracefully and return JSON"""
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"⚠️ Angel GET error {res.status_code}: {url}")
    except Exception as e:
        print("⚠️ Network error:", e)
    return {}


def ema(values, period):
    """Calculate simple EMA manually (for offline fallback)"""
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    ema_val = values[0]
    for price in values[1:]:
        ema_val = price * k + ema_val * (1 - k)
    return round(ema_val, 2)


# ===================== Main Snapshot =====================

def get_realtime_snapshot(symbol: str):
    """
    Fetches the latest NIFTY / BANKNIFTY + Option (CE/PE) data.
    Returns dict formatted for verify_signal().
    """

    try:
        # ---- Step 1: Base Setup ----
        symbol = symbol.upper()
        is_ce = "CE" in symbol
        base_index = "NIFTY" if symbol.startswith("NIFTY") else "BANKNIFTY"

        # ---- Step 2: Fetch index LTPs (3-min candles) ----
        index_url = f"https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        headers = {"X-PrivateKey": API_KEY, "Content-Type": "application/json"}
        # you can fetch candles via Angel SmartAPI, but fallback demo here
        index_prices = get_last_candles(base_index)
        ema20 = ema(index_prices, 20)
        ema50 = ema(index_prices, 50)

        trend = "BULL" if ema20 > ema50 else "BEAR"
        ha_colors = get_ha_colors(index_prices)

        # ---- Step 3: Option Chain (for IV, OI, Greeks) ----
        oc_data = get_option_chain_data(base_index)

        # parse atm CE/PE values (simplified)
        atm_data = oc_data.get("atm_ce" if is_ce else "atm_pe", {})
        iv = atm_data.get("iv", 18.5)
        iv_delta = atm_data.get("iv_delta_30m_pct", 4.2)
        delta = atm_data.get("delta", 0.42 if is_ce else -0.45)
        gamma = atm_data.get("gamma", 0.06)
        theta = atm_data.get("theta", -4.5)

        # ---- Step 4: Volume / Momentum ----
        vol = atm_data.get("volume", 12000)
        avg5 = atm_data.get("avg_5", 8000)
        tick_delta = atm_data.get("ltp_change_pct", 3.0)

        # ---- Step 5: OI delta ----
        oi_build = oc_data.get("atm_plus_minus_4_net_oi_delta_15m", 2500)
        oi_avg = oc_data.get("oi_1h_avg", 70000)

        # ---- Step 6: Combine ----
        snapshot = {
            "index": {
                "ema20": ema20,
                "ema50": ema50,
                "trend": trend,
                "ha_last3": ha_colors
            },
            "option": {
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "iv": iv,
                "iv_delta_30m_pct": iv_delta
            },
            "oi": {
                "atm_plus_minus_4_net_oi_delta_15m": oi_build,
                "oi_1h_avg": oi_avg
            },
            "volume": {
                "candle_vol": vol,
                "avg_5": avg5
            },
            "ltp_ticks": {
                "last_3_delta_pct": tick_delta
            }
        }

        return snapshot

    except Exception as e:
        print("⚠️ Snapshot Error:", e)
        return {
            "index": {"ema20": 0, "ema50": 0, "ha_last3": []},
            "option": {"delta": 0, "gamma": 0, "theta": 0, "iv": 0, "iv_delta_30m_pct": 0},
            "oi": {"atm_plus_minus_4_net_oi_delta_15m": 0, "oi_1h_avg": 0},
            "volume": {"candle_vol": 0, "avg_5": 0},
            "ltp_ticks": {"last_3_delta_pct": 0}
        }


# ===================== Helper Mock Functions =====================

def get_last_candles(index_symbol):
    """
    Mock / or replace with real Angel candle API
    Return last 50 close prices for EMA calc
    """
    try:
        # live candle endpoint (replace this URL with Angel candle API)
        url = f"https://margincalculator.angelbroking.com/OpenAPI_File/files/{index_symbol}last50.json"
        return [22500 + i * 2 for i in range(50)]  # simulated
    except Exception:
        return [22500 + i for i in range(50)]


def get_ha_colors(candles):
    """
    Simulated Heikin-Ashi color generation
    Returns ['green', 'green', 'red'] based on trend
    """
    colors = []
    for i in range(len(candles) - 3, len(candles)):
        colors.append("green" if candles[i] > candles[i - 1] else "red")
    return colors[-3:]


def get_option_chain_data(index_symbol):
    """
    Mock function — replace with live Angel option chain / Greeks feed
    Should return dictionary with ATM, IV, delta, gamma, theta, OI etc.
    """
    # In real setup, fetch from SmartAPI WebSocket or NSE API
    return {
        "atm_ce": {
            "iv": 18.5,
            "iv_delta_30m_pct": 3.8,
            "delta": 0.45,
            "gamma": 0.06,
            "theta": -4.0,
            "volume": 12000,
            "avg_5": 8000,
            "ltp_change_pct": 3.5
        },
        "atm_pe": {
            "iv": 20.2,
            "iv_delta_30m_pct": 4.5,
            "delta": -0.48,
            "gamma": 0.05,
            "theta": -4.2,
            "volume": 13000,
            "avg_5": 8500,
            "ltp_change_pct": -3.0
        },
        "atm_plus_minus_4_net_oi_delta_15m": 2600,
        "oi_1h_avg": 78000
    }
