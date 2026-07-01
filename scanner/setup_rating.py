"""
CRYPTO-BOT Elite — Setup Rating

במקום BUY/WATCH — דירוג A+/A/B/B+/C.

A+ = הכל מושלם, הכנס מלא
A  = חזק מאוד, כנס
B+ = טוב, כנס חצי
B  = בינוני, WATCH
C  = חלש, התעלם
"""
from utils.logger import get_logger

log = get_logger(__name__)


def rate_setup(coin: dict) -> tuple[str, int, list[str]]:
    """
    מחזיר (rating, confidence_0_100, reasons).

    A+ = 90+
    A  = 75-89
    B+ = 60-74
    B  = 45-59
    C  = <45
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

    score = 0
    reasons = []

    # Flow (35 נקודות)
    if flow >= 75:
        score += 35; reasons.append("Flow מצוין")
    elif flow >= 60:
        score += 25; reasons.append("Flow חזק")
    elif flow >= 45:
        score += 15; reasons.append("Flow בינוני")
    else:
        reasons.append("Flow חלש")

    # Pre-Breakout (25 נקודות)
    if pre >= 70:
        score += 25; reasons.append("Pre-Breakout מצוין")
    elif pre >= 55:
        score += 18; reasons.append("Pre-Breakout חזק")
    elif pre >= 40:
        score += 10; reasons.append("Pre-Breakout בינוני")

    # Volume (15 נקודות)
    if vol_exp:
        score += 15; reasons.append("💥 פיצוץ נפח")
    elif rvol >= 2.0:
        score += 12; reasons.append(f"RVOL גבוה ({rvol:.1f}x)")
    elif rvol >= 1.2:
        score += 7

    # OI + Compression (15 נקודות)
    if oi > 5 and compressed:
        score += 15; reasons.append("OI + Compression")
    elif oi > 2:
        score += 8; reasons.append(f"OI עולה {oi:+.1f}%")
    if compressed and oi <= 2:
        score += 7; reasons.append("Compression")

    # RS + Whale (10 נקודות)
    if rs_1h > 1.5:
        score += 7; reasons.append(f"RS חזק מ-BTC +{rs_1h:.1f}%")
    elif rs_1h > 0:
        score += 3
    if whale:
        score += 3; reasons.append("פעילות לווייתנים")

    # Entry bonus (5 נקודות)
    if entry_dec == "BUY":
        score += 5

    # Regime penalty
    if regime == "TRENDING_BEAR":
        score = int(score * 0.7)
    elif regime == "RISK_OFF":
        score = int(score * 0.85)

    score = min(100, max(0, score))

    if score >= 90:   rating = "A+"
    elif score >= 75: rating = "A"
    elif score >= 60: rating = "B+"
    elif score >= 45: rating = "B"
    else:             rating = "C"

    return rating, score, reasons


def rating_emoji(rating: str) -> str:
    return {"A+": "🟢", "A": "🟢", "B+": "🟡", "B": "🟡", "C": "⚪"}.get(rating, "⚪")


def should_send(rating: str, regime: str) -> bool:
    """האם לשלוח התראה לפי דירוג ו-regime?"""
    if regime in ("TRENDING_BEAR", "RISK_OFF"):
        return rating == "A+"
    if regime == "RANGE":
        return rating in ("A+", "A", "B+")
    return rating in ("A+", "A", "B+", "B")
