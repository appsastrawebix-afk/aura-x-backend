import random
import time
from config.firebase_config import get_db

# --------------------------------------------
#  🔹 AURA-X Strategy Core  (with Option Detection)
# --------------------------------------------

class StrategyCore:
    def __init__(self):
        self.db = get_db()

    # ------------------------------
    #  Candle Data (simulated / API)
    # ------------------------------
    def fetch_candles(self, symbol, interval="5m", limit=50):
        """Simulate candle data or fetch from Angel One API later"""
        candles = []
        base = 22500
        for i in range(limit):
            o = base + random.uniform(-40, 40)
            c = o + random.uniform(-15, 15)
            h = max(o, c) + random.uniform(0, 5)
            l = min(o, c) - random.uniform(0, 5)
            candles.append({"open": o, "close": c, "high": h, "low": l})
        return candles

    # ------------------------------
    #  Indicators
    # ------------------------------
    def ema(self, prices, period):
        """Calculate Exponential Moving Average"""
        k = 2 / (period + 1)
        ema = []
        for i, p in enumerate(prices):
            ema.append(p if i == 0 else p * k + ema[-1] * (1 - k))
        return ema

    def rsi(self, prices, period=14):
        """Calculate RSI (Relative Strength Index)"""
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            if diff >= 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))
        avg_gain = sum(gains[-period:]) / period if gains else 0
        avg_loss = sum(losses[-period:]) / period if losses else 0
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # ------------------------------
    #  Symbol Analyzer (Detect CE/PE/Normal)
    # ------------------------------
    def analyze_symbol(self, symbol):
        """
        Detects whether symbol is Option or Normal.
        Returns dict:
        {
            "is_option": True/False,
            "option_type": "CE"/"PE"/"NA",
            "base_symbol": "NIFTY"
        }
        """
        symbol = symbol.upper()
        is_option = False
        option_type = "NA"
        base_symbol = symbol

        if "CE" in symbol or "PE" in symbol:
            is_option = True
            if "CE" in symbol:
                option_type = "CE"
            elif "PE" in symbol:
                option_type = "PE"

            # Extract base symbol (like "NIFTY" from "NIFTY24NOV22500CE")
            base_symbol = ''.join([c for c in symbol if not c.isdigit()])
            base_symbol = base_symbol.split("CE")[0].split("PE")[0].strip()

        return {
            "is_option": is_option,
            "option_type": option_type,
            "base_symbol": base_symbol
        }

    # ------------------------------
    #  Strategy Logic
    # ------------------------------
    def generate_signal(self, symbol):
        """Main AURA-X Strategy Logic"""
        candles = self.fetch_candles(symbol)
        closes = [c["close"] for c in candles]
        ema20 = self.ema(closes, 20)[-1]
        ema50 = self.ema(closes, 50)[-1]
        rsi_val = self.rsi(closes)
        last_price = closes[-1]

        action = "HOLD"
        reason = ""

        if ema20 > ema50 and rsi_val < 70:
            action, reason = "BUY", "Trend UP + RSI < 70"
        elif ema20 < ema50 and rsi_val > 30:
            action, reason = "SELL", "Trend DOWN + RSI > 30"

        signal = {
            "symbol": symbol,
            "price": round(last_price, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "rsi": round(rsi_val, 2),
            "action": action,
            "reason": reason,
            "created_at": int(time.time())
        }

        # Add option detection info
        symbol_info = self.analyze_symbol(symbol)
        signal.update(symbol_info)

        # Save in Firebase
        self.db.child("signals").push(signal)
        print(f"📈 Generated Signal → {signal}")
        return signal
