"""
scanner/multiday_features.py
Multi-Day Feature Engine – calculates trend, RS, volume, structure, exhaustion.
Only uses closed candles – no look-ahead.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger("multiday_features")


def calculate_trend(df: pd.DataFrame, lookback: int = 14) -> dict:
    """
    Calculate trend strength and direction from 1D/4H candles.
    Returns: trend_strength (-1 to 1), trend_1d, trend_4h, higher_highs/lows.
    """
    if df is None or len(df) < lookback:
        return {
            "trend_strength": 0.0,
            "trend_1d": 0.0,
            "trend_4h": 0.0,
            "higher_highs": 0,
            "higher_lows": 0
        }

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    # Simple linear regression slope (normalized by price)
    x = np.arange(len(close))
    slope = np.polyfit(x, close, 1)[0]
    trend_1d = slope / close[-1] * 100  # % change per day

    # 4H trend (last 4 periods)
    if len(close) >= 4:
        short_slope = np.polyfit(x[-4:], close[-4:], 1)[0]
        trend_4h = short_slope / close[-1] * 100
    else:
        trend_4h = 0.0

    # Higher highs / higher lows (last 20 periods)
    higher_highs = sum(1 for i in range(1, min(20, len(high))) if high[-i] > high[-i-1])
    higher_lows = sum(1 for i in range(1, min(20, len(low))) if low[-i] > low[-i-1])

    # Trend strength (normalized)
    trend_strength = np.clip(trend_1d / 5, -1, 1) if abs(trend_1d) > 0 else 0

    return {
        "trend_strength": round(trend_strength, 3),
        "trend_1d": round(trend_1d, 2),
        "trend_4h": round(trend_4h, 2),
        "higher_highs": higher_highs,
        "higher_lows": higher_lows
    }


def calculate_relative_strength(df_symbol: pd.DataFrame, df_btc: pd.DataFrame, lookback: int = 14) -> dict:
    """
    Calculate RS vs BTC for 1D and 4H.
    """
    if df_symbol is None or df_btc is None or len(df_symbol) < lookback or len(df_btc) < lookback:
        return {"rs_1d": 0.0, "rs_4h": 0.0}

    # 1D return
    sym_ret_1d = (df_symbol["close"].iloc[-1] / df_symbol["close"].iloc[-lookback] - 1) * 100
    btc_ret_1d = (df_btc["close"].iloc[-1] / df_btc["close"].iloc[-lookback] - 1) * 100
    rs_1d = sym_ret_1d - btc_ret_1d

    # 4H return (last 4 periods)
    if len(df_symbol) >= 4 and len(df_btc) >= 4:
        sym_ret_4h = (df_symbol["close"].iloc[-1] / df_symbol["close"].iloc[-4] - 1) * 100
        btc_ret_4h = (df_btc["close"].iloc[-1] / df_btc["close"].iloc[-4] - 1) * 100
        rs_4h = sym_ret_4h - btc_ret_4h
    else:
        rs_4h = 0.0

    return {
        "rs_1d": round(rs_1d, 2),
        "rs_4h": round(rs_4h, 2)
    }


def calculate_volume_features(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Volume expansion, contraction, relative volume, breakout ratio.
    """
    if df is None or len(df) < lookback:
        return {
            "volume_expansion": 0.0,
            "volume_contraction": 0.0,
            "relative_volume": 1.0,
            "volume_breakout_ratio": 1.0
        }

    vol = df["volume"].values
    avg_vol = np.mean(vol[-lookback:-1]) if len(vol) > lookback else np.mean(vol)
    last_vol = vol[-1] if len(vol) > 0 else 0
    prev_vol = vol[-2] if len(vol) > 1 else last_vol

    relative_vol = last_vol / avg_vol if avg_vol > 0 else 1.0
    volume_expansion = relative_vol - 1.0  # >0 = expansion, <0 = contraction

    # Volume contraction in pullback
    last_5_avg = np.mean(vol[-5:]) if len(vol) >= 5 else last_vol
    prev_5_avg = np.mean(vol[-10:-5]) if len(vol) >= 10 else avg_vol
    volume_contraction = 1 - (last_5_avg / prev_5_avg) if prev_5_avg > 0 else 0

    # Breakout ratio: volume spike relative to recent highs
    max_vol_20 = np.max(vol[-lookback:]) if len(vol) >= lookback else avg_vol
    volume_breakout_ratio = last_vol / max_vol_20 if max_vol_20 > 0 else 1.0

    return {
        "volume_expansion": round(volume_expansion, 3),
        "volume_contraction": round(volume_contraction, 3),
        "relative_volume": round(relative_vol, 2),
        "volume_breakout_ratio": round(volume_breakout_ratio, 2)
    }


