"""
CRYPTO-BOT Elite — Market Data
מקור ראשי: KuCoin. Fallback: CoinGecko OHLCV.
"""
import time
import pandas as pd
import numpy as np
import requests

from utils.cache import load as cache_load, save as cache_save
from utils.config import KUCOIN_BASE, CANDLES_PER_TF, TIMEFRAMES
from utils.logger import get_logger

log = get_logger(__name__)
_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_DELAY = 0.05

# מיפוי אינטרוולים סטנדרטיים לפורמט של KuCoin
INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1hour", "2h": "2hour", "4h": "4hour", "8h": "8hour",
    "12h": "12hour", "1d": "1day", "1w": "1week",
    # תמיכה בפורמט KuCoin המקורי אם כבר הועבר כזה:
    "1min": "1min", "5min": "5min", "15min": "15min", "1hour": "1hour"
}


def _fetch_kucoin(symbol: str, interval: str, limit: int):
    kucoin_sym = symbol.replace("USDT", "-USDT")
    kucoin_interval = INTERVAL_MAP.get(interval, interval)
    
    try:
        resp = requests.get(
            f"{KUCOIN_BASE}/api/v1/market/candles",
            headers=_HEADERS,
            params={
                "symbol": kucoin_sym, 
                "type": kucoin_interval,
                # חישוב זמן התחלה במידת הצורך או הסתמכות על גבולות KuCoin
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200000":
            return None
        
        # חיתוך המערך לפי ה-limit המבוקש
        raw_data = data.get("data", [])
        return raw_data[:limit] if raw_data else []
    except Exception as e:
        log.debug(f"KuCoin failed {symbol}/{interval}: {e}")
        return None


def _fetch_coingecko_ohlcv(symbol: str) -> list | None:
    """
    Fallback: CoinGecko OHLCV
    אזהרה: נפח המסחר בנתונים אלו הינו דמה (Dummy) ולא מתאים למדדי Flow.
    """
    base = symbol.replace("USDT", "").lower()
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
            
        result = []
        for row in data:
            ts_sec = row[0] // 1000
            o, h, l, c = row[1], row[2], row[3], row[4]
            vol = 0.0  # מוגדר כ-0 כדי למנוע זיהוי שווא של נפחי מסחר גבוהים
            result.append([str(ts_sec), str(o), str(c), str(h), str(l), str(vol), str(0)])
        return result
    except Exception as e:
        log.debug(f"CoinGecko OHLCV failed {symbol}: {e}")
        return None


def _to_df(raw: list) -> pd.DataFrame:
    rows = list(reversed(raw))
    df = pd.DataFrame(rows, columns=["ts", "open", "close", "high", "low", "volume", "turnover"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["open_time"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df["close_time"] = df["open_time"]
    df["quote_volume"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0)
    df["trades"] = 0
    return df[["open_time", "open", "high", "low", "close", "volume",
               "close_time", "quote_volume", "trades"]].reset_index(drop=True)


def get_candles(symbol: str, interval: str, limit: int = CANDLES_PER_TF) -> pd.DataFrame | None:
    cached = cache_load(symbol, interval)
    if cached is not None:
        df = _to_df(cached)
    else:
        # ניסיון טעינה מ-KuCoin
        raw = _fetch_kucoin(symbol, interval, limit)

        # Fallback ל-CoinGecko רק במידה ו-KuCoin נכשל
        if not raw and interval in ("5m", "5min", "15m", "15min", "1h", "1hour"):
            log.debug(f"KuCoin failed {symbol}/{interval} — trying CoinGecko")
            raw = _fetch_coingecko_ohlcv(symbol)

        if not raw:
            return None

        cache_save(symbol, interval, raw)
        time.sleep(_DELAY)
        df = _to_df(raw)
        
    # שמירה ל-Candle Cache (עבור 5m / 5min)
    if interval in ("5m", "5min"):
        try:
            from storage.candle_cache import save_candles
            df_to_save = df.copy()
            if "time" not in df_to_save.columns:
                df_to_save["time"] = pd.to_datetime(df_to_save["open_time"])
            save_candles(symbol, df_to_save)
        except Exception as e:
            log.warning(f"Candle save error: {e}")

    return df


def get_all_timeframes(symbol: str) -> dict:
    result = {}
    for tf in TIMEFRAMES:
        df = get_candles(symbol, tf)
        if df is not None and not df.empty and len(df) >= 5:
            result[tf] = df

    # אם חסר timeframe — שכפול ה-TF הקרוב ביותר
    if result:
        available = list(result.keys())
        for tf in TIMEFRAMES:
            if tf not in result:
                result[tf] = result[available[0]].copy()
                log.debug(f"{symbol}: {tf} missing, using {available[0]} as proxy")

    return result


def get_ticker_24h(symbol: str) -> dict | None:
    """מנסה Binance, נופל ל‑KuCoin."""
    # נסיון Binance
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": symbol.upper()},
            headers=_HEADERS,
            timeout=5
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass

    # Fallback ל‑KuCoin
    try:
        kucoin_sym = symbol.replace("USDT", "-USDT")
        r = requests.get(
            f"{KUCOIN_BASE}/api/v1/market/stats",
            params={"symbol": kucoin_sym},
            headers=_HEADERS,
            timeout=5
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            return {"quoteVolume": data.get("volValue", 0)}
    except Exception:
        pass

    return None
