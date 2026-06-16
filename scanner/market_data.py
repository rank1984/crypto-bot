"""
CRYPTO-BOT Elite — Market Data
מקור: KuCoin (חינמי, ללא הרשמה, עובד מ-GitHub Actions).

KuCoin intervals: 1min, 5min, 15min, 1hour
"""
import time
import pandas as pd
import requests

from utils.cache  import load as cache_load, save as cache_save
from utils.config import KUCOIN_BASE, CANDLES_PER_TF, TIMEFRAMES
from utils.logger import get_logger

log = get_logger(__name__)

_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_DELAY   = 0.12   # 120ms בין קריאות → ~8 req/s

# KuCoin מחזיר נרות בסדר הפוך (חדש ראשון) — נהפוך
# עמודות KuCoin: [time, open, close, high, low, volume, turnover]


def _fetch_kucoin(symbol: str, interval: str, limit: int):
    """
    symbol: "BTCUSDT" → KuCoin רוצה "BTC-USDT"
    interval: "5min" (כמו שמוגדר ב-config)
    """
    kucoin_sym = symbol.replace("USDT", "-USDT")
    try:
        resp = requests.get(
            f"{KUCOIN_BASE}/api/v1/market/candles",
            headers=_HEADERS,
            params={"symbol": kucoin_sym, "type": interval},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200000":
            log.debug(f"KuCoin error {symbol}/{interval}: {data.get('msg')}")
            return None
        return data.get("data", [])
    except Exception as e:
        log.debug(f"KuCoin fetch failed {symbol}/{interval}: {e}")
        return None


def _to_df(raw: list) -> pd.DataFrame:
    # KuCoin: [timestamp, open, close, high, low, volume, turnover]
    # סדר הפוך — הישן ראשון אחרי reverse
    rows = list(reversed(raw))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"]  = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df["close_time"] = df["open_time"]
    df["quote_volume"] = df["turnover"].astype(float)
    df["trades"] = 0
    return df[["open_time","open","high","low","close","volume","close_time","quote_volume","trades"]].reset_index(drop=True)


def get_candles(symbol: str, interval: str,
                limit: int = CANDLES_PER_TF):
    cached = cache_load(symbol, interval)
    if cached is not None:
        return _to_df(cached)

    raw = _fetch_kucoin(symbol, interval, limit)
    if not raw:
        return None

    cache_save(symbol, interval, raw)
    time.sleep(_DELAY)
    return _to_df(raw)


def get_all_timeframes(symbol: str) -> dict:
    result = {}
    for tf in TIMEFRAMES:
        df = get_candles(symbol, tf)
        if df is not None and not df.empty:
            result[tf] = df
    return result


if __name__ == "__main__":
    dfs = get_all_timeframes("BTCUSDT")
    for tf, df in dfs.items():
        print(f"\n{tf}: {len(df)} candles, last close = {df['close'].iloc[-1]:.4f}")
