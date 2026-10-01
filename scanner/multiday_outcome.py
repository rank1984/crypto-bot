"""
scanner/multiday_outcome.py
Multi-Day Outcome Tracker – computes 24h, 48h, 72h, 7d PnL/MFE/MAE.
Only computes horizons where enough time has passed.
"""

import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
from storage.sqlite_db import DB_PATH
from scanner.market_data import get_candles

log = get_logger("multiday_outcome")


def _to_utc_timestamp(dt) -> pd.Timestamp:
    """Convert to UTC pandas Timestamp safely."""
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def ensure_multiday_table():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS multiday_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                signal_timestamp TEXT NOT NULL,
                data_timestamp TEXT NOT NULL,
                price REAL,
                setup_type TEXT,
                stage TEXT,
                score REAL,
                entry REAL,
                stop REAL,
                tp1 REAL,
                tp2 REAL,
                strategy_type TEXT,
                strategy_version TEXT,
                mode TEXT,
                return_4h REAL,
                return_24h REAL,
                return_48h REAL,
                return_72h REAL,
                exhaustion_score REAL,
                trend_strength REAL,
                rs_1d REAL,
                volume_expansion REAL,
                distance_from_breakout REAL,
                pullback_depth REAL,
                mfe_24h REAL,
                mae_24h REAL,
                pnl_24h REAL,
                mfe_48h REAL,
                mae_48h REAL,
                pnl_48h REAL,
                mfe_72h REAL,
                mae_72h REAL,
                pnl_72h REAL,
                mfe_7d REAL,
                mae_7d REAL,
                pnl_7d REAL,
                outcome_type TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Error creating multiday_signals table: {e}")


def _fetch_candles_since(symbol: str, interval: str, start_ts: datetime):
    """Fetch candles after start_ts."""
    df = get_candles(symbol, interval, limit=500)
    if df is None or df.empty:
        return None

    if "open_time" in df.columns:
        df["time"] = pd.to_datetime(df["open_time"], utc=True)
    elif "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True)
    else:
        return None

    start_ts_utc = _to_utc_timestamp(start_ts)
    df = df[df["time"] >= start_ts_utc].copy()
    return df


def update_multiday_outcomes():
    """Update outcomes for pending Multi-Day signals."""
    ensure_multiday_table()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        signals = cur.execute("""
            SELECT id, symbol, signal_timestamp, entry, stop, tp1, tp2
            FROM multiday_signals
            WHERE outcome_type IS NULL OR outcome_type = 'PENDING'
        """).fetchall()
    except sqlite3.OperationalError as e:
        log.error(f"Table not ready: {e}")
        conn.close()
        return 0

    log.info(f"Updating outcomes for {len(signals)} Multi-Day signals")

    # Current time – used to skip signals that are too fresh
    now = datetime.now(timezone.utc)

    # 🆕 Horizons with required hours
    horizons = {
        "24h": 24,
        "48h": 48,
        "72h": 72,
        "7d": 168,
    }

    updated = 0
    skipped_too_fresh = 0

    for row in signals:
        try:
            symbol = row["symbol"]
            entry = float(row["entry"] or 0)
            stop = float(row["stop"] or 0)
            tp1 = float(row["tp1"] or 0)
            tp2 = float(row["tp2"] or 0)
            if entry <= 0:
                continue

            signal_ts = datetime.fromisoformat(row["signal_timestamp"])
            if signal_ts.tzinfo is None:
                signal_ts = signal_ts.replace(tzinfo=timezone.utc)

            # 🆕 Skip signals that haven't passed 24h yet
            hours_since_signal = (now - signal_ts).total_seconds() / 3600
            if hours_since_signal < 24:
                skipped_too_fresh += 1
                continue

            df = _fetch_candles_since(symbol, "4h", signal_ts)

            if df is None or df.empty:
                log.debug(f"{symbol}: no candles for outcome")
                continue

            df = df.sort_values("time").reset_index(drop=True)
            last_candle_ts = df["time"].iloc[-1]
            hours_of_data = (last_candle_ts - _to_utc_timestamp(signal_ts)).total_seconds() / 3600

            outcomes = {}
            for name, hours_needed in horizons.items():
                # 🆕 Only compute if we have enough data for this horizon
                if hours_of_data < hours_needed:
                    continue

                cutoff = signal_ts + timedelta(hours=hours_needed)
                cutoff_ts = _to_utc_timestamp(cutoff)
                df_horizon = df[df["time"] <= cutoff_ts]

                if df_horizon.empty:
                    continue

                high = df_horizon["high"].max()
                low = df_horizon["low"].min()
                close = df_horizon["close"].iloc[-1]

                outcomes[f"mfe_{name}"] = round((high - entry) / entry * 100, 2)
                outcomes[f"mae_{name}"] = round((low - entry) / entry * 100, 2)
                outcomes[f"pnl_{name}"] = round((close - entry) / entry * 100, 2)

            # Determine outcome_type
            outcome_type = "STILL_OPEN"
            if hours_of_data >= 168:
                outcome_type = "TIMEOUT"
            else:
                if tp1 > 0 and any(df["high"] >= tp1):
                    outcome_type = "TP1_HIT"
                if tp2 > 0 and any(df["high"] >= tp2):
                    outcome_type = "TP2_HIT"
                if stop > 0 and any(df["low"] <= stop):
                    outcome_type = "STOP_HIT"

            # Skip if no outcomes computed yet (still too fresh for even 24h)
            if not outcomes:
                skipped_too_fresh += 1
                continue

            cur.execute("""
                UPDATE multiday_signals
                SET
                    mfe_24h = ?, mae_24h = ?, pnl_24h = ?,
                    mfe_48h = ?, mae_48h = ?, pnl_48h = ?,
                    mfe_72h = ?, mae_72h = ?, pnl_72h = ?,
                    mfe_7d = ?, mae_7d = ?, pnl_7d = ?,
                    outcome_type = ?
                WHERE id = ?
            """, (
                outcomes.get("mfe_24h"), outcomes.get("mae_24h"), outcomes.get("pnl_24h"),
                outcomes.get("mfe_48h"), outcomes.get("mae_48h"), outcomes.get("pnl_48h"),
                outcomes.get("mfe_72h"), outcomes.get("mae_72h"), outcomes.get("pnl_72h"),
                outcomes.get("mfe_7d"), outcomes.get("mae_7d"), outcomes.get("pnl_7d"),
                outcome_type,
                row["id"]
            ))
            updated += 1

        except Exception as e:
            log.error(f"Error updating outcome for {row['symbol']}: {e}")

    conn.commit()
    conn.close()
    log.info(f"Multi-Day outcome update complete: {updated} updated, {skipped_too_fresh} skipped (too fresh)")
    return updated


if __name__ == "__main__":
    update_multiday_outcomes()
