# services/atm_executor.py
"""
AURA-X — ATM Executor Service
- Watches main index (NIFTY/BANKNIFTY)
- Finds ATM option based on current index price & capital
- Verifies signal with signal_verifier
- Executes demo or live trade via AngelSmartAPI (or posts to /api/trade/place)
- Logs to Firebase and sends Telegram notifications
"""

import os
import time
import math
import threading
import traceback
import datetime
from typing import Optional, Dict, Any

from config.firebase_config import get_db, init_firebase
from services.risk_manager import RiskManager
from services.angel_api import AngelSmartAPI
from services import signal_verifier
from services import market_snapshot

# notifier
try:
    from services.notifier import notify_trade, notify_system_alert
except Exception:
    def notify_trade(*a, **k): print("notify_trade:", a, k)
    def notify_system_alert(*a, **k): print("notify_system_alert:", a, k)

# mode controller
try:
    from controllers.mode_controller import get_mode
except Exception:
    def get_mode(): return os.getenv("AURA_MODE", "demo")

# snapshot loader
get_snapshot = getattr(market_snapshot, "get_realtime_snapshot", None) or \
               getattr(market_snapshot, "get_live_snapshot", None) or \
               (lambda symbol: {})

# init services
init_firebase()
db = get_db()
rm = RiskManager()
angel_api = AngelSmartAPI()

# config
CFG = {
    "index_symbols": ["NIFTY", "BANKNIFTY"],
    "poll_interval_sec": 15,
    "atm_distance_strikes": 0,
    "strike_round": 100,
    "min_verify_score": 0.75,
    "manual_score_threshold": 0.65,
    "max_open_trades_per_uid": 3,
    "min_capital_for_trade": 10000,
    "cooldown_after_exec_sec": 8,
    "max_spread_allowed": 5.0,
    "allow_only_buy_options": True,
    "use_angel_place_endpoint": False,
    "internal_trade_api": "http://127.0.0.1:5000/api/trade/place",
}

_last_executed_at = {}


def _on_cooldown(app_symbol: str) -> bool:
    last = _last_executed_at.get(app_symbol)
    return bool(last and (time.time() - last) < CFG["cooldown_after_exec_sec"])


def _set_cooldown(app_symbol: str):
    _last_executed_at[app_symbol] = time.time()

# ---------------- SEBI-Aware Expiry Helpers ---------------- #

def get_weekday_for_index(index_name: str) -> int:
    name = index_name.upper()
    if "BANK" in name:
        return 2  # Wednesday
    if "FIN" in name:
        return 1  # Tuesday
    return 3  # Thursday (NIFTY default)

def get_next_weekly_expiry(index_name: str, from_date: Optional[datetime.date] = None) -> datetime.date:
    if from_date is None:
        from_date = datetime.date.today()
    target_wd = get_weekday_for_index(index_name)
    days_ahead = (target_wd - from_date.weekday()) % 7
    return from_date + datetime.timedelta(days=days_ahead)

def build_option_symbol(index_name: str, expiry_date: datetime.date, strike: int, option_type: str) -> str:
    year_two = expiry_date.strftime("%y")
    month_str = expiry_date.strftime("%b").upper()
    day_str = expiry_date.strftime("%d")
    base = index_name.upper()
    return f"{base}{year_two}{month_str}{day_str}{strike}{option_type}"

def round_strike(index_price: float, strike_step: int = 50) -> int:
    if strike_step <= 0:
        return int(round(index_price))
    return int(round(index_price / strike_step) * strike_step)

def find_atm_option(index_price: float, index_name: str = "NIFTY", option_type: str = "CE",
                    strike_step: Optional[int] = None, offset: int = 0, prefer_weekly: bool = True) -> str:
    name = index_name.upper()
    if strike_step is None:
        strike_step = 100 if "BANK" in name else 50

    strike = round_strike(index_price, strike_step) + (offset * strike_step)
    today = datetime.date.today()

    if prefer_weekly:
        expiry = get_next_weekly_expiry(name, today)
    else:
        target_wd = get_weekday_for_index(name)
        year, month = today.year, today.month
        next_month = month % 12 + 1
        next_month_year = year + (1 if next_month == 1 else 0)
        last_day = datetime.date(next_month_year, next_month, 1) - datetime.timedelta(days=1)
        days_back = (last_day.weekday() - target_wd) % 7
        expiry = last_day - datetime.timedelta(days=days_back)

    return build_option_symbol(name, expiry, strike, option_type.upper())

# ------------------------------------------------------------ #

