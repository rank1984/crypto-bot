"""
CRYPTO-BOT Elite — Market Data
מוריד נרות מ-Binance עם caching לפי timeframe.

מחזיר DataFrame עם עמודות:
    open_time, open, high, low, close, volume,
    close_time, quote_volume, trades
"""
import time
from typing import Optional

import pandas as pd
import requests

from utils.cache import load as cache_load, save as cache_save
from utils.config import BINANCE_BASE_URL, CANDLES_PER_TF, TIMEFRAMES
from utils.logger import get_logger

log = get_logger(__name__)

# Binance klines column names
_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "_ignore",
]

# Rate-limit: short sleep between requests when cache misses pile up
_REQUEST_DELAY = 0.05   # 50 ms → ≈ 20 req/s, well within Binance 1200 req/min


def _fetch_klines(symbol: str, interval: str, limit: int) -> Optional[list]:
    """Raw Binance klines request. Returns list of rows or None on error."""
    try:
        resp = requests.get(
            f"{BINANCE_BASE_URL}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"klines error {symbol}/{interval}: {e}")
        return None


def _to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=_COLS)
    df = df[["open_time", "open", "high", "low", "close", "volume",
             "close_time", "quote_volume", "trades"]]
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)
    df["open_time"]  = pd.to_datetime(df["open_time"],  unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def get_candles(symbol: str, interval: str,
                limit: int = CANDLES_PER_TF) -> Optional[pd.DataFrame]:
    """
    Returns a DataFrame of the last `limit` candles for symbol/interval.
    Uses file cache; fetches from Binance only when cache is stale.
    """
    cached = cache_load(symbol, interval)
    if cached is not None:
        return _to_df(cached)

    raw = _fetch_klines(symbol, interval, limit)
    if raw is None:
        return None

    cache_save(symbol, interval, raw)
    time.sleep(_REQUEST_DELAY)   # be polite to Binance
    return _to_df(raw)


def get_all_timeframes(symbol: str) -> dict[str, pd.DataFrame]:
    """
    Convenience: returns {tf: DataFrame} for all configured timeframes.
    Missing timeframes are omitted from the dict.
    """
    result = {}
    for tf in TIMEFRAMES:
        df = get_candles(symbol, tf)
        if df is not None:
            result[tf] = df
    return result


if __name__ == "__main__":
    dfs = get_all_timeframes("BTCUSDT")
    for tf, df in dfs.items():
        print(f"\n{tf}: {len(df)} candles, last close = {df['close'].iloc[-1]:.4f}")
        print(df.tail(3)[["open_time", "open", "high", "low", "close", "volume"]])
