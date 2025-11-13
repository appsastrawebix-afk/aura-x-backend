# services/aura_guard.py
"""
AURA-X — Guard process (aura_guard)
Responsibilities:
 - Monitor per-user daily P&L and drawdown
 - Auto-pause trading if soft/hard stop breached
 - Notify admins via notifier.notify_system_alert / Telegram
 - Support auto-resume rules or manual resume via Firebase key
"""

import os
import time
import traceback
from dotenv import load_dotenv

# local imports from your project
from config.firebase_config import init_firebase, get_db
from services.risk_manager import RiskManager
try:
    from services.notifier import notify_system_alert
except Exception:
    # fallback logger if notifier missing
    def notify_system_alert(level, title, body):
        print(f"[ALERT {level}] {title} — {body}")

# load env
load_dotenv()

# ------------------------------------------------------------------
# Config (env or Firebase override)
# ------------------------------------------------------------------
CHECK_INTERVAL = int(os.getenv("AURA_GUARD_INTERVAL_SEC", "30"))   # loop interval
SOFT_STOP_PCT = float(os.getenv("AURA_GUARD_SOFT_PCT", "0.03"))   # 3% daily loss (fraction of capital) default
HARD_STOP_PCT = float(os.getenv("AURA_GUARD_HARD_PCT", "0.05"))   # 5% daily loss
MIN_TRADES_BEFORE_PAUSE = int(os.getenv("AURA_GUARD_MIN_TRADES", "1"))
AUTO_RESUME_AFTER_SECONDS = int(os.getenv("AURA_GUARD_AUTO_RESUME_SEC", "0"))  # 0 = disabled

# Firebase keys used:
# - /system/mode  -> "live" | "demo" | "paused"
# - /system/paused_info -> {reason, at, user, pnl, limit}
# - /system/config/aura_guard -> optional overrides
# - /broker_tokens -> existing usage
# - users -> user entries with 'capital' (optional)
# - trades -> per-uid trades

# ------------------------------------------------------------------
# Init Firebase + Risk manager
# ------------------------------------------------------------------
init_firebase()
db = get_db()
rm = RiskManager()

# helper utilities
def read_guard_config_from_db():
    cfg_ref = db.child("system").child("config").child("aura_guard").get() or {}
    cfg = {}
    if isinstance(cfg_ref, dict):
        cfg["soft_pct"] = float(cfg_ref.get("soft_pct", SOFT_STOP_PCT))
        cfg["hard_pct"] = float(cfg_ref.get("hard_pct", HARD_STOP_PCT))
        cfg["min_trades"] = int(cfg_ref.get("min_trades", MIN_TRADES_BEFORE_PAUSE))
        cfg["auto_resume_sec"] = int(cfg_ref.get("auto_resume_sec", AUTO_RESUME_AFTER_SECONDS))
    else:
        cfg["soft_pct"] = SOFT_STOP_PCT
        cfg["hard_pct"] = HARD_STOP_PCT
        cfg["min_trades"] = MIN_TRADES_BEFORE_PAUSE
        cfg["auto_resume_sec"] = AUTO_RESUME_AFTER_SECONDS
    return cfg

def get_system_mode():
    m = db.child("system").child("mode").get()
    return (m or "live")

def set_system_mode(mode):
    db.child("system").child("mode").set(mode)
    return True

def record_pause_info(reason, uid=None, pnl=None, limit=None):
    payload = {
        "reason": reason,
        "by": "aura_guard",
        "at": int(time.time()),
        "uid": uid,
        "pnl": pnl,
        "limit": limit
    }
    db.child("system").child("paused_info").set(payload)
    return payload

def clear_pause_info():
    db.child("system").child("paused_info").remove()

def get_users_list():
    users = db.child("users").get() or {}
    if isinstance(users, dict):
        return users
    return {}

