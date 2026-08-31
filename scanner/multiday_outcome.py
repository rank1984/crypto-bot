"""
scanner/multiday_outcome.py
Multi-Day Outcome Tracker – computes 24h, 48h, 72h, 7d PnL/MFE/MAE.
Uses point-in-time data only.
"""

import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
from storage.sqlite_db import DB_PATH
from scanner.market_data import get_candles

log = get_logger("multiday_outcome")


def update_multiday_outcomes():
    """Update outcomes for all pending Multi-Day signals."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get signals that are still pending (outcome_type is NULL or 'PENDING')
    signals = cur.execute("""
        SELECT id, symbol, signal_timestamp, entry, stop, tp1, tp2
        FROM multiday_signals
        WHERE outcome_type IS NULL OR outcome_type = 'PENDING'
    """).fetchall()

    log.info(f"Updating outcomes for {len(signals)} Multi-Day signals")

    updated = 0
    for row in signals:
        try:
            symbol = row["symbol"]
            entry = float(row["entry"])
            stop = float(row["stop"])
            tp1 = float(row["tp1"])
            tp2 = float(row["tp2"])
            signal_ts = datetime.fromisoformat(row["signal_timestamp"])

            # Get candles starting from signal time
            ts_str = signal_ts.strftime("%Y-%m-%d %H:%M:%S")
            df = get_candles(symbol, "4h", start=ts_str)

            if df is None or df.empty:
                log.debug(f"{symbol}: no candles for outcome")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)

            # Compute outcomes for each horizon
            horizons = {
                "24h": 24,
                "48h": 48,
                "72h": 72,
                "7d": 168  # 7 days * 24 hours
            }

            outcomes = {}
            for name, hours in horizons.items():
                cutoff = signal_ts + timedelta(hours=hours)
                df_horizon = df[df["time"] <= cutoff]

                if df_horizon.empty:
                    continue

                high = df_horizon["high"].max()
                low = df_horizon["low"].min()
                close = df_horizon["close"].iloc[-1]

                mfe = (high - entry) / entry * 100
                mae = (low - entry) / entry * 100
                pnl = (close - entry) / entry * 100

                outcomes[f"mfe_{name}"] = round(mfe, 2)
                outcomes[f"mae_{name}"] = round(mae, 2)
                outcomes[f"pnl_{name}"] = round(pnl, 2)

            # Determine outcome type (first target hit, stop, timeout, still open)
            outcome_type = "STILL_OPEN"
            if not df.empty:
                last_time = df["time"].iloc[-1]
                hours_elapsed = (last_time - signal_ts).total_seconds() / 3600
                if hours_elapsed >= 168:  # 7 days
                    outcome_type = "TIMEOUT"
                else:
                    # Check if TP1 or TP2 was hit
                    high_series = df["high"]
                    low_series = df["low"]
                    if any(high_series >= tp1):
                        outcome_type = "TP1_HIT"
                    if any(high_series >= tp2):
                        outcome_type = "TP2_HIT"
                    if any(low_series <= stop):
                        outcome_type = "STOP_HIT"

            # Update database
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
                outcomes.get("mfe_24h", 0), outcomes.get("mae_24h", 0), outcomes.get("pnl_24h", 0),
                outcomes.get("mfe_48h", 0), outcomes.get("mae_48h", 0), outcomes.get("pnl_48h", 0),
                outcomes.get("mfe_72h", 0), outcomes.get("mae_72h", 0), outcomes.get("pnl_72h", 0),
                outcomes.get("mfe_7d", 0), outcomes.get("mae_7d", 0), outcomes.get("pnl_7d", 0),
                outcome_type,
                row["id"]
            ))
            updated += 1

        except Exception as e:
            log.error(f"Error updating outcome for {row['symbol']}: {e}")

    conn.commit()
    conn.close()
    log.info(f"Multi-Day outcome update complete: {updated} updated")
    return updated


if __name__ == "__main__":
    update_multiday_outcomes()
