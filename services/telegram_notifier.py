import os
import requests
from dotenv import load_dotenv

load_dotenv()

class TelegramNotifier:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, text):
        """Send message to Telegram channel or user"""
        if not self.bot_token or not self.chat_id:
            print("⚠️ Telegram credentials missing in .env")
            return
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            res = requests.post(self.base_url, json=payload)
            if res.status_code == 200:
                print(f"📨 Telegram Alert Sent: {text}")
            else:
                print("❌ Telegram API error:", res.text)
        except Exception as e:
            print("⚠️ Telegram send error:", e)