def calculate_user_daily_pnl(uid):
    """
    Compute approximate daily P&L for user by summing trades with exit_time today.
    Relies on stored trades in /trades/<uid>/<trade_key> with entry_price/exit_price and quantity.
    This is a best-effort calculation; you can replace it with your accurate P&L function.
    """
    total = 0.0
    try:
        trades = db.child("trades").child(uid).get() or {}
        if not isinstance(trades, dict):
            return 0.0, 0  # pnl, trades_count
        today_start = int(time.time()//86400 * 86400)  # epoch start of day
        count = 0
        for k, t in trades.items():
            # We consider entries with exit_time set (closed trades) OR status being STOP/TARGET
            status = t.get("status", "").upper()
            exit_time = t.get("exit_time", 0)
            if exit_time and exit_time >= today_start:
                entry = float(t.get("entry_price", 0) or 0)
                exitp = float(t.get("exit_price", t.get("price", 0) or 0))
                qty = int(t.get("quantity", 0) or 0)
                pnl = (exitp - entry) * qty if t.get("type","").upper() == "BUY" else (entry - exitp) * qty
                total += pnl
                count += 1
            else:
                # optionally include MTM/unclosed trades — skip to avoid noise
                pass
        return float(total), count
    except Exception as e:
        print("⚠️ calculate_user_daily_pnl error:", e)
        return 0.0, 0

def check_user_against_limits(uid, user_obj, cfg):
    """
    Returns: (allowed: bool, pnl: float, soft_limit: float, hard_limit: float, trades_count)
    """
    capital = float(user_obj.get("capital", cfg.get("default_capital", 100000)))
    pnl, trades_count = calculate_user_daily_pnl(uid)
    soft_limit_value = -abs(capital * cfg["soft_pct"])
    hard_limit_value = -abs(capital * cfg["hard_pct"])
    allowed = True
    reason = None
    if trades_count >= cfg["min_trades"] and pnl <= hard_limit_value:
        allowed = False
        reason = "HARD_STOP"
    elif trades_count >= cfg["min_trades"] and pnl <= soft_limit_value:
        allowed = False
        reason = "SOFT_STOP"
    return allowed, pnl, soft_limit_value, hard_limit_value, trades_count, reason

def pause_system(reason, uid=None, pnl=None, limit=None):
    current = get_system_mode()
    if current == "paused":
        return False  # already paused
    set_system_mode("paused")
    info = record_pause_info(reason, uid, pnl, limit)
    notify_system_alert("CRITICAL", "AURA-GUARD: System Paused", f"Reason: {reason}, uid: {uid}, pnl: {pnl}, limit: {limit}")
    print(f"⛔ System paused by aura_guard — reason={reason} uid={uid} pnl={pnl} limit={limit}")
    return True

def try_auto_resume_if_allowed(cfg):
    """
    Auto-resume logic:
     - If cfg.auto_resume_sec > 0 and system paused since > auto_resume_sec, resume.
     - Or if admin set /system/force_resume = true.
    """
    if cfg["auto_resume_sec"] <= 0:
        return False
    paused = db.child("system").child("paused_info").get() or {}
    if not isinstance(paused, dict) or not paused.get("at"):
        return False
    paused_at = int(paused.get("at", 0))
    if time.time() - paused_at >= cfg["auto_resume_sec"]:
        # resume
        set_system_mode("live")
        clear_pause_info()
        notify_system_alert("INFO", "AURA-GUARD: Auto-resume", f"Auto-resume after cooldown ({cfg['auto_resume_sec']}s)")
        print("✅ Auto-resume triggered by aura_guard")
        return True
    # admin forced resume?
    if db.child("system").child("force_resume").get() == True:
        set_system_mode("live")
        db.child("system").child("force_resume").remove()
        clear_pause_info()
        notify_system_alert("INFO", "AURA-GUARD: Admin resume", "Admin forced resume via Firebase flag")
        print("✅ Admin resume applied")
        return True
    return False

# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
def run_guard_loop():
    print("🛡️  AURA-GUARD started. Checking every", CHECK_INTERVAL, "seconds.")
    while True:
        try:
            cfg_db = read_guard_config_from_db()
            cfg = {
                "soft_pct": cfg_db.get("soft_pct", SOFT_STOP_PCT),
                "hard_pct": cfg_db.get("hard_pct", HARD_STOP_PCT),
                "min_trades": cfg_db.get("min_trades", MIN_TRADES_BEFORE_PAUSE),
                "auto_resume_sec": cfg_db.get("auto_resume_sec", AUTO_RESUME_AFTER_SECONDS),
                "default_capital": 100000
            }

            # check if paused already and maybe auto-resume
            current_mode = get_system_mode()
            if current_mode == "paused":
                # try auto resume conditions
                if try_auto_resume_if_allowed(cfg):
                    # resumed - continue main loop
                    time.sleep(CHECK_INTERVAL)
                    continue
                else:
                    # keep paused
                    time.sleep(CHECK_INTERVAL)
                    continue

            # iterate users and check P&L vs thresholds
            users = get_users_list()
            for uid, uobj in users.items():
                allowed, pnl, soft_limit, hard_limit, trades_count, reason = check_user_against_limits(uid, uobj, cfg)
                # If not allowed -> pause system
                if not allowed:
                    # Pause and notify
                    pause_reason = reason or "LOSS_LIMIT"
                    pause_system(pause_reason, uid=uid, pnl=pnl, limit=(hard_limit if pause_reason=="HARD_STOP" else soft_limit))
                    # once paused, break checking others until next cycle
                    break

            # small delay before next cycle
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("🛑 aura_guard stopped by user.")
            break
        except Exception as e:
            print("⚠️ aura_guard runtime error:", e)
            traceback.print_exc()
            notify_system_alert("ERROR", "AURA-GUARD Exception", str(e))
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run_guard_loop()
