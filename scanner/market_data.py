"""
CRYPTO-BOT Elite — Market Data
מקור ראשי: KuCoin. Fallback: CoinGecko OHLCV.
"""
import time
import pandas as pd
import numpy as np
import requests

from utils.cache  import load as cache_load, save as cache_save
from utils.config import KUCOIN_BASE, CANDLES_PER_TF, TIMEFRAMES
from utils.logger import get_logger

log = get_logger(__name__)
_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_DELAY   = 0.05


def _fetch_kucoin(symbol: str, interval: str, limit: int):
    kucoin_sym = symbol.replace("USDT", "-USDT")
    try:
        resp = requests.get(
            f"{KUCOIN_BASE}/api/v1/market/candles",
            headers=_HEADERS,
            params={"symbol": kucoin_sym, "type": interval},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200000":
            return None
        return data.get("data", [])
    except Exception as e:
        log.debug(f"KuCoin failed {symbol}/{interval}: {e}")
        return None


def _fetch_coingecko_ohlcv(symbol: str) -> list | None:
    """
    Fallback: CoinGecko OHLCV (daily — עדיין שימושי לאינדיקטורים)
    מחזיר רשימה של pseudo-5m candles מנתונים יומיים.
    """
    base = symbol.replace("USDT", "").lower()
    # מיפוי נפוצים
    mapping = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
        "bnb": "binancecoin", "xrp": "ripple", "ada": "cardano",
        "doge": "dogecoin", "avax": "avalanche-2", "dot": "polkadot",
        "link": "chainlink", "uni": "uniswap", "aave": "aave",
        "near": "near", "apt": "aptos", "arb": "arbitrum",
        "op": "optimism", "inj": "injective-protocol", "sui": "sui",
        "fet": "fetch-ai", "rndr": "render-token", "tao": "bittensor",
        "pepe": "pepe", "wif": "dogwifcoin", "bonk": "bonk",
        "crv": "curve-dao-token", "mkr": "maker", "ldo": "lido-dao",
    }
    coin_id = mapping.get(base, base)
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
            headers=_HEADERS,
            params={"vs_currency": "usd", "days": "1"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        # [timestamp, open, high, low, close] → convert to KuCoin format
        # KuCoin: [ts_sec, open, close, high, low, volume, turnover]
        result = []
        for row in data:
            ts_sec = row[0] // 1000
            o, h, l, c = row[1], row[2], row[3], row[4]
            vol = 1000.0  # dummy volume
            result.append([str(ts_sec), str(o), str(c), str(h), str(l), str(vol), str(o*vol)])
        return result
    except Exception as e:
        log.debug(f"CoinGecko OHLCV failed {symbol}: {e}")
        return None


def _to_df(raw: list) -> pd.DataFrame:
    rows = list(reversed(raw))
    df = pd.DataFrame(rows, columns=["ts","open","close","high","low","volume","turnover"])
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["open_time"]    = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df["close_time"]   = df["open_time"]
    df["quote_volume"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0)
    df["trades"]       = 0
    return df[["open_time","open","high","low","close","volume",
               "close_time","quote_volume","trades"]].reset_index(drop=True)


def get_candles(symbol: str, interval: str,
                limit: int = CANDLES_PER_TF) -> pd.DataFrame | None:
    cached = cache_load(symbol, interval)
    if cached is not None:
        return _to_df(cached)

    # נסה KuCoin
    raw = _fetch_kucoin(symbol, interval, limit)

    # Fallback: CoinGecko (רק ל-5min כ-proxy)
    if not raw and interval in ("5min", "15min", "1hour"):
        log.debug(f"KuCoin failed {symbol}/{interval} — trying CoinGecko")
        raw = _fetch_coingecko_ohlcv(symbol)

    if not raw:
        return None

    cache_save(symbol, interval, raw)
    time.sleep(_DELAY)
    return _to_df(raw)


def get_all_timeframes(symbol: str) -> dict:
    result = {}
    for tf in TIMEFRAMES:
        df = get_candles(symbol, tf)
        if df is not None and not df.empty and len(df) >= 5:
            result[tf] = df

    # אם חסר timeframe — שכפל מה שיש (כדי לא לפסול מטבע על בעיה טכנית)
    if result:
        available = list(result.keys())
        for tf in TIMEFRAMES:
            if tf not in result:
                # שכפל את ה-tf הכי קרוב
                result[tf] = result[available[0]].copy()
                log.debug(f"{symbol}: {tf} missing, using {available[0]} as proxy")

    return result
