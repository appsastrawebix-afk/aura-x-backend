from flask import Blueprint, request, jsonify
from config.firebase_config import get_db
import time

# 🔹 Create Flask Blueprint
broker_bp = Blueprint("broker", __name__)

# ---------------------------------------------------
# 🔑 Broker Connect API (Angel SmartAPI credentials)
# ---------------------------------------------------
@broker_bp.route("/connect", methods=["POST"])
def connect_broker():
    """
    Example Body (JSON):
    {
        "uid": "manual-1761997955",
        "api_key": "YOUR_API_KEY",
        "client_id": "A53735560",
        "password": "YOUR_BROKER_PASSWORD",
        "totp": "123456"
    }
    """
    try:
        data = request.get_json()

        # Validate inputs
        if not data or "uid" not in data or "api_key" not in data:
            return jsonify({"error": "uid आणि api_key आवश्यक आहेत"}), 400

        uid = data["uid"]
        user_ref = get_db().child("users").child(uid)

        broker_data = {
            "api_key": data.get("api_key"),
            "client_id": data.get("client_id"),
            "password": data.get("password"),
            "totp": data.get("totp"),
            "connected_at": int(time.time()),
            "access_token": "TEMP_TOKEN_{}".format(int(time.time()))
        }

        # Firebase मध्ये store करा
        user_ref.child("broker").set(broker_data)

        return jsonify({"message": "Broker Connected ✅", "broker": broker_data}), 200

    except Exception as e:
        print("⚠️ Broker Connect Error:", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------
# 🔍 Broker Status API
# ---------------------------------------------------
@broker_bp.route("/status/<uid>", methods=["GET"])
def broker_status(uid):
    try:
        broker_info = get_db().child("users").child(uid).child("broker").get()
        if not broker_info:
            return jsonify({"error": "Broker info not found"}), 404
        return jsonify({"broker": broker_info}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
