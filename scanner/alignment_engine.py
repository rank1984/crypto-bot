"""
CRYPTO-BOT Elite — Multi-Timeframe Alignment Engine

מחשב כמה הטיימפריימים מיושרים באותו כיוון.

מצב	                    ניקוד
כל הטווחים ירוקים	    100
5m + 15m + 1h	            85
5m + 15m בלבד	            70
5m בלבד	                50
1h נגד הכיוון	            20
כולם נגד	                0
"""
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)


def calc_alignment(
    df_5m:   pd.DataFrame,
    df_15m:  pd.DataFrame,
    df_1h:   pd.DataFrame,
    df_4h:   pd.DataFrame | None = None,
    ema_period: int = 20,
) -> dict:
    """
    מחשב alignment_score על סמך:
        1. מומנטום (close vs close N נרות אחורה)
        2. EMA slope (האם EMA עולה?)
        3. מחיר מעל EMA (בכל טיימפריים)

    Returns
    -------
    {
        "alignment_score": float,   # 0–100
        "aligned_count":   int,     # כמה TF ירוקים
        "total_tf":        int,
        "details": {
            "5m":  {"momentum": float, "above_ema": bool, "ema_rising": bool},
            "15m": {...},
            "1h":  {...},
            "4h":  {...},
        }
    }
    """
    tfs = {
        "5m":  (df_5m,  1),    # נר אחד אחורה
        "15m": (df_15m, 1),
        "1h":  (df_1h,  1),
        "4h":  (df_4h,  1),
    }

    details      = {}
    green_count  = 0
    total        = 0
    score        = 0.0

    # משקלים לפי TF — 1h ו-4h שווים יותר
    weights = {"5m": 15, "15m": 25, "1h": 35, "4h": 25}

    for tf_name, (df, n_back) in tfs.items():
        if df is None or len(df) < max(ema_period + 1, n_back + 2):
            details[tf_name] = {"momentum": 0.0, "above_ema": False, "ema_rising": False, "green": False}
            continue

        total += 1
        close = df["close"]

        # מומנטום
        mom = (float(close.iloc[-1]) - float(close.iloc[-(n_back+1)])) \
              / float(close.iloc[-(n_back+1)]) * 100

        # EMA
        ema      = close.ewm(span=ema_period, adjust=False).mean()
        above    = float(close.iloc[-1]) > float(ema.iloc[-1])
        rising   = float(ema.iloc[-1]) > float(ema.iloc[-3])

        # ירוק = לפחות 2 מ-3 תנאים
        conditions = [mom > 0, above, rising]
        green = sum(conditions) >= 2

        if green:
            green_count += 1
            score += weights.get(tf_name, 20)

        details[tf_name] = {
            "momentum":   round(mom, 3),
            "above_ema":  above,
            "ema_rising": rising,
            "green":      green,
        }

    # בונוס: כל הטיימפריימים מיושרים
    if green_count == total and total >= 3:
        score = min(100.0, score + 10)

    # מלא ניקוד אם אין 4h
    if total == 3 and df_4h is None:
        score = score / 75 * 100   # normalize ל-3 TF

    result = {
        "alignment_score": round(min(100.0, score), 1),
        "aligned_count":   green_count,
        "total_tf":        total,
        "details":         details,
    }

    log.debug(
        f"Alignment: {result['alignment_score']:.0f} "
        f"({green_count}/{total} TF green)"
    )
    return result


def alignment_summary(details: dict) -> str:
    """מחרוזת קצרה לטלגרם: ✅5m ✅15m ✅1h ❌4h"""
    icons = {True: "✅", False: "❌"}
    return "  ".join(
        f"{icons[v.get('green', False)]}{tf}"
        for tf, v in details.items()
    )
