# controllers/mode_controller.py
from flask import Blueprint, jsonify, request
import os
from dotenv import load_dotenv
from config.firebase_config import get_db, init_firebase

load_dotenv()
mode_bp = Blueprint("mode", __name__)

init_firebase()
db = get_db()

# ✅ Get current trading mode
@mode_bp.route("/status", methods=["GET"])
def get_status():
    try:
        mode = db.child("settings").child("trade_mode").get()
        mode_value = mode.lower() if mode else os.getenv("AURA_MODE", "demo").lower()
        return jsonify({
            "message": f"Current mode: {mode_value.upper()}",
            "mode": mode_value
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "mode": "demo"}), 500


# ✅ Switch mode Demo ↔ Live
@mode_bp.route("/switch", methods=["POST"])
def switch_mode():
    try:
        data = request.get_json(force=True)
        new_mode = data.get("mode", "").lower()
        if new_mode not in ["demo", "live"]:
            return jsonify({"error": "Invalid mode. Use 'demo' or 'live'"}), 400

        db.child("settings").child("trade_mode").set(new_mode)
        print(f"🔁 Trading Mode switched → {new_mode.upper()}")
        return jsonify({
            "message": f"Mode switched to {new_mode.upper()}",
            "mode": new_mode
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ✅ Helper for backend use
def get_mode():
    try:
        mode = db.child("settings").child("trade_mode").get()
        if mode:
            return mode.lower()
    except Exception:
        pass
    return os.getenv("AURA_MODE", "demo").lower()
