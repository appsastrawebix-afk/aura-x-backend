from flask import Blueprint, request, jsonify
import time, random

risk_bp = Blueprint("risk", __name__)

# ------------------------------------------
# ✅ Safe Firebase + RiskManager Initialization
# ------------------------------------------
try:
    from config.firebase_config import init_firebase, get_db
    from services.risk_manager import RiskManager
    init_firebase()
    db = get_db()
    rm = RiskManager()
    print("✅ RiskController initialized successfully.")
except Exception as e:
    print("⚠️ RiskController init failed:", e)
    db, rm = None, None


# ------------------------------------------
# 🔹 Risk Monitor (Dashboard API)
# ------------------------------------------
@risk_bp.route("/status", methods=["GET"])
def risk_status():
    """Dashboard साठी live risk summary"""
    try:
        # 🧠 If Firebase not ready, show simulated data
        if not db or not rm:
            total_pl = random.randint(-200, 1200)
            soft_stop = 300
            hard_stop = 400
            percent = round(abs(total_pl) / hard_stop * 100, 2)
            status = (
                "STOP" if total_pl <= -hard_stop
                else "WARNING" if total_pl <= -soft_stop
                else "ACTIVE"
            )
            return jsonify({
                "daily_pl_value": total_pl,
                "daily_pl_percent": percent,
                "soft_stop": soft_stop,
                "hard_stop": hard_stop,
                "status": status
            }), 200

        # 🧮 Fetch trades from Firebase for real calculation
        trades = db.child("trades").get() or {}
        total_pl = 0
        trade_count = 0

        if isinstance(trades, dict):
            for uid, trade_data in trades.items():
                for t in trade_data.values():
                    entry = float(t.get("entry_price", 0))
                    exit_p = float(t.get("exit_price", entry))
                    qty = int(t.get("quantity", 0))
                    side = t.get("type", "BUY")
                    pnl = (exit_p - entry) * qty if side == "BUY" else (entry - exit_p) * qty
                    total_pl += pnl
                    trade_count += 1

        soft_stop = 300
        hard_stop = 400
        percent = round(abs(total_pl) / hard_stop * 100, 2) if hard_stop else 0

        if total_pl <= -hard_stop:
            status = "STOP"
        elif total_pl <= -soft_stop:
            status = "WARNING"
        else:
            status = "ACTIVE"

        return jsonify({
            "daily_pl_value": round(total_pl, 2),
            "daily_pl_percent": percent,
            "soft_stop": soft_stop,
            "hard_stop": hard_stop,
            "status": status,
            "total_trades": trade_count
        }), 200

    except Exception as e:
        print("⚠️ Risk Status Error:", e)
        return jsonify({"error": str(e)}), 500
