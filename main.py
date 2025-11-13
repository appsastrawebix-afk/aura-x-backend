from flask import Flask, jsonify
from flask_cors import CORS
from config.firebase_config import init_firebase, get_db

# ------------------------------------------
# 🔹 Flask App Initialize
# ------------------------------------------
app = Flask(__name__)

# ✅ Enable proper CORS for frontend + TradingView webhooks
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# ✅ Better JSON and error handling
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True
app.config["PROPAGATE_EXCEPTIONS"] = True

# ------------------------------------------
# 🔹 Firebase Initialize (before controllers)
# ------------------------------------------
try:
    init_firebase()
    print("🔥 Firebase initialized successfully.")
except Exception as e:
    print("⚠️ Firebase init failed:", e)

# ------------------------------------------
# 🔹 Import Controllers (Blueprints)
# ------------------------------------------
from controllers.user_controller import user_bp
from controllers.broker_controller import broker_bp
from controllers.trade_controller import trade_bp
from controllers.signal_controller import signal_bp
from controllers.risk_controller import risk_bp
from controllers.tradingview_webhook import webhook_bp
from controllers.mode_controller import mode_bp
from controllers.notification_controller import notif_bp

# ------------------------------------------
# 🔹 Register Blueprints
# ------------------------------------------
app.register_blueprint(user_bp, url_prefix="/api/user")
app.register_blueprint(broker_bp, url_prefix="/api/broker")
app.register_blueprint(trade_bp, url_prefix="/api/trade")
app.register_blueprint(signal_bp, url_prefix="/api/signal")
app.register_blueprint(risk_bp, url_prefix="/api/risk")          # ✅ Risk Monitor
app.register_blueprint(webhook_bp, url_prefix="/api")            # ✅ TradingView Webhooks
app.register_blueprint(mode_bp, url_prefix="/api/mode")          # ✅ Demo/Live Mode Switch
app.register_blueprint(notif_bp, url_prefix="/api")              # ✅ Notifications Fetch

# ------------------------------------------
# 🔹 Default Routes / Health Checks
# ------------------------------------------
@app.route("/")
def home():
    """Base route for quick status check."""
    return jsonify({
        "message": "✅ AURA-X Backend Running",
        "status": "ok",
        "available_endpoints": [
            "/api/webhook/tradingview",
            "/api/notifications",
            "/api/risk/status",
            "/api/mode/status",
            "/api/mode/switch"
        ]
    }), 200


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "time": "server active"}), 200


@app.route("/write", methods=["GET"])
def write_data():
    ref = get_db()
    ref.child("test").push({"msg": "Hello Firebase 🔥"})
    return jsonify({"message": "Data written to Firebase"}), 200


@app.route("/read", methods=["GET"])
def read_data():
    ref = get_db().child("test")
    data = ref.get()
    return jsonify({"data": data}), 200

# ------------------------------------------
# 🔹 AURA-X Auto ATM Executor (Background Worker)
# ------------------------------------------
try:
    from services.atm_executor import start_atm_executor_in_thread
    stop_event, executor_thread = start_atm_executor_in_thread()
    print("🚀 AURA-X ATM Executor initialized and running in background.")
except Exception as e:
    print("⚠️ ATM Executor failed to start:", e)

# ------------------------------------------
# 🔹 Run Flask Server
# ------------------------------------------
if __name__ == "__main__":
    print("✅ AURA-X Backend Started Successfully — Ready for Auto Execution & Webhooks.")
    app.run(host="0.0.0.0", port=5000, debug=False)
