import time
import traceback
from config.firebase_config import get_db
from services.notifier import notify_trade, notify_system_alert
from services.angel_api import AngelSmartAPI
from services.risk_manager import RiskManager

db = get_db()
angel = AngelSmartAPI()
rm = RiskManager()


def get_trade_pnl(trade, current_price):
    """Calculate real-time P/L for a trade"""
    direction = trade.get("type")
    entry_price = float(trade.get("entry_price", 0))
    qty = int(trade.get("quantity", 1))
    if direction == "BUY":
        pnl = (current_price - entry_price) * qty
    else:
        pnl = (entry_price - current_price) * qty
    return round(pnl, 2)


def check_active_trades():
    """Firebase मधील active trades तपासते आणि auto-exit करते."""
    trades_ref = db.child("trades").get()
    if not trades_ref:
        print("⚠️ No active trades in Firebase.")
        return

    for uid, trades in trades_ref.items():
        if not isinstance(trades, dict):
            continue

        for key, trade in trades.items():
            status = trade.get("status")
            if status not in ["SUCCESS", "TRAILING"]:
                continue  # फक्त active trades

            symbol = trade.get("symbol")
            direction = trade.get("type")
            entry_price = float(trade.get("entry_price", 0))
            stoploss = float(trade.get("stoploss", 0))
            target = float(trade.get("target", 0))
            qty = int(trade.get("quantity", 1))
            trade_id = trade.get("trade_id")

            try:
                # 🔹 Get live price
                ltp = angel.get_ltp(symbol)
                if not ltp:
                    continue
                current_price = float(ltp)
            except Exception as e:
                print(f"⚠️ LTP fetch error for {symbol}:", e)
                continue

            pnl = get_trade_pnl(trade, current_price)
            print(f"💹 {symbol} → {current_price} | P/L ₹{pnl}")

            # 🧮 Exit condition check
            hit_type = None
            if direction == "BUY":
                if current_price <= stoploss:
                    hit_type = "STOPLOSS"
                elif current_price >= target:
                    hit_type = "TARGET"
            elif direction == "SELL":
                if current_price >= stoploss:
                    hit_type = "STOPLOSS"
                elif current_price <= target:
                    hit_type = "TARGET"

            # ⚙️ Trailing Stop Logic (optional)
            if direction == "BUY" and current_price > entry_price + (entry_price * 0.002):  # +0.2%
                new_sl = max(stoploss, current_price - (0.003 * current_price))
                if new_sl > stoploss:
                    db.child("trades").child(uid).child(key).update({"stoploss": new_sl, "status": "TRAILING"})
                    print(f"🔁 Trailing SL updated for {symbol}: ₹{round(new_sl,2)}")
            elif direction == "SELL" and current_price < entry_price - (entry_price * 0.002):
                new_sl = min(stoploss, current_price + (0.003 * current_price))
                if new_sl < stoploss:
                    db.child("trades").child(uid).child(key).update({"stoploss": new_sl, "status": "TRAILING"})
                    print(f"🔁 Trailing SL updated for {symbol}: ₹{round(new_sl,2)}")

            # ✅ Exit condition hit
            if hit_type:
                print(f"💥 {hit_type} HIT for {symbol} @ {current_price}")
                db.child("trades").child(uid).child(key).update({
                    "status": hit_type,
                    "exit_price": current_price,
                    "exit_time": int(time.time()),
                    "pnl": pnl
                })

                notify_trade(
                    symbol,
                    f"{direction} EXIT ({hit_type})",
                    current_price,
                    target,
                    stoploss,
                    100,
                    trade_id
                )
                rm.record_exit(uid, pnl)

                # 🧠 Auto Token Refresh safeguard
                if "Invalid Session" in str(pnl):
                    angel.get_access_token()


def run_trade_watcher(interval=30):
    """प्रत्येक 30 सेकंदांनी चालणारा watcher loop."""
    print("👁️‍🗨️ AURA-X TradeWatcher started — auto-exit monitor active.")
    while True:
        try:
            check_active_trades()
        except Exception as e:
            err_trace = traceback.format_exc()
            print("❌ TradeWatcher Error:", e)
            notify_system_alert("CRITICAL", "TradeWatcher Crash", str(err_trace))
        time.sleep(interval)
