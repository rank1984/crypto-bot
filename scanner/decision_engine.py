"""
CRYPTO-BOT Elite — Decision Engine

מנוע אחד שמחליט: BUY / WAIT / IGNORE
ומסביר בדיוק למה.

מקבל coin dict מ-ranking ומחזיר:
{
    "decision":   "BUY" / "WAIT" / "IGNORE",
    "rating":     "A+" / "A" / "B+" / "B" / "C",
    "confidence": 0-100,
    "reason":     "טקסט קצר",
    "missing":    ["מה חסר"],
    "positives":  ["מה יש"],
    "score_breakdown": {...}
}
"""
from utils.logger import get_logger
log = get_logger(__name__)


# ─── Thresholds per Regime ────────────────────────────────────────────────────

_REGIME_THRESHOLDS = {
    "TRENDING_BULL": {"flow": 50, "pre": 35, "rvol": 0.8, "rating_min": "B"},
    "ALTSEASON":     {"flow": 45, "pre": 30, "rvol": 0.7, "rating_min": "B"},
    "RANGE":         {"flow": 55, "pre": 40, "rvol": 0.8, "rating_min": "B+"},
    "RISK_OFF":      {"flow": 65, "pre": 55, "rvol": 1.2, "rating_min": "A"},
    "TRENDING_BEAR": {"flow": 75, "pre": 65, "rvol": 1.5, "rating_min": "A+"},
}

_RATING_ORDER = ["C", "B", "B+", "A", "A+"]


def _rating_ok(rating: str, min_rating: str) -> bool:
    return _RATING_ORDER.index(rating) >= _RATING_ORDER.index(min_rating)


# ─── Core Decision ────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    """
    ההחלטה המרכזית — מנוע אחד, תשובה אחת.
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    regime     = coin.get("regime", "RANGE")
    catalyst   = coin.get("has_catalyst", False)

    thr = _REGIME_THRESHOLDS.get(regime, _REGIME_THRESHOLDS["RANGE"])

    # ── ציון איכות ────────────────────────────────────────────────────────────
    score = 0

    # Flow (35)
    if flow >= 75: score += 35
    elif flow >= 60: score += 25
    elif flow >= 45: score += 15
    elif flow >= 30: score += 7

    # Pre-Breakout (25)
    if pre >= 70: score += 25
    elif pre >= 55: score += 18
    elif pre >= 40: score += 10
    elif pre >= 25: score += 5

    # Volume (15)
    if vol_exp:       score += 15
    elif rvol >= 2.0: score += 12
    elif rvol >= 1.2: score += 7
    elif rvol >= 0.8: score += 3

    # OI + Compression (15)
    if oi > 5 and compressed: score += 15
    elif oi > 2:               score += 8
    if compressed and oi <= 2: score += 7

    # RS + Whale (10)
    if rs_1h > 1.5:   score += 7
    elif rs_1h > 0:   score += 3
    if whale:         score += 3

    # Entry + Catalyst (bonus)
    if entry_dec == "BUY": score += 5
    if catalyst:           score += 5

    # Regime multiplier
    multipliers = {"TRENDING_BULL": 1.0, "ALTSEASON": 1.05,
                   "RANGE": 1.0, "RISK_OFF": 0.85, "TRENDING_BEAR": 0.70}
    score = min(100, int(score * multipliers.get(regime, 1.0)))

    # ── Rating ────────────────────────────────────────────────────────────────
    if score >= 90:   rating = "A+"
    elif score >= 75: rating = "A"
    elif score >= 60: rating = "B+"
    elif score >= 45: rating = "B"
    else:             rating = "C"

    # ── Positives ─────────────────────────────────────────────────────────────
    positives = []
    if vol_exp:        positives.append("💥 פיצוץ נפח")
    if flow >= 60:     positives.append(f"Flow חזק ({flow:.0f})")
    if oi > 2:         positives.append(f"OI עולה {oi:+.1f}%")
    if compressed:     positives.append("Compression")
    if rs_1h > 0.5:   positives.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    if whale:          positives.append("פעילות לווייתנים")
    if catalyst:       positives.append("Catalyst")

    # ── Missing ───────────────────────────────────────────────────────────────
    missing = []
    if flow < thr["flow"]:
        missing.append(f"Flow מעל {thr['flow']} (יש {flow:.0f})")
    if oi <= 1:
        missing.append("OI חיובי")
    if rvol < thr["rvol"]:
        missing.append(f"RVOL מעל {thr['rvol']} (יש {rvol:.1f}x)")
    if not compressed:
        missing.append("Compression")
    if rs_1h <= 0:
        missing.append("חוזק מול BTC")

    # ── Decision ──────────────────────────────────────────────────────────────
    flow_ok    = flow >= thr["flow"]
    rvol_ok    = rvol >= thr["rvol"]
    rating_ok  = _rating_ok(rating, thr["rating_min"])
    has_entry  = entry_dec == "BUY"
    bear_mode  = regime in ("TRENDING_BEAR", "RISK_OFF")

    if bear_mode and not catalyst:
        decision = "IGNORE"
        reason   = f"{regime}: מחפשים רק A+ עם Catalyst"
    elif rating == "C" or score < 35:
        decision = "IGNORE"
        reason   = "ציון נמוך מדי"
    elif flow_ok and rvol_ok and rating_ok and has_entry:
        decision = "BUY"
        reason   = f"כל התנאים מתקיימים — דירוג {rating}"
    elif flow_ok and rvol_ok and rating_ok:
        decision = "WAIT"
        reason   = "ממתין לאישור פריצה"
    elif len(missing) <= 1 and rating in ("A+","A","B+"):
        decision = "WAIT"
        reason   = f"קרוב ל-BUY — חסר: {missing[0] if missing else '?'}"
    elif rating in ("B","C"):
        decision = "IGNORE"
        reason   = "לא עומד בתנאי המינימום"
    else:
        decision = "IGNORE"
        reason   = f"חסרים {len(missing)} תנאים"

    return {
        "decision":        decision,
        "rating":          rating,
        "confidence":      score,
        "reason":          reason,
        "missing":         missing[:3],
        "positives":       positives[:5],
        "score_breakdown": {
            "flow":       flow, "pre": pre, "rvol": rvol,
            "oi":         oi,   "compressed": compressed,
            "rs_1h":      rs_1h, "vol_explosion": vol_exp,
        },
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    """מריץ decide על כל המטבעות ומוסיף את התוצאה ל-coin dict."""
    for c in coins:
        result = decide(c)
        c["decision"]   = result["decision"]
        c["rating"]     = result["rating"]
        c["confidence"] = result["confidence"]
        c["reason"]     = result["reason"]
        c["missing"]    = result["missing"]
        c["positives"]  = result["positives"]
        # signal לתאימות עם שאר המערכת
        c["signal"] = {"BUY": "BUY", "WAIT": "PREPARE"}.get(result["decision"], "IGNORE")
    return coins