def calculate_structure(df: pd.DataFrame, lookback: int = 30) -> dict:
    """
    Identify resistance, breakout level, distance from breakout, recent high, consolidation range.
    """
    if df is None or len(df) < lookback:
        return {
            "resistance": 0.0,
            "breakout_level": 0.0,
            "distance_from_breakout": 0.0,
            "distance_from_recent_high": 0.0,
            "consolidation_range": 0.0,
            "pullback_depth": 0.0
        }

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    last_close = close[-1]

    # Recent resistance (highest high in last 20 periods)
    resistance = np.max(high[-20:]) if len(high) >= 20 else np.max(high)
    breakout_level = resistance  # simple definition

    # Distance from breakout (relative to ATR)
    atr = calculate_atr(df, period=14)
    if atr > 0:
        distance_from_breakout = (last_close - breakout_level) / atr
    else:
        distance_from_breakout = 0.0

    # Distance from recent high
    recent_high = np.max(high[-10:]) if len(high) >= 10 else np.max(high)
    distance_from_recent_high = (recent_high - last_close) / atr if atr > 0 else 0.0

    # Consolidation range (high-low over last 10 periods)
    range_10 = (np.max(high[-10:]) - np.min(low[-10:])) if len(high) >= 10 else 0
    consolidation_range = range_10 / last_close * 100 if last_close > 0 else 0

    # Pullback depth (from recent high)
    pullback_depth = (recent_high - last_close) / last_close * 100 if last_close > 0 else 0

    return {
        "resistance": round(resistance, 4),
        "breakout_level": round(breakout_level, 4),
        "distance_from_breakout": round(distance_from_breakout, 2),
        "distance_from_recent_high": round(distance_from_recent_high, 2),
        "consolidation_range": round(consolidation_range, 2),
        "pullback_depth": round(pullback_depth, 2)
    }


def calculate_momentum(df: pd.DataFrame) -> dict:
    """
    Returns: return_4h, return_24h, return_48h, return_72h.
    """
    if df is None or len(df) < 4:
        return {"return_4h": 0.0, "return_24h": 0.0, "return_48h": 0.0, "return_72h": 0.0}

    close = df["close"].values
    last_close = close[-1]

    ret_4h = (last_close / close[-4] - 1) * 100 if len(close) >= 4 else 0
    ret_24h = (last_close / close[-24] - 1) * 100 if len(close) >= 24 else (last_close / close[0] - 1) * 100
    ret_48h = (last_close / close[-48] - 1) * 100 if len(close) >= 48 else 0
    ret_72h = (last_close / close[-72] - 1) * 100 if len(close) >= 72 else 0

    return {
        "return_4h": round(ret_4h, 2),
        "return_24h": round(ret_24h, 2),
        "return_48h": round(ret_48h, 2),
        "return_72h": round(ret_72h, 2)
    }


def calculate_exhaustion(df: pd.DataFrame, features: dict) -> float:
    """
    Exhaustion score (0-100). Higher = more exhausted.
    Based on: recent returns, distance from breakout, volume divergence.
    """
    score = 0

    # 24h return > 15% → high exhaustion
    ret_24 = features.get("return_24h", 0)
    if ret_24 > 15:
        score += 30
    elif ret_24 > 8:
        score += 15
    elif ret_24 > 3:
        score += 5

    # Distance from breakout > 4 ATR → high exhaustion
    dist = features.get("distance_from_breakout", 0)
    if dist > 4:
        score += 25
    elif dist > 2:
        score += 10

    # Volume contraction after expansion (possible climax)
    vol_exp = features.get("volume_expansion", 0)
    vol_cont = features.get("volume_contraction", 0)
    if vol_exp > 1.0 and vol_cont > 0.3:
        score += 20

    # Pullback depth > 10% after strong trend → potential exhaustion
    if features.get("pullback_depth", 0) > 10:
        score += 15

    # Consolidation range > 15% → high volatility (exhaustion)
    if features.get("consolidation_range", 0) > 15:
        score += 10

    return min(100, score)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
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
    return round(atr, 4)


def compute_all_features(df_1d: pd.DataFrame, df_4h: pd.DataFrame, df_btc_1d: pd.DataFrame, df_btc_4h: pd.DataFrame) -> dict:
    """Aggregate all features into a single dict."""
    features = {}

    # Trend
    features.update(calculate_trend(df_1d, lookback=14))
    features.update(calculate_trend(df_4h, lookback=14))

    # RS
    features.update(calculate_relative_strength(df_1d, df_btc_1d, lookback=14))
    features.update(calculate_relative_strength(df_4h, df_btc_4h, lookback=14))

    # Volume
    features.update(calculate_volume_features(df_1d, lookback=20))

    # Structure
    features.update(calculate_structure(df_1d, lookback=30))

    # Momentum
    features.update(calculate_momentum(df_4h))

    # ATR (4H)
    features["atr_4h"] = calculate_atr(df_4h, period=14)
    features["atr_1d"] = calculate_atr(df_1d, period=14)

    # Exhaustion
    features["exhaustion_score"] = calculate_exhaustion(df_4h, features)

    # Stage (EARLY/DEVELOPING/LATE/EXHAUSTED)
    return features
