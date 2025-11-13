import os
import time
import requests
import pyotp
from dotenv import load_dotenv
from config.firebase_config import init_firebase, get_db

load_dotenv()

class AngelSmartAPI:
    """🔹 Angel SmartAPI Integration (Login + Token + LTP)"""

    def __init__(self):
        init_firebase()
        self.db = get_db()

        # Env Variables
        self.api_key = os.getenv("ANGEL_API_KEY")
        self.client_id = os.getenv("ANGEL_CLIENT_ID")
        self.password = os.getenv("ANGEL_PASSWORD")
        self.totp_secret = os.getenv("ANGEL_TOTP_SECRET")

        # API URLs
        self.auth_base = "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1"
        self.order_base = "https://apiconnect.angelbroking.com/rest/secure/angelbroking"
        self.market_base = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1"

        # Token cache
        self.access_token = None
        self.last_login = 0


    # 🔹 1️⃣ Generate TOTP
    def get_totp(self):
        try:
            code = pyotp.TOTP(self.totp_secret).now()
            print(f"📟 Generated TOTP: {code}")
            return code
        except Exception as e:
            print("⚠️ TOTP generation error:", e)
            return None


    # 🔹 2️⃣ Login / Token Fetch
    def get_access_token(self, force_refresh=False):
        """Login करून JWT Access Token मिळवा आणि Firebase मध्ये साठवा"""
        # Cached token वापर (10 मिनिटांपर्यंत valid)
        if not force_refresh and self.access_token and (time.time() - self.last_login) < 600:
            return self.access_token

        print("🔐 Fetching new AngelOne token...")
        login_url = f"{self.auth_base}/loginByPassword"
        totp = self.get_totp()

        if not totp:
            print("❌ TOTP generation failed.")
            return None

        payload = {
            "clientcode": self.client_id,
            "password": self.password,
            "totp": totp
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "AA:BB:CC:DD:EE:FF",
            "X-PrivateKey": self.api_key
        }

        try:
            res = requests.post(login_url, json=payload, headers=headers, timeout=10)
            data = res.json()
            if res.status_code == 200 and "data" in data:
                token = data["data"].get("jwtToken")
                feed_token = data["data"].get("feedToken")

                if token:
                    self.access_token = token
                    self.last_login = time.time()

                    # 🔸 Firebase मध्ये साठवा
                    token_ref = self.db.child("broker_tokens").child(self.client_id)
                    token_ref.set({
                        "access_token": token,
                        "feed_token": feed_token,
                        "created_at": int(time.time())
                    })

                    print("✅ AngelOne Login Success — Token Stored in Firebase.")
                    return token

            print(f"❌ Login failed: {data}")
            return None
        except Exception as e:
            print("⚠️ Login error:", e)
            return None


    # 🔹 3️⃣ LTP Fetcher (used by TradeWatcher)
    def get_ltp(self, symbol):
        """Fetch real-time LTP using Angel SmartAPI."""
        try:
            from controllers.trade_controller import contracts
            if symbol not in contracts:
                print(f"⚠️ {symbol} not in contract list.")
                return None

            contract = contracts[symbol]
            url = f"{self.market_base}/quote/"
            headers = {
                "Authorization": f"Bearer {self.get_access_token()}",
                "X-PrivateKey": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            payload = {
                "mode": "LTP",
                "exchangeTokens": {contract["exchange"]: [contract["token"]]}
            }

            res = requests.post(url, json=payload, headers=headers, timeout=10)
            data = res.json()

            if "data" in data and data["data"]["fetched"]:
                ltp = float(data["data"]["fetched"][0]["ltp"])
                print(f"📈 LTP {symbol} = {ltp}")
                return ltp
            else:
                print(f"⚠️ LTP fetch failed for {symbol}: {data}")
                return None
        except Exception as e:
            print("⚠️ LTP fetch error:", e)
            return None


    # 🔹 4️⃣ Generic Order Executor (Reusable)
    def place_order(self, payload):
        """SmartAPI order wrapper"""
        try:
            url = f"{self.order_base}/order/v1/placeOrder"
            headers = {
                "Authorization": f"Bearer {self.get_access_token()}",
                "X-PrivateKey": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            data = res.json()
            if "Invalid Session" in str(data):
                print("⚠️ Session expired — refreshing token.")
                self.get_access_token(force_refresh=True)
                return self.place_order(payload)
            return data
        except Exception as e:
            print("⚠️ Order error:", e)
            return {"status": False, "error": str(e)}
