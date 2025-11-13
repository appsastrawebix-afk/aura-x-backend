from flask import Blueprint, jsonify, request
from services.strategy_core import StrategyCore
from services.telegram_notifier import TelegramNotifier
from config.firebase_config import get_db
import time, requests

signal_bp = Blueprint("signal", __name__)
strategy = StrategyCore()
notifier = TelegramNotifier()
db = get_db()


# ============================================================
# 🔹 Generate & Store Trading Signal
# ============================================================
@signal_bp.route("/generate", methods=["POST"])
def generate_signal():
    data = request.get_json(force=True)
    symbol = data.get("symbol", "NIFTY")

    # 🔹 Generate new trading signal (from your strategy core)
    signal = strategy.generate_signal(symbol)
    signal["timestamp"] = int(time.time())

    # 🔹 Save in Firebase (under /signals)
    try:
        db.child("signals").push(signal)
    except Exception as e:
        print("⚠️ Firebase Save Error:", e)

    # 🔹 Telegram Alert
    try:
        msg = (
            f"📊 *AURA-X Signal Alert*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Symbol: {signal['symbol']}\n"
            f"Action: *{signal['action']}*\n"
            f"Price: ₹{signal['price']}\n"
            f"Reason: {signal['reason']}\n"
            f"Time: {time.strftime('%H:%M:%S')}"
        )
        notifier.send_message(msg)
    except Exception as e:
        print("⚠️ Telegram Error:", e)

    # 🔹 Auto-trade trigger (optional)
    if signal["action"] in ["BUY", "SELL"]:
        try:
            trade_url = "http://127.0.0.1:5000/api/trade/place"
            payload = {
                "uid": "manual-auto",
                "symbol": signal["symbol"],
                "transaction_type": signal["action"],
                "quantity": 1,
                "price": signal["price"]
            }
            requests.post(trade_url, json=payload)
            print(f"💰 Auto-Trade Triggered → {signal['action']} {signal['symbol']}")
        except Exception as e:
            print("⚠️ Auto-Trade Error:", e)

    return jsonify({"signal": signal}), 200


# ============================================================
# 🔹 Get Latest Signal for Frontend (AI Insights)
# ============================================================
@signal_bp.route("/latest", methods=["GET"])
def latest_signal():
    """Frontend dashboard साठी — latest AI signal"""
    try:
        signals = db.child("signals").get()
        if not signals:
            return jsonify({"message": "No signals yet"}), 404

        # sort by timestamp descending
        latest = None
        if isinstance(signals, dict):
            latest = sorted(signals.values(), key=lambda x: x.get("timestamp", 0), reverse=True)[0]

        return jsonify({"signal": latest}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🔹 Get Signal History (last 10)
# ============================================================
@signal_bp.route("/history", methods=["GET"])
def signal_history():
    try:
        signals = db.child("signals").get()
        if not signals:
            return jsonify([]), 200

        sorted_signals = sorted(
            signals.values(),
            key=lambda x: x.get("timestamp", 0),
            reverse=True
        )[:10]

        return jsonify({"signals": sorted_signals}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
