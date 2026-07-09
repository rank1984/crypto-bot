"""
CRYPTO-BOT Elite — Decision Engine

מנוע מרכזי שמנהל את רמות הפעולה (BUY NOW / PREPARE / WATCH / IGNORE)
ומכין את הנתונים והסיבות עבור ה-Telegram Assistant.
"""
from utils.logger import get_logger
from scanner.probability_engine import enrich_with_probability

log = get_logger(__name__)


# ─── Thresholds per Regime (Legacy Compatibility) ─────────────────────────────

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


# ─── Core Decision (Legacy / Fallback) ────────────────────────────────────────

def decide(coin: dict) -> dict:
    """
    החלטה קלאסית עבור מטבע בודד — נשמרת לטובת תאימות לאחור במערכת.
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
    
    # הזרקת ה-RVOL הנדרש למניעת קריסות בגרסאות ישנות
    coin["required_rvol"] = thr["rvol"]

    # חישוב ציון בסיסי
    score = 0
    if flow >= 75: score += 35
    elif flow >= 60: score += 25
    elif flow >= 45: score += 15
    elif flow >= 30: score += 7

    if pre >= 70: score += 25
    elif pre >= 55: score += 18
    elif pre >= 40: score += 10
    elif pre >= 25: score += 5

    if vol_exp:       score += 15
    elif rvol >= 2.0: score += 12
    elif rvol >= 1.2: score += 7
    elif rvol >= 0.8: score += 3

    if oi > 5 and compressed: score += 15
    elif oi > 2:               score += 8
    if compressed and oi <= 2: score += 7

    if rs_1h > 1.5:   score += 7
    elif rs_1h > 0:   score += 3
    if whale:         score += 3

    if entry_dec == "BUY": score += 5
    if catalyst:           score += 5

    multipliers = {"TRENDING_BULL": 1.0, "ALTSEASON": 1.05, "RANGE": 1.0, "RISK_OFF": 0.85, "TRENDING_BEAR": 0.70}
    score = min(100, int(score * multipliers.get(regime, 1.0)))

    if score >= 90:   rating = "A+"
    elif score >= 75: rating = "A"
    elif score >= 60: rating = "B+"
    elif score >= 45: rating = "B"
    else:             rating = "C"

    positives = []
    if vol_exp:        positives.append("💥 פיצוץ נפח")
    if flow >= 60:     positives.append(f"Flow חזק ({flow:.0f})")
    if oi > 2:         positives.append(f"OI עולה {oi:+.1f}%")
    if compressed:     positives.append("Compression")
    if rs_1h > 0.5:    positives.append(f"חזק מ-BTC {rs_1h:+.1f}%")

    missing = []
    if flow < thr["flow"]: missing.append(f"Flow מעל {thr['flow']}")
    if oi <= 1:           missing.append("OI חיובי")
    if rvol < thr["rvol"]: missing.append(f"RVOL מעל {thr['rvol']}")

    return {
        "decision": "BUY" if (flow >= thr["flow"] and rvol >= thr["rvol"] and entry_dec == "BUY") else "IGNORE",
        "rating": rating,
        "confidence": score,
        "reason": "Legacy output",
        "missing": missing[:3],
        "positives": positives[:5],
        "score_breakdown": {"flow": flow, "pre": pre, "rvol": rvol, "oi": oi, "compressed": compressed, "rs_1h": rs_1h},
    }


# ─── Advanced Batch Processing (Telegram v6 Ecosystem) ───────────────────────

def decide_batch(coins: list[dict]) -> list[dict]:
    """
    מריץ את מנוע ההסתברויות המתקדם, מסדר את הדירוגים (Rank),
    ומחלק ל-4 רמות פעולה ברורות לטריידר.
    """
    if not coins:
        return []

    # 1. מעשירים את המטבעות וממיינים לפי הציון המשוקלל של ה-AI Score
    coins = enrich_with_probability(coins)
    total_count = len(coins)
    
    for i, c in enumerate(coins, 1):
        # עדכון מבנה הדירוג בדיוק כפי ש-sender.py v6 מצפה לקבל
        c["rank"] = i
        c["rank_total"] = total_count
        
        ai_score = c.get("ai_score", 0)
        entry_dec = c.get("entry_decision", "NO")
        
        # 2. קביעת 4 רמות הפעולה (Decision Levels)
        if ai_score >= 80 and entry_dec == "BUY":
            c["decision"] = "BUY NOW"
            c["signal"] = "BUY"
        elif ai_score >= 70:
            c["decision"] = "PREPARE"
            c["signal"] = "PREPARE"
        elif ai_score >= 55:
            c["decision"] = "WATCH"
            c["signal"] = "WATCH"
        else:
            c["decision"] = "IGNORE"
            c["signal"] = "IGNORE"
            
        # 3. בניית הטיעונים החיוביים והשליליים (Reasons) בצורה דינמית
        pos = []
        neg = []
        
        # בדיקת חיוביים
        if c.get("is_compressed"): 
            pos.append("Compression")
        if c.get("flow_score", 0) >= 60: 
            pos.append("Flow גבוה")
        if c.get("rs_1h", 0) > 0.5: 
            pos.append("RS חיובי")
        if c.get("vol_explosion"): 
            pos.append("פיצוץ נפח")
        if c.get("whale_detected"): 
            pos.append("פעילות לווייתנים")

        # בדיקת שליליים / חסרים
        if c.get("oi_change", 0) <= 0: 
            neg.append("OI עדיין שלילי")
        if entry_dec != "BUY": 
            neg.append("אין Trigger")
        if c.get("rvol", 0) < 1.1: 
            neg.append("RVOL עדיין בינוני")
        elif c.get("rvol", 0) < 0.8:
            neg.append("RVOL נמוך")
            
        # הגבלת כמות הסיבות כדי לשמור על הודעה נקייה וקריאה
        c["pos_reasons"] = pos[:3]
        c["neg_reasons"] = neg[:2] if neg else ["כל התנאים ההכרחיים התקיימו"]
            
    return coins
