"""
CRYPTO-BOT Elite — Indicators (V3)
מחשב אינדיקטורים טכניים על ה-5m / 1h DataFrames.

פלט:
    vwap, vwap_dist (% מהמחיר)
    ema20, ema50, ema200
    rsi_14
    atr_14
"""
import pandas as pd
import numpy as np

from utils.logger import get_logger

log = get_logger(__name__)


# ─── VWAP ─────────────────────────────────────────────────────────────────────

def calc_vwap(df: pd.DataFrame) -> float:
    """
    Rolling session VWAP on the provided DataFrame.
    Uses all candles as the session (reset per scan).
    """
    tp  = (df["high"] + df["low"] + df["close"]) / 3   # typical price
    vol = df["volume"]
    cumvol = vol.cumsum()
    if cumvol.iloc[-1] == 0:
        return float(df["close"].iloc[-1])
    return float((tp * vol).cumsum().iloc[-1] / cumvol.iloc[-1])


# ─── EMA ──────────────────────────────────────────────────────────────────────

def calc_ema(df: pd.DataFrame, period: int) -> float:
    """EMA of close over `period` candles."""
    if len(df) < period:
        return float(df["close"].iloc[-1])
    return float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1])


# ─── RSI ──────────────────────────────────────────────────────────────────────

def calc_rsi(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 50.0
    delta  = df["close"].diff().dropna()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l  = loss.ewm(alpha=1/period, adjust=False).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    rsi    = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


# ─── ATR ──────────────────────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    tr    = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return round(float(atr.iloc[-1]), 8)


# ─── Main entry point ─────────────────────────────────────────────────────────

def calc_indicators(df_5m: pd.DataFrame,
                    df_1h: pd.DataFrame) -> dict[str, float]:
    """
    Parameters
    ----------
    df_5m : 5m candle DataFrame  (VWAP, EMA, RSI, ATR)
    df_1h : 1h candle DataFrame  (EMA200 — needs more history)

    Returns
    -------
    {
        'vwap':      float,
        'vwap_dist': float,   # % above/below VWAP (+2.1 = 2.1% above)
        'ema20':     float,
        'ema50':     float,
        'ema200':    float,   # computed on 1h for better signal
        'rsi_14':    float,
        'atr_14':    float,
    }
    """
    result = {
        "vwap": 0.0, "vwap_dist": 0.0,
        "ema20": 0.0, "ema50": 0.0, "ema200": 0.0,
        "rsi_14": 50.0, "atr_14": 0.0,
    }

    if df_5m is None or df_5m.empty:
        return result

    last_price = float(df_5m["close"].iloc[-1])

    vwap = calc_vwap(df_5m)
    result["vwap"] = round(vwap, 8)
    if vwap > 0:
        result["vwap_dist"] = round((last_price - vwap) / vwap * 100, 3)

    result["ema20"]  = round(calc_ema(df_5m, 20),  8)
    result["ema50"]  = round(calc_ema(df_5m, 50),  8)
    result["ema200"] = round(calc_ema(df_1h or df_5m, 200), 8)

    result["rsi_14"] = calc_rsi(df_5m)
    result["atr_14"] = calc_atr(df_5m)

    return result
