from flask import Blueprint, request, jsonify
from services.angel_api import AngelSmartAPI
from services.notifier import notify_trade, _push_log  # ✅ Added _push_log
from services.risk_manager import RiskManager
from services.signal_verifier import verify_signal
from controllers.mode_controller import get_mode
from config.firebase_config import get_db
import time, os, requests

webhook_bp = Blueprint("webhook", __name__)
angel = AngelSmartAPI()
rm = RiskManager()
db = get_db()

# ======================================================
# 🔹 TradingView Webhook Endpoint
# ======================================================
@webhook_bp.route("/webhook/tradingview", methods=["POST"])
def tradingview_signal():
    """
    Receives TradingView alert JSON:
    {
      "symbol": "NIFTY24NOV22500CE",
      "signal" or "side": "BUY"/"SELL",
      "price": 142.5,
      "confidence": 94,
      "time": "2025-11-12T15:59:00"
    }
    """
    try:
        data = request.get_json(force=True)
        print("📩 TradingView Alert Received:", data)

        symbol = data.get("symbol")
        txn_type = data.get("side", data.get("signal", "BUY")).upper()
        entry_price = float(data.get("price", 0))
        confidence = float(data.get("confidence", 90))
        capital = float(data.get("capital", 100000))
        uid = data.get("uid", "webhook-auto")

        if not symbol or txn_type not in ["BUY", "SELL"]:
            return jsonify({"error": "Invalid symbol or transaction_type"}), 400

        # ✅ Mode Check
        mode = get_mode()
        print(f"💼 Mode: {mode.upper()} | Symbol: {symbol}")

        # ✅ Real-time snapshot mock
        snapshot = {
            "index": {"ema20": 22450, "ema50": 22400, "ha_last3": ["green","green","green"]},
            "option": {"delta": 0.45, "gamma": 0.06, "theta": -4, "iv": 18, "iv_delta_30m_pct": 4},
            "oi": {"atm_plus_minus_4_net_oi_delta_15m": 2500, "oi_1h_avg": 70000},
            "volume": {"candle_vol": 18000, "avg_5": 9000},
            "ltp_ticks": {"last_3_delta_pct": 3.8}
        }

        # ✅ Verify signal (prevent false alerts)
        verify = verify_signal(data, snapshot)
        if verify["action"] == "SKIP":
            print("⚠️ Signal filtered:", verify["reasons"])
            _push_log("SKIP", f"{txn_type} {symbol} filtered — {verify.get('reasons', 'No reasons')}")
            return jsonify({"message": "Filtered out", "verify": verify}), 200

        # ✅ Risk Check
        allowed, pnl, limit = rm.check_daily_loss_limit(uid, capital)
        if not allowed:
            notify_trade(f"🚫 Daily loss limit reached: {pnl}/{limit}")
            _push_log("RISK", f"{symbol} skipped — Risk limit reached ({pnl}/{limit})")
            return jsonify({"error": "Risk limit hit"}), 403

        # ✅ Mode-based behavior
        if mode == "demo":
            db.child("signals").push({
                "symbol": symbol,
                "type": txn_type,
                "price": entry_price,
                "mode": "demo",
                "verified": verify,
                "timestamp": int(time.time())
            })
            notify_trade(f"🧪 DEMO Signal: {txn_type} {symbol} (conf {confidence}%)")
            _push_log("DEMO", f"{txn_type} {symbol} @ {entry_price} | Conf {confidence}%")
            return jsonify({"message": "Demo signal logged"}), 200

        # ✅ LIVE MODE Execution
        payload = {
            "uid": uid,
            "symbol": symbol,
            "transaction_type": txn_type,
            "price": entry_price,
            "quantity": 1,
            "capital": capital
        }

        res = requests.post("http://127.0.0.1:5000/api/trade/place", json=payload)
        print("📤 Trade API Response:", res.text)
        notify_trade(f"✅ LIVE Order Executed: {txn_type} {symbol} @ {entry_price} ({confidence}%)")
        _push_log("TRADE", f"{txn_type} {symbol} @ {entry_price} | Conf {confidence}%")

        # Save in Firebase
        db.child("signals").push({
            "symbol": symbol,
            "type": txn_type,
            "price": entry_price,
            "mode": mode,
            "confidence": confidence,
            "verify_score": verify.get("score", 0),
            "timestamp": int(time.time())
        })

        return jsonify({"message": "Signal processed", "verify": verify}), 200

    except Exception as e:
        print("❌ Webhook Error:", e)
        notify_trade(f"❌ AURA-X Error: {e}")
        _push_log("ERROR", f"Webhook error: {str(e)}")
        return jsonify({"error": str(e)}), 500
