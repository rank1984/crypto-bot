import os
import requests
import pandas as pd
from typing import Optional, Dict

from utils.config import KUCOIN_BASE
from utils.cache  import load as cache_load, save as cache_save

def get_candles(symbol: str, timeframe: str, limit: int = 100, end_time: Optional[int] = None) -> pd.DataFrame:
    """
    מושך נרות מ-KuCoin עבור סימבול ואינטרוול מסוים.
    אם end_time מסופק (בפורמט Unix Timestamp בשניות), המערכת תמשוך נתונים היסטוריים עד לאותה נקודה.
    """
    # התאמת פורמט הסימבול ל-KuCoin (למשל מ-SYNUSDT ל-SYN-USDT)
    kucoin_symbol = symbol
    if "USDT" in symbol and "-" not in symbol:
        kucoin_symbol = symbol.replace("USDT", "-USDT")

    # ניהול ה-Cache: נרצה להשתמש בזה רק בריצה רגילה (לייב) ולא בזמן Replay
    cache_key = f"candles_{symbol}_{timeframe}_{limit}"
    if end_time is None:
        cached_data = cache_load(cache_key)
        if cached_data is not None:
            return pd.DataFrame(cached_data)

    # בניית הפרמטרים לקריאת ה-API
    params = {
        "symbol": kucoin_symbol,
        "type": timeframe,
        "limit": limit
    }

    # 🔥 הצינור ל-Replay Engine: הזרקת חותמת הזמן של העבר ל-KuCoin
    if end_time is not None:
        params["endAt"] = int(end_time)

    try:
        url = f"{KUCOIN_BASE}/api/v1/market/candles"
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        
        res_json = resp.json()
        data = res_json.get("data", [])
        
        if not data:
            return pd.DataFrame()
            
        # בניית ה-DataFrame מהמבנה של KuCoin
        # הפורמט של KuCoin מחזיר רשימה של רשימות: [time, open, close, high, low, volume, turnover]
        df = pd.DataFrame(data, columns=['open_time', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
        
        # המרת טיפוסים
        df['open_time'] = pd.to_datetime(df['open_time'].astype(float), unit='s')
        for col in ['open', 'close', 'high', 'low', 'volume', 'turnover']:
            df[col] = df[col].astype(float)
            
        # KuCoin מחזיר מהחדש לישן (Reverse Chronological). 
        # אנחנו הופכים את הסדר כדי שהאינדיקטורים הטכניים יחושבו נכון (מהישן ביותר לחדש ביותר)
        df = df.iloc[::-1].reset_index(drop=True)

        # שמירה ב-Cache (רק אם אנחנו בריצת לייב רגילה)
        if end_time is None:
            cache_save(cache_key, df.to_dict(orient='records'))

        return df

    except Exception as e:
        print(f"❌ שגיאה במשיכת נרות עבור {symbol} ב-TF {timeframe}: {e}")
        return pd.DataFrame()

def get_all_timeframes(symbol: str, end_time: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """
    מוריד ומארגן את כל ה-Timeframes הנדרשים לצורך ה-Ranking של המטבע.
    מזרים את ה-end_time הלאה אל פונקציית הבסיס.
    """
    # רשימת האינטרוולים שהבוט שלך צריך לצורך חישוב ה-Score (ודא שזה תואם לאינטרוולים שלך)
    timeframes = ["5min", "15min", "1hour", "4hour"]
    dfs = {}
    
    for tf in timeframes:
        df = get_candles(symbol, tf, limit=100, end_time=end_time)
        if not df.empty:
            dfs[tf] = df
            
    return dfs
