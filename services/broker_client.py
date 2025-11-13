import os
from SmartApi import SmartConnect
import pyotp
from dotenv import load_dotenv

load_dotenv()

class AngelOneClient:
    def __init__(self):
        self.api_key = os.getenv("ANGEL_API_KEY")
        self.client_id = os.getenv("ANGEL_CLIENT_ID")
        self.password = os.getenv("ANGEL_PASSWORD")
        self.totp_key = os.getenv("ANGEL_TOTP_SECRET")
        self.obj = SmartConnect(api_key=self.api_key)
        self._login()

    def _login(self):
        token = pyotp.TOTP(self.totp_key).now()
        data = self.obj.generateSession(self.client_id, self.password, token)
        self.jwt_token = data["data"]["jwtToken"]
        print("✅ Angel One Login Success")

    def place_order(self, symbol, side, qty):
        payload = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": "99926000",  # Example token, replace with correct from Angel instruments list
            "transactiontype": side.upper(),
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": int(qty),
        }
        response = self.obj.placeOrder(payload)
        print("📦 Order Response:", response)
        return response
