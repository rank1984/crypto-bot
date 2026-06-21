"""
CRYPTO-BOT Elite — Position Engine + Runner Engine

Position Engine:
    כמה לקנות לפי Confidence + Risk + Regime

Runner Engine:
    לא למכור ב-10%. לתת למנצחים לרוץ.
    TP1 = להחזיר סיכון (25%)
    TP2 = למכור חלק (25%)
    TP3 = trailing stop על 50% הנותרים → 20%-300%+
"""
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Position Sizing ──────────────────────────────────────────────────────────

POSITION_TABLE = [
    (90, "גבוהה מאוד", 0.05),   # 5% מהתיק
    (80, "גבוהה",      0.03),   # 3%
    (70, "בינונית",    0.02),   # 2%
    (60, "נמוכה",      0.01),   # 1%
    (0,  "מינימלית",   0.005),  # 0.5%
]

REGIME_MULTIPLIER = {
    "TRENDING_BULL": 1.0,
    "ALTSEASON":     1.0,
    "RANGE":         0.75,
    "RISK_OFF":      0.5,
    "TRENDING_BEAR": 0.25,
}


def calc_position(
    final_score:  float,
    pre_score:    float,
    flow_score:   float,
    regime:       str,
    portfolio_usd: float = 1000.0,
) -> dict:
    """
    מחשב גודל פוזיציה.

    Confidence = ממוצע משוקלל של הציונים.
    מחזיר:
    {
        "confidence":     float,    # 0–100
        "confidence_label": str,
        "pct_of_portfolio": float,  # 0.01 = 1%
        "usd_amount":     float,
        "rationale":      str,
    }
    """
    # Confidence = ממוצע עם משקל גדול יותר ל-pre_score
    confidence = round(
        final_score * 0.35
        + pre_score  * 0.40
        + flow_score * 0.25,
        1
    )

    # בסיס לפי confidence
    base_pct = 0.005
    conf_label = "מינימלית"
    for threshold, label, pct in POSITION_TABLE:
        if confidence >= threshold:
            base_pct   = pct
            conf_label = label
            break

    # מכפיל לפי regime
    mult    = REGIME_MULTIPLIER.get(regime, 0.75)
    final_pct = round(base_pct * mult, 4)
    usd_amt   = round(portfolio_usd * final_pct, 2)

    rationale = (
        f"Confidence {confidence:.0f} ({conf_label}) × "
        f"Regime {mult:.0f}x = {final_pct*100:.1f}% מהתיק"
    )

    return {
        "confidence":        confidence,
        "confidence_label":  conf_label,
        "pct_of_portfolio":  final_pct,
        "usd_amount":        usd_amt,
        "rationale":         rationale,
    }


# ─── Runner Engine ────────────────────────────────────────────────────────────

def calc_runner_exits(
    entry:      float,
    sl:         float,
    atr:        float,
    pre_score:  float,
) -> dict:
    """
    מחשב יעדים לפי Runner philosophy:
        TP1 (25%) — להחזיר סיכון, גם אם המהלך ימשיך
        TP2 (25%) — יעד ביניים סביר
        TP3 (50%) — Trailing Stop, מטרה 20%-300%+

    ככל שה-pre_score גבוה יותר — יעדי TP2/TP3 גבוהים יותר.
    """
    if entry <= 0 or sl >= entry:
        return {}

    risk_pct = (entry - sl) / entry   # % סיכון

    # TP1: 1.5× הסיכון — מספיק להחזיר ולהישאר חינם בשוק
    tp1 = round(entry * (1 + risk_pct * 1.5), 8)

    # TP2: תלוי ב-pre_score
    if pre_score >= 80:
        tp2_mult = 5.0    # pre_score גבוה = ציפייה למהלך גדול
    elif pre_score >= 60:
        tp2_mult = 3.5
    else:
        tp2_mult = 2.5
    tp2 = round(entry * (1 + risk_pct * tp2_mult), 8)

    # TP3: Trailing Stop — מטרה שאפתנית
    if pre_score >= 80:
        tp3_target = round(entry * 1.50, 8)   # +50% יעד
        trail_pct  = round(risk_pct * 4 * 100, 2)
    elif pre_score >= 60:
        tp3_target = round(entry * 1.30, 8)   # +30%
        trail_pct  = round(risk_pct * 3 * 100, 2)
    else:
        tp3_target = round(entry * 1.20, 8)   # +20%
        trail_pct  = round(risk_pct * 2 * 100, 2)

    risk_pct_display  = round(risk_pct * 100, 2)
    tp1_pct = round((tp1 - entry) / entry * 100, 1)
    tp2_pct = round((tp2 - entry) / entry * 100, 1)
    tp3_pct = round((tp3_target - entry) / entry * 100, 1)

    rr = round((tp1 - entry) / (entry - sl), 2) if entry > sl else 0

    return {
        "tp1":          tp1,
        "tp2":          tp2,
        "tp3_target":   tp3_target,
        "trail_pct":    trail_pct,
        "sl":           sl,
        "risk_pct":     risk_pct_display,
        "tp1_pct":      tp1_pct,
        "tp2_pct":      tp2_pct,
        "tp3_pct":      tp3_pct,
        "rr":           rr,
        "tp1_size":     "25%",
        "tp2_size":     "25%",
        "tp3_size":     "50% + Trailing",
    }


# ─── Fakeout Risk ─────────────────────────────────────────────────────────────

def assess_fakeout_risk(
    rvol:        float,
    vwap_dist:   float,
    rsi:         float,
    flow_score:  float,
    is_compressed: bool,
) -> tuple[str, str]:
    """
    מחזיר (risk_level, emoji).
    "נמוך" / "בינוני" / "גבוה"
    """
    risk_score = 0

    if rvol > 15 and flow_score < 40:  risk_score += 3   # RVOL spike ללא flow
    if rsi > 75:                        risk_score += 2
    if abs(vwap_dist) > 4:             risk_score += 2
    if not is_compressed:              risk_score += 1

    if risk_score >= 5:   return "גבוה",  "🔴"
    if risk_score >= 3:   return "בינוני","🟡"
    return "נמוך", "🟢"
