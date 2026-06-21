"""
CRYPTO-BOT Elite — Pre-Explosion Engine

מחבר את כל הסיגנלים ומזהה שלב:
    EARLY BUILDUP     40–59  — משהו מתחיל
    WATCH CLOSELY     60–79  — תשים עין
    EXPLOSION IMMINENT 80+   — כניסה בקרוב

מחזיר:
    {
        "score":     84,
        "phase":     "EXPLOSION IMMINENT",
        "direction": "BULLISH"
    }
"""
from utils.logger import get_logger

log = get_logger(__name__)

PHASES = [
    (80, "EXPLOSION IMMINENT", "⚡"),
    (60, "WATCH CLOSELY",      "👀"),
    (40, "EARLY BUILDUP",      "🌱"),
    (0,  "NO SIGNAL",          "⚪"),
]


def calc_pre_explosion(
    flow_score:     float,
    final_score:    float,
    breakout_score: float,
    is_compressed:  bool,
    whale_detected: bool,
    cvd_trend:      float,
    oi_change:      float,
    rs_btc_1h:      float,
    momentum_15m:   float,
    vol_accel:      float,
) -> dict:
    """
    מחשב Pre-Explosion Score ומזהה שלב.

    משקלים:
        flow_score     40%  — הכי חשוב
        final_score    25%  — scoring מקצועי
        breakout_score 20%  — קרבה לפריצה
        bonuses        15%  — תנאים ספציפיים
    """
    base = (
        flow_score     * 0.40
        + final_score  * 0.25
        + breakout_score * 0.20
    )

    # בונוסים לתנאים שמחזקים את ההסתברות
    bonus = 0.0

    if is_compressed:
        bonus += 5    # קומפרסיה = אנרגיה שנצברת

    if whale_detected:
        bonus += 5    # כסף גדול נכנס לפני המהלך

    if cvd_trend > 5:
        bonus += 4    # קונים תוקפים אגרסיבית

    if oi_change > 3:
        bonus += 4    # כסף חדש נכנס לשוק

    if rs_btc_1h > 2:
        bonus += 3    # מוביל את BTC בבירור

    if momentum_15m > 2 and vol_accel > 1.5:
        bonus += 4    # מומנטום + האצה = combo

    score = round(min(100.0, base + bonus), 1)

    # Phase
    phase, emoji = "NO SIGNAL", "⚪"
    for threshold, name, em in PHASES:
        if score >= threshold:
            phase, emoji = name, em
            break

    # Direction
    bullish_signals = sum([
        cvd_trend > 0,
        oi_change > 0,
        rs_btc_1h > 0,
        momentum_15m > 0,
    ])
    direction = "BULLISH" if bullish_signals >= 3 else "NEUTRAL"

    log.debug(f"Pre-explosion: {score:.0f} ({phase}) base={base:.1f} bonus={bonus:.1f}")

    return {
        "score":     score,
        "phase":     phase,
        "emoji":     emoji,
        "direction": direction,
    }
