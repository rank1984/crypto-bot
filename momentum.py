"""
CRYPTO-BOT Elite — Momentum Engine (V2)
מחשב מומנטום לפי 4 timeframes: 3m, 5m, 15m, 1h

כל ערך הוא שינוי אחוזי מה-close N נרות אחורה לעומת ה-close הנוכחי.
"""
import pandas as pd

from utils.logger import get_logger

log = get_logger(__name__)


def calc_momentum(df_1m: pd.DataFrame,
                  df_5m: pd.DataFrame,
                  df_15m: pd.DataFrame,
                  df_1h: pd.DataFrame) -> dict[str, float]:
    """
    Parameters
    ----------
    df_1m, df_5m, df_15m, df_1h : DataFrames from market_data.get_candles()

    Returns
    -------
    {
        'momentum_3m':  float,   # % change over last 3 × 1m candles
        'momentum_5m':  float,   # % change over last 1 × 5m candle
        'momentum_15m': float,   # % change over last 1 × 15m candle
        'momentum_1h':  float,   # % change over last 1 × 1h candle
    }
    All values are percentages, e.g. +2.1 means +2.1%.
    """
    result = {
        "momentum_3m":  0.0,
        "momentum_5m":  0.0,
        "momentum_15m": 0.0,
        "momentum_1h":  0.0,
    }

    def pct(df: pd.DataFrame, n_candles_back: int, key: str) -> None:
        if df is None or len(df) < n_candles_back + 1:
            log.debug(f"Not enough candles for {key}")
            return
        current = df["close"].iloc[-1]
        past    = df["close"].iloc[-(n_candles_back + 1)]
        if past == 0:
            return
        result[key] = round((current - past) / past * 100, 3)

    pct(df_1m,  3, "momentum_3m")
    pct(df_5m,  1, "momentum_5m")
    pct(df_15m, 1, "momentum_15m")
    pct(df_1h,  1, "momentum_1h")

    return result
