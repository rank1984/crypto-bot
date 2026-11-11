"""
CRYPTO-BOT Elite — Candle Cache v2.0

ARCHITECTURAL FIX:
  - Candles now live in a SEPARATE file (data/candle_cache.db)
  - This file is never in shadow.db, so shadow.db stays small
  - No more 100MB DB / failed git push / aggressive prune every scan
  - Env var: CANDLE_CACHE_PATH (separate from DB_PATH)
  - Added prune_candles() so main.py doesn't need raw SQL
  - WAL mode for concurrent read/write
"""
import sqlite3
import os
import pandas as pd
from utils.logger import get_logger

log = get_logger("candle_cache")

# ── SEPARATE from shadow.db — this is intentional ────────────
CANDLE_CACHE_PATH = os.getenv("CANDLE_CACHE_PATH", "data/candle_cache.db")


def _conn():
    os.makedirs(os.path.dirname(CANDLE_CACHE_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(CANDLE_CACHE_PATH)
    c.row_factory = sqlite3.Row
    # WAL for concurrent reads during long writes
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return c


def init_cache():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles_5m (
                symbol TEXT NOT NULL,
                time TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (symbol, time)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
            ON candles_5m(symbol, time)
        """)
        conn.commit()
    log.info(f"Candle cache initialized at {CANDLE_CACHE_PATH}")


def save_candles(symbol: str, df: pd.DataFrame):
    """df must contain: time (datetime), open, high, low, close, volume."""
    if df is None or df.empty:
        return

    # Copy to avoid mutating caller's DataFrame
    df = df.copy()

    # Ensure `time` is datetime before strftime
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    df = df.dropna(subset=["time"])

    # Store as UTC text
    if df["time"].dt.tz is not None:
        df["time"] = df["time"].dt.tz_convert("UTC").dt.tz_localize(None)
    df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    rows = df[["time", "open", "high", "low", "close", "volume"]].values.tolist()

    with _conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO candles_5m
                (symbol, time, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
            """,
            [(symbol, r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
        )
        conn.commit()


def get_candles_range(symbol: str, start_ts: str, end_ts: str = None) -> pd.DataFrame:
    """Returns DataFrame with candles in range (start_ts, end_ts). Empty if none."""
    conn = _conn()
    try:
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
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame()

    data = {
        "time": [r["time"] for r in rows],
        "open": [float(r["open"]) for r in rows],
        "high": [float(r["high"]) for r in rows],
        "low": [float(r["low"]) for r in rows],
        "close": [float(r["close"]) for r in rows],
        "volume": [float(r["volume"]) for r in rows],
    }
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


# ── New: prune + size check (main.py no longer needs raw SQL) ──
def prune_candles(retention_hours: int = 48) -> int:
    """Delete candles older than `retention_hours`. Returns deleted row count."""
    if not os.path.exists(CANDLE_CACHE_PATH):
        return 0
    with _conn() as conn:
        try:
            cur = conn.execute(
                f"DELETE FROM candles_5m WHERE time < datetime('now', '-{int(retention_hours)} hours')"
            )
            conn.commit()
            return cur.rowcount
        except sqlite3.OperationalError:
            return 0


def vacuum_if_big(threshold_mb: float = 50.0) -> bool:
    """VACUUM candle_cache.db if it exceeds threshold. Returns True if vacuumed."""
    if not os.path.exists(CANDLE_CACHE_PATH):
        return False
    size_mb = os.path.getsize(CANDLE_CACHE_PATH) / 1024 / 1024
    if size_mb < threshold_mb:
        return False

    log.warning(f"Candle cache is {size_mb:.1f} MB — VACUUM")
    conn = _conn()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()
    log.info(f"Candle cache after VACUUM: {os.path.getsize(CANDLE_CACHE_PATH) / 1024 / 1024:.1f} MB")
    return True
