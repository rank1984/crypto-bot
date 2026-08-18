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

            t0 = _parse_ts(row["ts"])
            if t0 is None:
                log.warning(f"{symbol}: invalid entry timestamp")
                continue

            ts_str = t0.strftime("%Y-%m-%d %H:%M:%S")
            df = get_candles_range(symbol, ts_str)

            if df is None or df.empty:
                log.warning(f"{symbol}: no candles returned")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])

            entry_ts = pd.Timestamp(t0, tz="UTC")
            df = df[df["time"] >= entry_ts].copy()
            if df.empty:
                log.warning(f"{symbol}: no candles after entry")
                continue

            df = df.sort_values("time").reset_index(drop=True)

            max_high = float(df["high"].max())
            min_low = float(df["low"].min())

            mfe_pct = (max_high - entry) / entry * 100
            mae_pct = (min_low - entry) / entry * 100

            tp1_event = _first_event(df, tp1, "high", "up")
            tp2_event = _first_event(df, tp2, "high", "up")
            sl_event = _first_event(df, sl, "low", "down")

            events = []
            if tp1_event:
                events.append(("TP1", tp1_event[0], tp1))
            if tp2_event:
                events.append(("TP2", tp2_event[0], tp2))
            if sl_event:
                events.append(("SL", sl_event[0], sl))
            events.sort(key=lambda x: x[1])

            exit_reason = None
            exit_price = None
            exit_time = None

            if events:
                exit_reason, exit_time, exit_price = events[0]

            last_candle_time = df["time"].iloc[-1].to_pydatetime().replace(tzinfo=None)
            elapsed_minutes = (last_candle_time - t0).total_seconds() / 60

            if exit_reason is None:
                if elapsed_minutes >= TIMEOUT_HOURS * 60:
                    exit_reason = "TIME"
                    exit_time = last_candle_time
                    exit_price = float(df["close"].iloc[-1])

            if exit_reason:
                pnl_pct = (exit_price - entry) / entry * 100
                duration_minutes = (exit_time - t0).total_seconds() / 60
                new_status = "FINAL"
            else:
                last_close = float(df["close"].iloc[-1])
                pnl_pct = (last_close - entry) / entry * 100
                duration_minutes = elapsed_minutes
                new_status = "ACTIVE"

            risk_pct = abs(sl - entry) / entry * 100 if sl > 0 else 0.0
            pnl_r = pnl_pct / risk_pct if risk_pct > 0 else None
            mfe_r = mfe_pct / risk_pct if risk_pct > 0 else None
            mae_r = abs(mae_pct) / risk_pct if risk_pct > 0 else None

            tp1_hit = int(tp1_event is not None)
            tp2_hit = int(tp2_event is not None)
            sl_hit = int(sl_event is not None)

            def minutes_from_entry(event):
                if not event:
                    return None
                return round((event[0] - t0).total_seconds() / 60, 1)

            tp1_min = minutes_from_entry(tp1_event)
            tp2_min = minutes_from_entry(tp2_event)
            sl_min = minutes_from_entry(sl_event)

            cur.execute("""
                UPDATE shadow_trades
                SET
                    outcome_tp1_hit = ?,
                    outcome_tp2_hit = ?,
                    outcome_sl_hit = ?,
                    outcome_max_up_pct = ?,
                    outcome_max_down_pct = ?,
                    outcome_mfe = ?,
                    outcome_mae = ?,
                    pnl_pct = ?,
                    pnl_r = ?,
                    duration_minutes = ?,
                    exit_reason = ?,
                    exit_price = ?,
                    outcome_status = ?,
                    time_to_tp1_min = ?,
                    outcome_tp2_min = ?,
                    time_to_sl_min = ?,
                    outcome_highest_price = ?,
                    outcome_lowest_price = ?,
                    outcome_checked = 1,
                    last_update_time = ?
                WHERE id = ?
            """, (
                tp1_hit, tp2_hit, sl_hit,
                round(mfe_pct, 4), round(mae_pct, 4),
                round(mfe_pct, 4), round(abs(mae_pct), 4),
                round(pnl_pct, 4), round(pnl_r, 4) if pnl_r is not None else None,
                int(duration_minutes),
                exit_reason,
                exit_price,
                new_status,
                tp1_min, tp2_min, sl_min,
                max_high, min_low,
                1,
                datetime.utcnow().isoformat(),
                row["id"]
            ))

            updated += 1

            log.info(f"{symbol}: status={new_status} reason={exit_reason} PnL={pnl_pct:.2f}% MFE={mfe_pct:.2f}% MAE={mae_pct:.2f}%")

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