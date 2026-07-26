"""
CRYPTO-BOT Elite — Candle Cache
שומר נרות 5m למטבעות בזמן הסריקה, משמש את Outcome Tracker.
"""
import sqlite3
import os
import pandas as pd

DB_PATH = os.getenv("DB_PATH", "data/candle_cache.db")


def init_cache():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candles_5m (
            symbol TEXT NOT NULL,
            time TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, time)
        )
    """
    )
    conn.commit()
    conn.close()


def save_candles(symbol: str, df: pd.DataFrame):
    """df חייב להכיל 'time' (datetime), 'open','high','low','close','volume'"""
    if df is None or df.empty:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # וודא עמודה time בפורמט טקסט
    df = df.copy()
    df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    rows = df[["time", "open", "high", "low", "close", "volume"]].values.tolist()
    for r in rows:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO candles_5m (symbol, time, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?)
            """,
                (symbol, r[0], r[1], r[2], r[3], r[4], r[5]),
            )
        except:
            pass
    conn.commit()
    conn.close()


def get_candles_range(symbol: str, start_ts: str, end_ts: str = None):
    """מחזיר DataFrame עם נרות בטווח (start_ts, end_ts)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if end_ts:
        rows = conn.execute(
            """
            SELECT * FROM candles_5m
            WHERE symbol=? AND time >= ? AND time <= ?
            ORDER BY time
        """,
            (symbol, start_ts, end_ts),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM candles_5m
            WHERE symbol=? AND time >= ?
            ORDER BY time
        """,
            (symbol, start_ts),
        ).fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame()

    # המרה ידנית ל-DataFrame (הגנה מפני Row)
    data = {
        "time": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
    for r in rows:
        data["time"].append(r["time"])
        data["open"].append(float(r["open"]))
        data["high"].append(float(r["high"]))
        data["low"].append(float(r["low"]))
        data["close"].append(float(r["close"]))
        data["volume"].append(float(r["volume"]))

    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"])
    return df
