from flask import Blueprint, request, jsonify
from config.firebase_config import get_db
import time
import uuid

# 🔹 Blueprint म्हणजे छोटं route group
user_bp = Blueprint("user", __name__)

# -----------------------------
# 🧍 REGISTER (नवीन user)
# -----------------------------
@user_bp.route("/register", methods=["POST"])
def register_user():
    data = request.get_json()
    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "email आणि password आवश्यक आहेत"}), 400

    user_id = str(uuid.uuid4())
    user_data = {
        "uid": user_id,
        "name": data.get("name", ""),
        "email": data["email"],
        "password": data["password"],  # Note: production मध्ये hash करायचं
        "created_at": int(time.time())
    }

    ref = get_db().child("users").child(user_id)
    ref.set(user_data)
    return jsonify({"message": "User नोंदवला गेला ✅", "user": user_data}), 201


# -----------------------------
# 🔐 LOGIN (user check करणे)
# -----------------------------
@user_bp.route("/login", methods=["POST"])
def login_user():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email आणि Password आवश्यक आहेत"}), 400

    users = get_db().child("users").get()
    if not users:
        return jsonify({"error": "कोणताही user नाही"}), 404

    for uid, info in users.items():
        if info.get("email") == email and info.get("password") == password:
            return jsonify({"message": "Login यशस्वी ✅", "user": info}), 200

    return jsonify({"error": "Invalid credentials"}), 401


# -----------------------------
# 🧍 DIRECT USER CREATE (तात्पुरता)
# -----------------------------
@user_bp.route("/create_direct", methods=["GET"])
def create_direct_user():
    ref = get_db().child("users")
    user_id = "manual-" + str(int(time.time()))
    user_data = {
        "uid": user_id,
        "name": "Amit",
        "email": "infoitamicos@gmail.com",
        "password": "Admin@123",
        "created_at": int(time.time())
    }
    ref.child(user_id).set(user_data)
    return jsonify({"message": "Direct user created ✅", "user": user_data}), 200
