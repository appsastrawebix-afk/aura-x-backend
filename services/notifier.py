import os
import time
import requests
from dotenv import load_dotenv
from config.firebase_config import get_db, init_firebase  # ✅ Added init_firebase

# 🔹 Initialize Firebase SDK
init_firebase()

# 🔹 Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 🧩 1️⃣ Telegram Message Sender
def _send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Telegram credentials missing — skipping notify.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        res = requests.post(url, data=data, timeout=10)
        if res.status_code == 200:
            print(f"📨 Telegram message sent successfully ({len(text)} chars)")
            return True
        else:
            print(f"⚠️ Telegram API error: {res.status_code}, {res.text[:100]}")
            return False
    except Exception as e:
        print("❌ Telegram send error:", e)
        return False


# 🧠 2️⃣ Push to Firebase logs (for Dashboard)
def _push_log(status, message):
    try:
        db = get_db()
        db.child("logs").push({
            "time": time.strftime("%H:%M:%S"),
            "status": status,
            "message": message
        })
        print(f"🪶 Log pushed to Firebase — {status}: {message}")
    except Exception as e:
        print("⚠️ Firebase log push failed:", e)


# 🚀 3️⃣ Trade Execution Message
def notify_trade(symbol, action, entry, target, stoploss, confidence, order_id, latency_ms=None):
    emoji = "🟢" if action.upper() == "BUY" else "🔴"
    timestamp = time.strftime("%H:%M:%S")
    latency_text = f"\n⚡ Exec Time: {latency_ms} ms" if latency_ms else ""

    message = f"""
🤖 *Astra MarketMind AI Signal*
━━━━━━━━━━━━━━━━━━━
*Symbol:* `{symbol}`
*Action:* {emoji} `{action.upper()}`
*Entry:* ₹{entry:.2f}
*Target 🎯:* ₹{target:.2f}
*Stoploss 🛑:* ₹{stoploss:.2f}
*Confidence:* {confidence}%
*Order ID:* #{order_id}
*Time:* {timestamp}{latency_text}
━━━━━━━━━━━━━━━━━━━
✅ *Trade Executed | Trailing SL Active*
""".strip()

    _send_telegram_message(message)
    _push_log("TRADE", f"{action} {symbol} | Conf: {confidence}% | Entry ₹{entry:.2f}")


# ⚠️ 4️⃣ Risk Limit Warning
def notify_risk_warning(uid, daily_pnl, soft_limit, hard_limit):
    message = f"""
⚠️ *AURA-X Risk Alert*
━━━━━━━━━━━━━━━━━━━
User: `{uid}`
Current P/L: ₹{daily_pnl}
Soft Limit: ₹{soft_limit}
Hard Limit: ₹{hard_limit}
━━━━━━━━━━━━━━━━━━━
🟠 *Warning:* Loss limit approaching!
"""
    _send_telegram_message(message)
    _push_log("RISK", f"{uid}: P/L {daily_pnl} near limit")


# 🧩 5️⃣ System Error / Info
def notify_system_alert(level, title, detail=""):
    emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🛑"}.get(level.upper(), "🔔")
    message = f"""
{emoji} *System {level.title()}*
━━━━━━━━━━━━━━━━━━━
*Event:* {title}
{detail}
━━━━━━━━━━━━━━━━━━━
Time: {time.strftime('%H:%M:%S')}
"""
    _send_telegram_message(message)
    _push_log(level.upper(), f"{title}: {detail}")
