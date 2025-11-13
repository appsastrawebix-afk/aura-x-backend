import os, requests, time
from dotenv import load_dotenv
from config.firebase_config import get_db  # ✅ added

# 🔹 Load environment vars
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 🔸 Basic safety check
def _check_config():
    if not TOKEN or not CHAT_ID:
        print("⚠️ Telegram config missing in .env (BOT_TOKEN / CHAT_ID)")
        return False
    return True

# 🧠 Push to Firebase logs (for dashboard)
def _push_log(status, message):
    try:
        db = get_db()
        db.child("logs").push({
            "time": time.strftime("%H:%M:%S"),
            "status": status,
            "message": message
        })
    except Exception as e:
        print("⚠️ Firebase log push failed:", e)

# 🧠 Clean text alert
def notify(msg: str):
    """Simple plain text message"""
    if not _check_config():
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=data)
        print("📨 Telegram:", msg)
        _push_log("INFO", msg)  # ✅ log to dashboard
    except Exception as e:
        print("❌ Telegram Error:", e)

# 🚀 Trade Alert — formatted message
def notify_trade(symbol, action, entry, target, stoploss, confidence, order_id, latency=None):
    """Rich trade alert for AURA-X"""
    emoji = "🟢" if action.upper() == "BUY" else "🔴"
    latency_text = f"\n⚡Latency: {latency}ms" if latency else ""
    message = f"""
🤖 *AURA-X MarketMind Signal*  
━━━━━━━━━━━━━━━━━━━  
📊 Symbol: `{symbol}`
🎯 Action: {emoji} *{action.upper()}*
💰 Entry: ₹{entry:.2f}
🎯 Target: ₹{target:.2f}
🛑 Stoploss: ₹{stoploss:.2f}
📈 Confidence: {confidence}%
🆔 Order ID: #{order_id}
━━━━━━━━━━━━━━━━━━━  
✅ Trade Executed | Trailing SL Active  
{latency_text}
""".strip()

    if not _check_config():
        return

    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=data)
        print(f"📨 Trade alert sent → {symbol} ({action})")

        # ✅ Push same to dashboard
        _push_log("TRADE", f"{action} {symbol} | Conf: {confidence}% | Entry ₹{entry:.2f}")

    except Exception as e:
        print("❌ Telegram send error:", e)

# ⚠️ System / Error alert
def notify_system_alert(level, title, msg):
    """Used for backend warnings or exceptions"""
    if not _check_config():
        return
    text = f"⚠️ *{level.upper()} ALERT* — {title}\n\n{msg}"
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, data=data)
        print(f"⚠️ System Alert Sent — {title}")
        _push_log(level.upper(), f"{title}: {msg}")  # ✅ log to dashboard
    except Exception as e:
        print("❌ Telegram System Alert Error:", e)

# 🕹️ Legacy compatibility
def notify_legacy(symbol, action, entry, target, stoploss, confidence, order_id):
    return notify_trade(symbol, action, entry, target, stoploss, confidence, order_id)
