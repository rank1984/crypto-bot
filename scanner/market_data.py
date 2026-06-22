"""
CRYPTO-BOT Elite — Market Data (Time Machine Ready)
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
_DELAY   = 0.12  # 120ms בין קריאות → ~8 req/s

def _fetch_kucoin(symbol: str, interval: str, end_time: int = None):
    """
    symbol: "BTCUSDT" → KuCoin רוצה "BTC-USDT"
    interval: "5min"
    end_time: Unix timestamp בשניות (s). אם מסופק, יחזיר נרות עד לנקודה זו בעבר.
    """
    kucoin_sym = symbol.replace("USDT", "-USDT")
    
    params = {
        "symbol": kucoin_sym, 
        "type": interval
    }
    
    # 🕒 מנוע מכונת הזמן: אם הוגדר end_time, נבקש מ-KuCoin לחתוך את ההיסטוריה שם
    if end_time is not None:
        params["endAt"] = int(end_time)

    try:
        resp = requests.get(
            f"{KUCOIN_BASE}/api/v1/market/candles",
            headers=_HEADERS,
            params=params,
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


def _to_df(raw: list, limit: int) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()

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
    
    # חיתוך מדויק: לוקחים רק את ה-X נרות האחרונים שהיו זמינים עד אותה נקודת זמן
    df = df.tail(limit).reset_index(drop=True)
    
    return df[["open_time","open","high","low","close","volume","close_time","quote_volume","trades"]]


def get_candles(symbol: str, interval: str, limit: int = CANDLES_PER_TF, end_time: int = None):
    """
    מושך נרות למטבע. תומך במצב Live (ברירת מחדל) ובמצב Replay (באמצעות end_time).
    """
    # ⚠️ אם אנחנו מריצים בדיקה על העבר, עוקפים את ה-Cache כדי למנוע זיהום נתונים
    if end_time is not None:
        raw = _fetch_kucoin(symbol, interval, end_time=end_time)
        if not raw:
            return None
        return _to_df(raw, limit)
        
    # מצב LIVE רגיל - משתמש בבסיס הנתונים הזמני (Cache)
    cached = cache_load(symbol, interval)
    if cached is not None:
        return _to_df(cached, limit)

    raw = _fetch_kucoin(symbol, interval)
    if not raw:
        return None

    cache_save(symbol, interval, raw)
    time.sleep(_DELAY)
    return _to_df(raw, limit)


def get_all_timeframes(symbol: str, end_time: int = None) -> dict:
    """
    מושך את כל טווחי הזמן עבור מטבע מסוים, תומך ב-end_time עבור סימולציית עבר.
    """
    result = {}
    for tf in TIMEFRAMES:
        df = get_candles(symbol, tf, end_time=end_time)
        if df is not None and not df.empty:
            result[tf] = df
    return result


if __name__ == "__main__":
    # בדיקת ריצת Live רגילה להווה
    print("--- 🟢 Testing LIVE Mode ---")
    dfs = get_all_timeframes("BTCUSDT")
    if "5min" in dfs:
        print(f"LIVE 5min: {len(dfs['5min'])} candles, last close = {dfs['5min']['close'].iloc[-1]:.2f}")
        
    # בדיקת סימולציה לעבר (למשל, נתוני שוק של לפני 6 שעות)
    print("\n--- 🕒 Testing REPLAY Mode (6 hours ago) ---")
    six_hours_ago = int(time.time()) - (6 * 60 * 60)
    dfs_past = get_all_timeframes("BTCUSDT", end_time=six_hours_ago)
    if "5min" in dfs_past:
        print(f"REPLAY 5min: {len(dfs_past['5min'])} candles, past close = {dfs_past['5min']['close'].iloc[-1]:.2f}")
