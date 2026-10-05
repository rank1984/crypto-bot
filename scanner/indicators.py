"""
scanner/indicators.py
Technical indicators – RSI, VWAP, EMA, ATR (5m and 1h).
"""

import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


def calc_rsi(df: pd.DataFrame, period: int = 14) -> float:
    if df is None or len(df) < period + 1:
        return 50.0
    close = df["close"].values
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_vwap(df: pd.DataFrame) -> float:
    if df is None or len(df) < 2:
        return 0.0
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].values
    if vol.sum() == 0:
        return float(df["close"].iloc[-1])
    vwap = (tp * vol).sum() / vol.sum()
    return round(float(vwap), 6)


def calc_ema(df: pd.DataFrame, period: int = 20) -> float:
    if df is None or len(df) < period:
        return 0.0
    close = df["close"]
    ema = close.ewm(span=period, adjust=False).mean()
    return round(float(ema.iloc[-1]), 6)


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range."""
    if df is None or len(df) < period:
        return 0.0
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tr = np.zeros(len(high))
    for i in range(1, len(high)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.mean(tr[-period:])
    return round(float(atr), 6)


def calc_indicators(df_5m: pd.DataFrame, df_1h: pd.DataFrame = None) -> dict:
    """
    Calculate all indicators.
    Returns dict with rsi_14, vwap, vwap_dist, ema20, ema50, atr_14, atr_1h.
    """
    last_price = float(df_5m["close"].iloc[-1]) if df_5m is not None and len(df_5m) > 0 else 0

    rsi_14 = calc_rsi(df_5m, period=14)
    vwap = calc_vwap(df_5m)
    vwap_dist = ((last_price - vwap) / vwap * 100) if vwap > 0 else 0.0
    ema20 = calc_ema(df_5m, period=20)
    ema50 = calc_ema(df_5m, period=50)
    atr_14 = calc_atr(df_5m, period=14)

    # 🆕 1h ATR (for proper stop sizing)
    atr_1h = calc_atr(df_1h, period=14) if df_1h is not None and len(df_1h) >= 14 else 0.0

    return {
        "rsi_14": rsi_14,
        "vwap": vwap,
        "vwap_dist": round(vwap_dist, 3),
        "ema20": ema20,
        "ema50": ema50,
        "atr_14": atr_14,
        "atr_1h": atr_1h,   # 🆕
    }