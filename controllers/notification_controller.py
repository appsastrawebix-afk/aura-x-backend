# controllers/notification_controller.py

from flask import Blueprint, jsonify
from config.firebase_config import get_db

# 🔹 Blueprint initialization
notif_bp = Blueprint("notifications", __name__)

# ✅ Route: /api/notifications
@notif_bp.route("/notifications", methods=["GET"])
def get_notifications():
    """
    Fetch recent system/trade notifications from Firebase Realtime DB
    to show inside the AURA-X dashboard.
    """
    try:
        db = get_db()

        # ✅ Directly get data from Firebase (Admin SDK returns dict)
        logs_data = db.child("logs").get()
        data = []

        # ✅ Handle Firebase response (dict or None)
        if isinstance(logs_data, dict):
            for _, v in sorted(logs_data.items(), reverse=True):
                data.append({
                    "time": v.get("time", "--:--"),
                    "status": v.get("status", "INFO"),
                    "message": v.get("message", "No message")
                })
        elif logs_data is not None:
            print("⚠️ Unexpected logs_data type:", type(logs_data))

        # ✅ Fallback demo data if no Firebase entries
        if not data:
            data = [
                {"time": "14:25", "status": "Succeeded", "message": "BUY NIFTY 22500 PE"},
                {"time": "14:08", "status": "Skipped", "message": "Filters failed"},
            ]

        # ✅ Uniform response for frontend
        return jsonify({"data": data}), 200

    except Exception as e:
        print("⚠️ Notification fetch error:", e)
        return jsonify({
            "error": "Failed to load notifications",
            "details": str(e)
        }), 500
