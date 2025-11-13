# backend/services/signal_verifier.py
"""
AURA-X — Signal Verification Engine (upgraded)
- Config via env (.env)
- Uses optional realtime snapshot provider if available
- Returns: { action, score, breakdown, reasons }
"""

import os
import time
import math
import logging

# Optional: try to import live snapshot helper (safe fallback)
try:
    from services.market_snapshot import get_realtime_snapshot
except Exception:
    # older name or not available — ignore, we'll handle None
    get_realtime_snapshot = None

# ---- logging ----
LOG_LEVEL = os.getenv("AURA_LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger("signal_verifier")

# ---- default config (can override via env) ----
CFG = {
    "time_window_start": os.getenv("SV_TIME_START", "09:45"),
    "time_window_end":   os.getenv("SV_TIME_END", "15:00"),
    "avoid_after":       os.getenv("SV_AVOID_AFTER", "15:10"),
    "min_confidence":    float(os.getenv("SV_MIN_CONF", "80")),
    "score_threshold_auto": float(os.getenv("SV_AUTO_THRESH", "0.75")),
    "score_threshold_manual": float(os.getenv("SV_MANUAL_THRESH", "0.65")),
    "volume_multiplier": float(os.getenv("SV_VOL_MULT", "1.5")),
    "min_delta": float(os.getenv("SV_MIN_DELTA", "0.30")),
    "oi_delta_abs_min": int(os.getenv("SV_OI_MIN", "2000")),
    "iv_delta_min_pct": float(os.getenv("SV_IV_MIN", "-5")),
    "iv_delta_max_pct": float(os.getenv("SV_IV_MAX", "20"))
}

# ---- utility helpers ----
def hhmm_to_minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def now_in_time_window(start, end):
    m = time.localtime()
    cur = m.tm_hour * 60 + m.tm_min
    return hhmm_to_minutes(start) <= cur <= hhmm_to_minutes(end)

# ---- weights (sum to 1) ----
WEIGHTS = {
    "market_direction": 0.25,
    "oi_build":         0.20,
    "volume_momentum":  0.15,
    "greeks":           0.15,
    "iv_sanity":        0.10,
    "confidence":       0.15
}

def _fetch_snapshot(symbol, provided_snapshot=None):
    """Prefer provided snapshot, else try global realtime provider, else empty dict."""
    if provided_snapshot:
        return provided_snapshot
    if get_realtime_snapshot:
        try:
            snap = get_realtime_snapshot(symbol)
            if snap:
                return snap
        except Exception as e:
            log.debug("market snapshot fetch error: %s", e)
    return {}

def verify_signal(signal, snapshot=None, verbose=False):
    """
    Main verification function.

    Args:
      signal: dict (from TradingView / AI)
      snapshot: optional realtime snapshot dict (best) - else will attempt to fetch
      verbose: bool -> extra logging

    Returns:
      {
        "action": "EXECUTE" | "MANUAL" | "SKIP",
        "score": float (0..1),
        "breakdown": {subscores...},
        "reasons": [ ... ]
      }
    """

    if verbose:
        log.setLevel("DEBUG")

    reasons = []
    breakdown = {}

    # 1) time window
    if not now_in_time_window(CFG["time_window_start"], CFG["time_window_end"]):
        return {"action": "SKIP", "score": 0.0, "breakdown": {}, "reasons": ["outside_time_window"]}

    # 2) only BUY signals allowed (per user's rule)
    if signal.get("side", "").upper() != "BUY":
        return {"action": "SKIP", "score": 0.0, "breakdown": {}, "reasons": ["not_buy_signal"]}

    # Pull snapshot
    snap = _fetch_snapshot(signal.get("symbol", ""), snapshot)

    total_score = 0.0

    # --- market direction ---
    md_score = 0.0
    try:
        idx = snap.get("index", {})
        ema20 = idx.get("ema20")
        ema50 = idx.get("ema50")
        ha3 = idx.get("ha_last3", [])
        if ema20 is not None and ema50 is not None:
            trend = "BULL" if ema20 > ema50 else "BEAR"
            sig_side = "CALL" if ("CE" in signal.get("symbol","") or signal.get("type","").upper()=="CE") else "PUT"
            if (trend == "BULL" and sig_side == "CALL") or (trend == "BEAR" and sig_side == "PUT"):
                if len(ha3) >= 3 and all(c.lower() == ("green" if trend=="BULL" else "red") for c in ha3[-3:]):
                    md_score = 1.0
                else:
                    md_score = 0.6
            else:
                md_score = 0.0
        else:
            md_score = 0.5
    except Exception as e:
        log.debug("md error: %s", e)
        md_score = 0.0
    breakdown["market_direction"] = md_score
    total_score += md_score * WEIGHTS["market_direction"]

    # --- OI build (ATM ±4) ---
    oi_score = 0.0
    try:
        oi = snap.get("oi", {})
        oi_delta = oi.get("atm_plus_minus_4_net_oi_delta_15m", 0)
        oi_avg = oi.get("oi_1h_avg", 0)
        thresh = max(CFG["oi_delta_abs_min"], int(0.03 * (oi_avg or 1)))
        # for BUY CE we want positive oi_delta (builder)
        if (signal.get("type","").upper().endswith("CE") and oi_delta >= thresh):
            oi_score = 1.0
        elif abs(oi_delta) >= (thresh * 0.6):
            oi_score = 0.6
        else:
            oi_score = 0.0
    except Exception as e:
        log.debug("oi error: %s", e)
        oi_score = 0.0
    breakdown["oi_build"] = oi_score
    total_score += oi_score * WEIGHTS["oi_build"]

    # --- volume / momentum ---
    vol_score = 0.0
    try:
        v = snap.get("volume", {})
        cv = v.get("candle_vol", 0)
        avg5 = v.get("avg_5", 1)
        ltp_ticks = snap.get("ltp_ticks", {})
        tick_delta_pct = ltp_ticks.get("last_3_delta_pct", 0)
        vol_ok = (cv >= CFG["volume_multiplier"] * (avg5 or 1))
        tick_ok = (abs(tick_delta_pct) >= 3.0)
        if vol_ok and tick_ok:
            vol_score = 1.0
        elif vol_ok or tick_ok:
            vol_score = 0.6
        else:
            vol_score = 0.0
    except Exception as e:
        log.debug("vol error: %s", e)
        vol_score = 0.0
    breakdown["volume_momentum"] = vol_score
    total_score += vol_score * WEIGHTS["volume_momentum"]

    # --- greeks sanity ---
    greeks_score = 0.0
    try:
        opt = snap.get("option", {})
        delta = abs(opt.get("delta", 0))
        gamma = opt.get("gamma", 0)
        theta = opt.get("theta", 0)
        d_ok = delta >= CFG["min_delta"]
        g_ok = gamma >= 0.03
        t_ok = theta > -12
        if d_ok and g_ok and t_ok:
            greeks_score = 1.0
        elif (d_ok and g_ok) or (d_ok and t_ok):
            greeks_score = 0.6
        else:
            greeks_score = 0.0
    except Exception as e:
        log.debug("greeks error: %s", e)
        greeks_score = 0.0
    breakdown["greeks"] = greeks_score
    total_score += greeks_score * WEIGHTS["greeks"]

    # --- iv sanity ---
    iv_score = 0.0
    try:
        opt = snap.get("option", {})
        ivd = opt.get("iv_delta_30m_pct", 0)
        if CFG["iv_delta_min_pct"] <= ivd <= CFG["iv_delta_max_pct"]:
            iv_score = 1.0
        else:
            iv_score = 0.0
            reasons.append("iv_out_of_range")
    except Exception as e:
        log.debug("iv error: %s", e)
        iv_score = 0.0
    breakdown["iv_sanity"] = iv_score
    total_score += iv_score * WEIGHTS["iv_sanity"]

    # --- confidence (TV + ai) ---
    conf_score = 0.0
    try:
        tv_conf = float(signal.get("confidence", 0))
        ai_score = float(signal.get("ai_score", 0)) if signal.get("ai_score") is not None else 0.0
        tv_norm = min(100.0, tv_conf) / 100.0
        ai_norm = ai_score if 0 <= ai_score <= 1 else 0.0
        combined = 0.6 * tv_norm + 0.4 * ai_norm
        conf_score = combined
    except Exception as e:
        log.debug("conf error: %s", e)
        conf_score = 0.0
    breakdown["confidence"] = conf_score
    total_score += conf_score * WEIGHTS["confidence"]

    # final score
    score = round(max(0.0, min(1.0, total_score)), 4)

    # decision
    if score >= CFG["score_threshold_auto"]:
        action = "EXECUTE"
    elif score >= CFG["score_threshold_manual"]:
        action = "MANUAL"
    else:
        action = "SKIP"

    # reasons for debugging (low sub-scores)
    if md_score < 0.5: reasons.append("market_direction_weak")
    if oi_score < 0.5: reasons.append("oi_weak")
    if vol_score < 0.5: reasons.append("volume_weak")
    if greeks_score < 0.5: reasons.append("greeks_weak")
    if conf_score < 0.5: reasons.append("confidence_weak")

    out = {
        "action": action,
        "score": score,
        "breakdown": breakdown,
        "reasons": reasons
    }

    if verbose:
        log.debug("verify_signal -> %s", out)
    return out


# ----- quick manual test helper (run `python -m backend.services.signal_verifier` ) -----
if __name__ == "__main__":
    sample_signal = {
        "symbol": "NIFTY24NOV22500CE",
        "type": "CE",
        "side": "BUY",
        "confidence": 95,
        "ai_score": 0.9
    }
    # minimal fake snapshot for local test
    sample_snapshot = {
        "index": {"ema20": 22600, "ema50": 22500, "ha_last3": ["green", "green", "green"]},
        "option": {"delta": 0.42, "gamma": 0.06, "theta": -3.2, "iv": 18.5, "iv_delta_30m_pct": 4.0},
        "oi": {"atm_plus_minus_4_net_oi_delta_15m": 3000, "oi_1h_avg": 80000},
        "volume": {"candle_vol": 16000, "avg_5": 8000},
        "ltp_ticks": {"last_3_delta_pct": 4.5}
    }
    print("Running local test...")
    res = verify_signal(sample_signal, sample_snapshot, verbose=True)
    print(res)
