"""
CRYPTO-BOT Elite — Regime Engine

השוק לא מתנהג אותו דבר כל הזמן.
הסורק מזהה את המשטר הנוכחי ומשנה משקלים אוטומטית.

Regimes:
    TRENDING_BULL  — BTC עולה חזק, אלטים עולים
    TRENDING_BEAR  — BTC יורד, כל השוק יורד
    ALTSEASON      — BTC sideways, אלטים מתפרצים
    RANGE          — שוק רגוע, אין כיוון
    RISK_OFF       — Funding קיצוני, OI גבוה, סיכון גבוה

כל משטר מקבל סט משקלים שונה ל-final_score.
"""
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)

# ─── Regime Definitions ───────────────────────────────────────────────────────

REGIMES = {
    "TRENDING_BULL": {
        "description": "BTC עולה חזק, momentum עובד",
        "weights": {"freshness":0.20,"momentum":0.35,"breakout":0.30,"pattern":0.15},
        "min_score_threshold": 58,
    },
    "ALTSEASON": {
        "description": "BTC sideways, אלטים מתפרצים",
        "weights": {"freshness":0.25,"momentum":0.25,"breakout":0.20,"pattern":0.30},
        "min_score_threshold": 55,
    },
    "RANGE": {
        "description": "שוק רגוע",
        "weights": {"freshness":0.35,"momentum":0.20,"breakout":0.25,"pattern":0.20},
        "min_score_threshold": 60,   # הוריד מ-70 ל-60
    },
    "RISK_OFF": {
        "description": "סיכון גבוה — זהירות",
        "weights": {"freshness":0.30,"momentum":0.20,"breakout":0.30,"pattern":0.20},
        "min_score_threshold": 70,   # הוריד מ-78 ל-70
    },
    "TRENDING_BEAR": {
        "description": "שוק יורד",
        "weights": {"freshness":0.25,"momentum":0.25,"breakout":0.25,"pattern":0.25},
        "min_score_threshold": 75,   # הוריד מ-85 ל-75
    },
}


# ─── Regime Detection ─────────────────────────────────────────────────────────

def detect_regime(
    btc_1h_move:  float,   # % שינוי BTC ב-1h
    btc_4h_move:  float,   # % שינוי BTC ב-4h
    btc_24h_move: float,   # % שינוי BTC ב-24h
    alt_avg_1h:   float,   # ממוצע שינוי אלטים ב-1h
    fear_greed:   int = 50,
) -> str:
    """
    מחזיר שם המשטר הנוכחי.
    """
    # TRENDING_BEAR — BTC יורד חזק
    if btc_4h_move < -4.0 or btc_24h_move < -8.0:
        log.info(f"Regime: TRENDING_BEAR (BTC 4h={btc_4h_move:.1f}%)")
        return "TRENDING_BEAR"

    # RISK_OFF — פחד קיצוני
    if fear_greed < 20:
        log.info(f"Regime: RISK_OFF (Fear&Greed={fear_greed})")
        return "RISK_OFF"

    # TRENDING_BULL — BTC עולה חזק
    if btc_4h_move > 3.0 and btc_1h_move > 0.5:
        log.info(f"Regime: TRENDING_BULL (BTC 4h={btc_4h_move:.1f}%)")
        return "TRENDING_BULL"

    # ALTSEASON — BTC flat אבל אלטים זזים
    btc_flat = abs(btc_4h_move) < 2.0
    alts_move = alt_avg_1h > btc_1h_move + 1.5
    if btc_flat and alts_move:
        log.info(f"Regime: ALTSEASON (alts={alt_avg_1h:.1f}% vs BTC={btc_1h_move:.1f}%)")
        return "ALTSEASON"

    # RANGE — ברירת מחדל
    log.info(f"Regime: RANGE (BTC 4h={btc_4h_move:.1f}%)")
    return "RANGE"


def get_regime_weights(regime: str) -> dict:
    """מחזיר משקלים לפי המשטר."""
    return REGIMES.get(regime, REGIMES["RANGE"])["weights"]


def get_min_threshold(regime: str) -> float:
    """ציון מינימלי לשליחה לטלגרם לפי המשטר."""
    return REGIMES.get(regime, REGIMES["RANGE"])["min_score_threshold"]


def calc_alt_avg(universe_sample: list[str],
                 get_move_fn) -> float:
    """
    מחשב ממוצע תנועה של מדגם אלטים.
    get_move_fn: פונקציה שמקבלת symbol ומחזירה % move
    """
    moves = []
    # מדגם של 20 מטבעות מהאמצע של ה-universe (לא BTC/ETH)
    sample = [s for s in universe_sample
              if s not in ("BTCUSDT", "ETHUSDT", "BNBUSDT")][:20]

    for sym in sample:
        try:
            m = get_move_fn(sym)
            if m != 0:
                moves.append(m)
        except Exception:
            continue

    return round(sum(moves) / len(moves), 2) if moves else 0.0
