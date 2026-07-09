"""
CRYPTO-BOT Elite — Probability Engine
מחשב הסתברות לפריצה בחלון זמן קרוב ומדרג את איכות הסטאפ.
"""
import os
from utils.logger import get_logger

log = get_logger(__name__)

_DEFAULT_WEIGHTS = {
    "flow":        0.25,
    "oi":          0.20,
    "compression": 0.15,
    "rvol":        0.15,
    "rs":          0.15,
    "momentum":    0.10
}

def calc_probability(coin: dict) -> dict:
    """
    מחשב הסתברות וציון איכות (0-100) לפריצה קרובה.
    """
    w = _DEFAULT_WEIGHTS
    
    flow       = coin.get("flow_score", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False) or coin.get("squeeze_detected", False)
    rvol       = coin.get("rvol", 0)
    rs         = coin.get("rs_1h", 0)
    momentum   = coin.get("momentum_1h", 0)
    whale      = coin.get("whale_detected", False) or coin.get("whale_activity", False)
    vol_exp    = coin.get("vol_explosion", False)
    streak     = coin.get("watchlist_streak", 0)

    # נרמול מדדים לערכים של 0 עד 1
    f_flow  = min(1.0, flow / 100)
    f_oi    = min(1.0, max(0, oi) / 10)       # 10% ומעלה = מקסימום
    f_comp  = 1.0 if compressed else 0.0
    f_rvol  = min(1.0, rvol / 2.0)            # RVOL של 2x = מקסימום
    f_rs    = min(1.0, max(0, rs) / 4.0)      # חוזק מול ביטקוין של 4% = מקסימום
    f_mom   = min(1.0, max(0, momentum) / 3.0) # מומנטום של 3% = מקסימום

    # חישוב הציון הבסיסי המשוקלל
    score_raw = (
        f_flow  * w["flow"] +
        f_oi    * w["oi"] +
        f_comp  * w["compression"] +
        f_rvol  * w["rvol"] +
        f_rs    * w["rs"] +
        f_mom   * w["momentum"]
    )
    ai_score = round(min(100, score_raw * 100), 1)

    # הוספת בונוסים דינמיים של פעילות חריגה
    prob = ai_score
    if whale:   prob = min(100, prob + 5)
    if vol_exp: prob = min(100, prob + 7)
    if streak >= 5:  prob = min(100, prob + 6)
    elif streak >= 2: prob = min(100, prob + 3)
    
    prob = round(prob, 1)

    # קביעת זמן משוער לפריצה (ETA)
    if prob >= 75:   eta = "15-45 דקות"
    elif prob >= 60: eta = "1-3 שעות"
    elif prob >= 45: eta = "היום / הקרוב"
    else:            eta = "בבנייה"

    # סטטוס
    if prob >= 75 and oi > 0 and compressed:
        status = "PRE_BREAKOUT"
    elif prob >= 55:
        status = "BUILDING"
    else:
        status = "EARLY"

    return {
        "probability": prob,
        "ai_score":    ai_score,
        "eta":         eta,
        "status":      status
    }
