"""
CRYPTO-BOT Elite — Relative Strength (RS)

דירוג מטבע ביחס ל-BTC — אחד השדרוגים עם יחס תמורה/מאמץ הטובים ביותר.

הלוגיקה:
    אם BTC עלה 2% ב-1h ו-AERO עלה 5% → RS חיובי → חוזק יחסי
    אם BTC עלה 2% ב-1h ו-ETC עלה 0.5% → RS שלילי → חולשה יחסית

מחזיר:
    rs_1h:   float   # % יחסי ל-BTC ב-1h
    rs_4h:   float   # % יחסי ל-BTC ב-4h (4 נרות 1h)
    rs_score: float  # 0–100
"""
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)

# BTC reference — מתעדכן ברמת הסריקה כדי לא להוריד פעמים רבות
_btc_cache: dict = {}


def set_btc_reference(df_1h: pd.DataFrame) -> None:
    """
    קורא פעם אחת לפני הסריקה עם נרות BTC.
    שומר ב-cache לכל הסריקה הנוכחית.
    """
    global _btc_cache
    if df_1h is None or df_1h.empty:
        return

    close = df_1h["close"]
    _btc_cache = {
        "1h":  _pct_change(close, 1),
        "4h":  _pct_change(close, 4),
        "12h": _pct_change(close, 12),
    }
    log.debug(f"BTC reference: 1h={_btc_cache['1h']:+.2f}% 4h={_btc_cache['4h']:+.2f}%")


def _pct_change(series: pd.Series, n: int) -> float:
    if len(series) < n + 1:
        return 0.0
    current = float(series.iloc[-1])
    past    = float(series.iloc[-(n + 1)])
    return round((current - past) / past * 100, 3) if past != 0 else 0.0


def calc_relative_strength(df_1h: pd.DataFrame) -> dict[str, float]:
    """
    מחשב חוזק יחסי של מטבע ביחס ל-BTC.

    Parameters
    ----------
    df_1h : 1h candles של המטבע

    Returns
    -------
    {
        'rs_1h':   float,   # חוזק יחסי 1h (חיובי = חזק מ-BTC)
        'rs_4h':   float,   # חוזק יחסי 4h
        'rs_score': float,  # 0–100
    }
    """
    if not _btc_cache:
        return {"rs_1h": 0.0, "rs_4h": 0.0, "rs_score": 50.0}

    if df_1h is None or df_1h.empty:
        return {"rs_1h": 0.0, "rs_4h": 0.0, "rs_score": 50.0}

    close = df_1h["close"]
    coin_1h  = _pct_change(close, 1)
    coin_4h  = _pct_change(close, 4)

    rs_1h = round(coin_1h  - _btc_cache.get("1h",  0), 3)
    rs_4h = round(coin_4h  - _btc_cache.get("4h",  0), 3)

    # RS Score: 50 = inline with BTC, 100 = מאוד חזק, 0 = מאוד חלש
    # sigmoid centred at 0, ±5% = extreme
    import math
    def sig(x: float) -> float:
        return 100 / (1 + math.exp(-0.4 * x))

    rs_score = round((sig(rs_1h) * 0.5 + sig(rs_4h) * 0.5), 1)

    return {
        "rs_1h":    rs_1h,
        "rs_4h":    rs_4h,
        "rs_score": rs_score,
    }
