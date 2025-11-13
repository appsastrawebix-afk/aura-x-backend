import math
import time
from config.firebase_config import get_db

# Simple ATR implementation (needs candles list of dicts with high/low/close)
def calculate_atr(candles, period=14):
    """
    candles: list of {'high':, 'low':, 'close':}
    returns ATR (float)
    """
    if len(candles) < period + 1:
        # Not enough data, fallback to small value
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        return (max(highs) - min(lows)) / 2 if highs and lows else 1.0

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]['high']
        low = candles[i]['low']
        prev_close = candles[i-1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    # Simple SMA of TRs over period
    atr = sum(trs[-period:]) / period
    return atr if atr > 0 else 1.0


class RiskManager:
    def __init__(self):
        self.db = get_db()
        # default rules (configurable per-user later)
        self.max_risk_pct = 0.02   # 2% capital risk per trade
        self.daily_loss_limit_pct = 0.05  # 5% daily max loss
        self.atr_multiplier_sl = 1.5
        self.target_multiplier = 3.0
        self.trailing_step_pct = 0.5  # trail after every +0.5% profit

    # ------------------------
    # Position sizing
    # ------------------------
    def calculate_quantity(self, capital, entry_price, stoploss_price, product_type="INTRADAY"):
        """
        capital: user's capital (float)
        entry_price: price at which position will be opened
        stoploss_price: absolute price (not distance)
        returns integer quantity to trade (rounded down)
        logic: risk_amount = capital * max_risk_pct
               sl_distance = abs(entry - stoploss)
               qty = floor(risk_amount / (sl_distance * lot_multiplier))
        Note: For options, treat 1 lot = 1 contract; for equity/intraday may consider minimum qty.
        """
        risk_amount = capital * self.max_risk_pct
        sl_distance = abs(entry_price - stoploss_price)
        if sl_distance <= 0:
            return 0
        # For intraday margin/lot handling you may multiply by lot size; keep 1 for now
        qty = math.floor(risk_amount / sl_distance)
        if qty < 1:
            return 0
        return qty

    # ------------------------
    # Compute SL / Target from ATR
    # ------------------------
    def compute_sl_target_from_atr(self, candles, entry_price, direction):
        """
        candles: recent candles for ATR calculation
        entry_price: float
        direction: "BUY" or "SELL"
        returns: dict { stoploss, target, atr }
        """
        atr = calculate_atr(candles, period=14)
        sl_distance = self.atr_multiplier_sl * atr
        target_distance = self.target_multiplier * atr

        if direction == "BUY":
            stoploss = entry_price - sl_distance
            target = entry_price + target_distance
        else:  # SELL
            stoploss = entry_price + sl_distance
            target = entry_price - target_distance

        # Round sensible
        return {
            "atr": round(atr, 4),
            "stoploss": round(stoploss, 2),
            "target": round(target, 2),
            "sl_distance": round(sl_distance, 4),
            "target_distance": round(target_distance, 4)
        }

    # ------------------------
    # Save trade risk plan to Firebase (so trade_controller can pick it)
    # ------------------------
    def save_trade_plan(self, uid, trade_plan):
        """
        trade_plan: dict with keys:
            symbol, direction, entry_price, stoploss, target, qty, created_at
        """
        ref = self.db.child("risk_plans").child(uid)
        key = ref.push(trade_plan)
        return key

    # ------------------------
    # Daily loss check
    # ------------------------
    def check_daily_loss_limit(self, uid, capital):
        """
        Calculate today's P&L for uid (simple calculation using trades logged)
        If loss exceeds daily_loss_limit_pct, return False (do not allow new trade)
        """
        today_ts = int(time.time()) - 24*3600
        trades = self.db.child("trades").child(uid).get() or {}
        pnl = 0.0
        for t_key, t in (trades.items() if isinstance(trades, dict) else []):
            # Expect trades stored with fields: pnl (profit negative/positive) and timestamp
            try:
                if t.get("timestamp", 0) >= today_ts:
                    pnl += float(t.get("pnl", 0))
            except:
                pass
        loss_limit = -abs(capital * self.daily_loss_limit_pct)
        # if pnl is negative and less than loss limit -> block
        if pnl <= loss_limit:
            return False, pnl, loss_limit
        return True, pnl, loss_limit

    # ------------------------
    # Trailing SL helper (compute new SL given running profit)
    # ------------------------
    def compute_trailing_sl(self, entry_price, current_price, direction, current_sl):
        """
        entry_price: float
        current_price: float
        direction: BUY or SELL
        current_sl: current stoploss price
        Returns new_sl (float) if trailing condition reached else current_sl
        trailing_step_pct used to move SL after profit thresholds
        """
        # percent move from entry
        move_pct = (current_price - entry_price) / entry_price * 100 if entry_price else 0.0
        if direction == "SELL":
            move_pct = (entry_price - current_price) / entry_price * 100 if entry_price else 0.0

        # For each trailing_step_pct threshold, compute how much SL should move
        # Example: after +0.5% profit, move SL to entry; after +1% move SL by half profit, etc.
        step = self.trailing_step_pct
        steps_passed = math.floor(move_pct / step) if move_pct > 0 else 0
        if steps_passed <= 0:
            return current_sl  # no change

        # Simple policy: lock-in a fraction of profit
        if direction == "BUY":
            # new_sl = max(current_sl, entry_price + (steps_passed * step/100) * entry_price - some buffer)
            # We'll move SL to entry when first threshold passed
            if steps_passed >= 1:
                new_sl = max(current_sl, round(entry_price, 2))
            else:
                new_sl = current_sl
        else:
            if steps_passed >= 1:
                new_sl = min(current_sl, round(entry_price, 2))
            else:
                new_sl = current_sl

        return new_sl
