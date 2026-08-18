"""
CRYPTO-BOT Elite — Outcome Tracker v6
Single Source of Truth for trade outcomes.

Calculates:
- MFE
- MAE
- TP1 / TP2 / SL
- first exit event
- exit price
- exit reason
- PnL %
- PnL R
- duration
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone

from utils.logger import get_logger
from storage.candle_cache import get_candles_range

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

TIMEOUT_HOURS = 48


def _parse_ts(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _first_event(df, level, column, direction):
    if level is None or level <= 0:
        return None
    if direction == "up":
        mask = df[column] >= level
    else:
        mask = df[column] <= level
    hits = df.loc[mask]
    if hits.empty:
        return None
    row = hits.iloc[0]
    return (
        row["time"].to_pydatetime().replace(tzinfo=None),
        float(level),
    )


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT *
        FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE')
          AND entry_price > 0
        ORDER BY id
    """).fetchall()

    log.info(f"Outcome tracker V6: processing {len(rows)} open outcomes")

    updated = 0

    for row in rows:
        try:
            symbol = row["symbol"]
            entry = float(row["entry_price"] or 0)
            if entry <= 0:
                continue

            tp1 = float(row["tp1"] or 0)
            tp2 = float(row["tp2"] or 0)
            sl = float(row["sl"] or 0)
            trigger = float(row["trigger_price"] or entry * 1.001)

            t0 = _parse_ts(row["ts"])
            if t0 is None:
                continue

            ts_str = t0.strftime("%Y-%m-%d %H:%M:%S")
            df = get_candles_range(symbol, ts_str)

            if df is None or df.empty:
                log.warning(f"{symbol}: no candles returned — keeping outcome open")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])

            entry_ts = pd.Timestamp(t0, tz="UTC")
            df = df[df["time"] >= entry_ts].copy()
            if df.empty:
                continue

            df = df.sort_values("time").reset_index(drop=True)

            max_high = float(df["high"].max())
            min_low = float(df["low"].min())

            max_up = round((max_high - entry) / entry * 100, 2)
            max_down = round((min_low - entry) / entry * 100, 2)

            last_close = float(df["close"].iloc[-1])
            pnl_pct = round((last_close - entry) / entry * 100, 2) if entry > 0 else 0.0

            trigger_hit = 1 if trigger > 0 and max_high >= trigger else 0
            tp1_hit = 1 if tp1 > 0 and max_high >= tp1 else 0
            tp2_hit = 1 if tp2 > 0 and max_high >= tp2 else 0
            sl_hit = 1 if sl > 0 and min_low <= sl else 0

            def first_time(level, series, direction="high"):
                if level <= 0:
                    return None
                if direction == "high":
                    mask = series >= level
                else:
                    mask = series <= level
                if not mask.any():
                    return None
                t_event = df.loc[mask, "time"].iloc[0].to_pydatetime().replace(tzinfo=None)
                return round((t_event - t0).total_seconds() / 60, 1)

            trigger_min = first_time(trigger, df["high"], "high") if trigger_hit else None
            tp1_min = first_time(tp1, df["high"], "high") if tp1_hit else None
            tp2_min = first_time(tp2, df["high"], "high") if tp2_hit else None
            sl_min = first_time(sl, df["low"], "low") if sl_hit else None

            now = datetime.utcnow()
            hours_elapsed = (now - t0).total_seconds() / 3600
            new_status = "FINAL" if (tp1_hit or tp2_hit or sl_hit or hours_elapsed >= TIMEOUT_HOURS) else "ACTIVE"

            event_times = [x for x in [tp1_min, tp2_min, sl_min] if x is not None]
            first_outcome_time = min(event_times) if event_times else None

            cur.execute("""
                UPDATE shadow_trades
                SET
                    outcome_trigger_hit = ?,
                    outcome_tp1_hit = ?,
                    outcome_tp2_hit = ?,
                    outcome_sl_hit = ?,
                    outcome_max_up_pct = ?,
                    outcome_max_down_pct = ?,
                    outcome_mfe = ?,
                    outcome_mae = ?,
                    outcome_status = ?,
                    time_to_trigger_min = ?,
                    time_to_tp1_min = ?,
                    outcome_tp2_min = ?,
                    time_to_sl_min = ?,
                    outcome_highest_price = ?,
                    outcome_lowest_price = ?,
                    first_tp_hit_time = ?,
                    last_update_time = ?,
                    pnl_pct = ?
                WHERE id = ?
            """, (
                trigger_hit, tp1_hit, tp2_hit, sl_hit,
                max_up, max_down, max_up, abs(max_down),
                new_status, trigger_min, tp1_min, tp2_min, sl_min,
                max_high, min_low, first_outcome_time,
                datetime.utcnow().isoformat(), pnl_pct, row["id"]
            ))

            updated += 1
            log.info(f"{symbol}: status={new_status} trigger={trigger_hit} tp1={tp1_hit} sl={sl_hit} PnL={pnl_pct:.2f}%")

        except Exception as e:
            log.exception(f"Outcome error {row['symbol']}: {e}")

    conn.commit()
    conn.close()

    log.info(f"Outcome tracker V6 complete: {updated}/{len(rows)} updated")

    if updated:
        try:
            from tools.shadow_mode import export_shadow_csv
            export_shadow_csv()
        except Exception as e:
            log.warning(f"CSV export failed: {e}")

    return updated
