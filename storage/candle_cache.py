"""
CRYPTO-BOT Elite — Candle Cache v2.1

CRITICAL FIX from v2.0:
  v2.0 created candles_5m ONLY in candle_cache.db, but scanner/market_data.py
  still tries to INSERT into DB_PATH (data/shadow.db) directly. This caused:
      "Candle save error: no such table: candles_5m"
  → 10/13 BUYs of 2026-11-11 were never processed by outcome_tracker.

  v2.1 solution:
  1. init_cache() creates candles_5m in BOTH DBs (backward compat)
  2. save_candles() writes to candle_cache.db only (canonical)
  3. NEW: migrate_shadow_candles() — moves candles from shadow.db to
     candle_cache.db, then drops the shadow.db table
  4. get_candles_range() reads from candle_cache.db, with fallback to shadow.db
"""
import sqlite3
import os
import pandas as pd
from utils.logger import get_logger

log = get_logger("candle_cache")

CANDLE_CACHE_PATH = os.getenv("CANDLE_CACHE_PATH", "data/candle_cache.db")
SHADOW_DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _cache_conn():
    os.makedirs(os.path.dirname(CANDLE_CACHE_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(CANDLE_CACHE_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return c


def _shadow_conn():
    if not os.path.exists(SHADOW_DB_PATH):
        return None
    c = sqlite3.connect(SHADOW_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS candles_5m (
        symbol TEXT NOT NULL,
        time TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        PRIMARY KEY (symbol, time)
    )
"""

_CREATE_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
    ON candles_5m(symbol, time)
"""


def init_cache():
    """Create candles_5m in BOTH DBs (backward compat with market_data.py)."""
    # ── 1. Canonical: candle_cache.db ──────────────────────
    with _cache_conn() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()

    # ── 2. Backward compat: shadow.db (market_data.py writes here) ──
    sc = _shadow_conn()
    if sc is not None:
        try:
            sc.execute(_CREATE_TABLE_SQL)
            sc.execute(_CREATE_INDEX_SQL)
            sc.commit()
            log.info("candles_5m table ensured in shadow.db (backward compat)")
        except sqlite3.OperationalError as e:
            log.warning(f"Could not create candles_5m in shadow.db: {e}")
        finally:
            sc.close()

    log.info(f"Candle cache initialized at {CANDLE_CACHE_PATH}")


def save_candles(symbol: str, df: pd.DataFrame):
    """Save to candle_cache.db (canonical). df must have: time, o/h/l/c/v."""
    if df is None or df.empty:
        return

    df = df.copy()

    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    df = df.dropna(subset=["time"])

    if df["time"].dt.tz is not None:
        df["time"] = df["time"].dt.tz_convert("UTC").dt.tz_localize(None)
    df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    rows = df[["time", "open", "high", "low", "close", "volume"]].values.tolist()

    with _cache_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO candles_5m
                (symbol, time, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
            """,
            [(symbol, r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
        )
        conn.commit()


def _read_from(conn, symbol, start_ts, end_ts):
    if end_ts:
        rows = conn.execute(
            "SELECT * FROM candles_5m WHERE symbol=? AND time >= ? AND time <= ? ORDER BY time",
            (symbol, start_ts, end_ts),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM candles_5m WHERE symbol=? AND time >= ? ORDER BY time",
            (symbol, start_ts),
        ).fetchall()
    return rows


def get_candles_range(symbol: str, start_ts: str, end_ts: str = None) -> pd.DataFrame:
    """
    Read from candle_cache.db first, fallback to shadow.db.
    This lets us migrate gradually without data loss.
    """
    rows = []
    try:
        with _cache_conn() as conn:
            rows = _read_from(conn, symbol, start_ts, end_ts)
    except sqlite3.OperationalError:
        rows = []

    if not rows:
        sc = _shadow_conn()
        if sc is not None:
            try:
                rows = _read_from(sc, symbol, start_ts, end_ts)
                if rows:
                    log.info(f"{symbol}: {len(rows)} candles from shadow.db (fallback)")
            except sqlite3.OperationalError:
                pass
            finally:
                sc.close()

    if not rows:
        return pd.DataFrame()

    data = {
        "time":   [r["time"] for r in rows],
        "open":   [float(r["open"]) for r in rows],
        "high":   [float(r["high"]) for r in rows],
        "low":    [float(r["low"]) for r in rows],
        "close":  [float(r["close"]) for r in rows],
        "volume": [float(r["volume"]) for r in rows],
    }
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def migrate_shadow_candles_to_cache() -> int:
    """
    One-time migration: copy candles from shadow.db to candle_cache.db,
    then drop candles_5m from shadow.db to shrink it.
    Run ONCE after switching to v2.1.
    """
    sc = _shadow_conn()
    if sc is None:
        log.info("shadow.db not found — nothing to migrate")
        return 0

    try:
        rows = sc.execute("SELECT * FROM candles_5m").fetchall()
    except sqlite3.OperationalError:
        log.info("No candles_5m in shadow.db — nothing to migrate")
        sc.close()
        return 0

    if not rows:
        log.info("candles_5m in shadow.db is empty")
        sc.close()
        return 0

    log.info(f"Migrating {len(rows)} candles from shadow.db → candle_cache.db")

    with _cache_conn() as cc:
        cc.executemany(
            """
            INSERT OR IGNORE INTO candles_5m
                (symbol, time, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
            """,
            [(r["symbol"], r["time"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
        )
        cc.commit()

    # Drop from shadow.db
    sc.execute("DROP TABLE IF EXISTS candles_5m")
    sc.execute("VACUUM")
    sc.commit()
    sc.close()

    log.info(f"Migration complete: {len(rows)} candles moved, shadow.db vacuumed")
    return len(rows)


def prune_candles(retention_hours: int = 48) -> int:
    if not os.path.exists(CANDLE_CACHE_PATH):
        return 0
    with _cache_conn() as conn:
        try:
            cur = conn.execute(
                f"DELETE FROM candles_5m WHERE time < datetime('now', '-{int(retention_hours)} hours')"
            )
            conn.commit()
            return cur.rowcount
        except sqlite3.OperationalError:
            return 0


def vacuum_if_big(threshold_mb: float = 50.0) -> bool:
    if not os.path.exists(CANDLE_CACHE_PATH):
        return False
    size_mb = os.path.getsize(CANDLE_CACHE_PATH) / 1024 / 1024
    if size_mb < threshold_mb:
        return False

    log.warning(f"Candle cache is {size_mb:.1f} MB — VACUUM")
    conn = _cache_conn()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()
    log.info(f"Candle cache after VACUUM: {os.path.getsize(CANDLE_CACHE_PATH) / 1024 / 1024:.1f} MB")
    return True