def determine_qty_by_capital(capital: float, entry_price: float, stoploss: float) -> int:
    try:
        return max(0, int(rm.calculate_quantity(capital, entry_price, stoploss)))
    except Exception:
        risk_amt = capital * 0.01
        per_unit_risk = abs(entry_price - stoploss)
        return int(risk_amt // per_unit_risk) if per_unit_risk > 0 else 0


def lookup_contract_info(app_symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import json
        path = os.path.join(os.getcwd(), "data", "angel_contracts.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                arr = json.load(f)
            for c in arr:
                if c.get("symbol", "").upper() == app_symbol.upper():
                    return {"token": c.get("token"), "exchange": c.get("exch_seg")}
        fb = db.child("contracts").child(app_symbol.upper()).get()
        if fb:
            return {"token": fb.get("token"), "exchange": fb.get("exchange")}
    except Exception:
        pass
    return None


def build_trade_payload(app_symbol, exchange, symboltoken, txn_type, entry_price, qty, stoploss, target):
    return {
        "uid": "auto-executor",
        "symbol": app_symbol,
        "transaction_type": txn_type,
        "price": entry_price,
        "quantity": qty,
        "capital": 0,
        "candles": [],
        "stoploss": stoploss,
        "target": target,
        "confidence": 95
    }


def execute_trade(app_symbol, normalized_symbol, exchange, symboltoken,
                  txn_type, entry_price, qty, stoploss, target, confidence=95):
    mode = get_mode().lower()
    uid = "auto-executor"

    trade_log = {
        "symbol": normalized_symbol,
        "exchange": exchange,
        "type": txn_type,
        "quantity": qty,
        "entry_price": entry_price,
        "stoploss": stoploss,
        "target": target,
        "timestamp": int(time.time()),
        "status": "PENDING",
        "meta": {"executor": "atm_executor", "mode": mode}
    }

    try:
        if mode == "demo":
            trade_log["status"] = "SIMULATED"
            trade_log["order_id"] = f"DEMO-{int(time.time())}"
            db.child("trades").child(uid).push(trade_log)
            notify_trade(normalized_symbol, txn_type, entry_price, target, stoploss, confidence, trade_log["order_id"], 0)
            _set_cooldown(app_symbol)
            return {"ok": True, "mode": "demo", "trade_log": trade_log}

        # LIVE mode
        import requests
        payload = build_trade_payload(normalized_symbol, exchange, symboltoken, txn_type, entry_price, qty, stoploss, target)
        if not CFG["use_angel_place_endpoint"]:
            res = requests.post(CFG["internal_trade_api"], json=payload, timeout=10)
            if res and res.status_code == 200:
                _set_cooldown(app_symbol)
                j = res.json()
                notify_trade(normalized_symbol, txn_type, entry_price, target, stoploss, confidence, j.get("trade_log", {}).get("trade_id", "UNKNOWN"), 0)
                return {"ok": True, "mode": "live", "response": j}
            return {"ok": False, "error": "internal api failed", "raw": res.text if res else None}

        if hasattr(angel_api, "place_order"):
            r = angel_api.place_order(
                tradingsymbol=normalized_symbol, exchange=exchange,
                transactiontype=txn_type, symboltoken=symboltoken,
                quantity=qty, price=entry_price, stoploss=stoploss, squareoff=target
            )
            _set_cooldown(app_symbol)
            notify_trade(normalized_symbol, txn_type, entry_price, target, stoploss, confidence, r.get("orderid", "UNKNOWN"), 0)
            return {"ok": True, "mode": "live", "response": r}
        return {"ok": False, "error": "AngelSmartAPI.place_order not implemented"}

    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


def evaluate_and_execute(index_name: str, base_index_price: float, capital_lookup: dict = None):
    try:
        # decide initial symbol
        app_symbol = find_atm_option(base_index_price, index_name=index_name, option_type="CE", prefer_weekly=True)
        snapshot = get_snapshot(index_name) or {}

        idx = snapshot.get("index", {})
        ema20, ema50 = idx.get("ema20"), idx.get("ema50")
        ha3 = idx.get("ha_last3", [])
        trend = "BUY" if ema20 and ema50 and ema20 > ema50 else "SELL" if ema20 and ema50 else \
                ("BUY" if ha3 and ha3[-1].lower() == "green" else "SELL" if ha3 else None)
        if not trend:
            return {"ok": False, "reason": "no_trend_info"}

        opt_type = "CE" if trend == "BUY" else "PE"
        app_symbol = find_atm_option(base_index_price, index_name=index_name, option_type=opt_type, prefer_weekly=True)

        if _on_cooldown(app_symbol):
            return {"ok": False, "reason": "cooldown"}

        option_snapshot = get_snapshot(app_symbol) or {}
        merged_snapshot = {
            "index": snapshot.get("index", {}),
            "option": option_snapshot.get("option", option_snapshot),
            "oi": option_snapshot.get("oi", {}),
            "volume": option_snapshot.get("volume", {}),
            "ltp_ticks": option_snapshot.get("ltp_ticks", {})
        }

        signal = {
            "symbol": app_symbol,
            "type": opt_type,
            "side": "BUY",
            "confidence": 95,
            "time": int(time.time()),
            "index_price": base_index_price,
            "ai_score": 0.9
        }

        verification = signal_verifier.verify_signal(signal, merged_snapshot)
        score, action = verification.get("score", 0), verification.get("action", "SKIP")
        if action != "EXECUTE" and score < CFG["min_verify_score"]:
            return {"ok": False, "action": action, "score": score}

        contract_info = lookup_contract_info(app_symbol)
        if not contract_info:
            return {"ok": False, "reason": "contract_not_found", "symbol": app_symbol}

        exchange, symboltoken = contract_info["exchange"], contract_info["token"]
        entry_price = float(option_snapshot.get("ltp") or base_index_price or 0)
        stoploss = round(entry_price * 0.90, 2) if opt_type == "CE" else round(entry_price * 1.10, 2)
        target = round(entry_price * 1.20, 2) if opt_type == "CE" else round(entry_price * 0.80, 2)

        uid = "auto-executor"
        user_node = db.child("users").child(uid).get() or {}
        capital = float(user_node.get("capital", CFG["min_capital_for_trade"]))
        if capital < CFG["min_capital_for_trade"]:
            return {"ok": False, "reason": "low_capital", "capital": capital}

        qty = determine_qty_by_capital(capital, entry_price, stoploss)
        if qty <= 0:
            return {"ok": False, "reason": "qty_zero", "qty": qty}

        spread = float(option_snapshot.get("ask", 0) or 0) - float(option_snapshot.get("bid", 0) or 0)
        if spread and spread > CFG["max_spread_allowed"]:
            return {"ok": False, "reason": "spread_too_high", "spread": spread}

        trades_ref = db.child("trades").child(uid).get() or {}
        open_trades = sum(1 for _, v in (trades_ref.items() if isinstance(trades_ref, dict) else []) if v.get("status") == "SUCCESS")
        if open_trades >= CFG["max_open_trades_per_uid"]:
            return {"ok": False, "reason": "too_many_open_trades", "open_trades": open_trades}

        result = execute_trade(app_symbol, app_symbol, exchange, symboltoken, "BUY", entry_price, qty, stoploss, target, int(score * 100))
        return {"ok": True, "execute_result": result, "verify": verification}

    except Exception as e:
        tb = traceback.format_exc()
        notify_system_alert("ERROR", "ATM Executor Exception", str(e) + "\n" + tb)
        return {"ok": False, "error": str(e), "trace": tb}


def executor_loop(stop_event: threading.Event = None):
    print("🔁 ATM Executor loop started.")
    try:
        while not (stop_event and stop_event.is_set()):
            for idx in CFG["index_symbols"]:
                try:
                    snap = get_snapshot(idx) or {}
                    idx_price = snap.get("index", {}).get("price") or snap.get("ltp") or snap.get("price")
                    if not idx_price:
                        idx_price = db.child("indices").child(idx).get() or None
                        if isinstance(idx_price, dict):
                            idx_price = idx_price.get("price")
                    if not idx_price:
                        continue
                    res = evaluate_and_execute(idx, float(idx_price))
                    if res.get("ok"):
                        print("✅ ATM Executor executed:", res.get("execute_result"))
                except Exception as e:
                    notify_system_alert("ERROR", "ATM Loop Index Eval Error", str(e))
            time.sleep(CFG["poll_interval_sec"])
    except KeyboardInterrupt:
        print("🔴 ATM Executor stopped.")
    except Exception as e:
        notify_system_alert("CRITICAL", "ATM Executor crashed", str(e))
        raise


def start_atm_executor_in_thread():
    stop_event = threading.Event()
    t = threading.Thread(target=executor_loop, args=(stop_event,), daemon=True)
    t.start()
    return stop_event, t


if __name__ == "__main__":
    print("Starting ATM Executor standalone (CTRL+C to stop).")
    stop, t = start_atm_executor_in_thread()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")
