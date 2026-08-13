"""
CRYPTO-BOT Elite — Outcome Tracker v5 (ACTIVE / FINAL) – PnL% fix
"""
import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
from storage.candle_cache import get_candles_range

log = get_logger("outcome_tracker")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_status IN ('PENDING','ACTIVE')
          AND entry_price > 0
        ORDER BY id
        LIMIT 50
    """).fetchall()

    log.info(f"Outcome tracker: found {len(rows)} rows")
    updated = 0

    for row in rows:
        symbol = row["symbol"]
        entry = float(row["entry_price"])
        tp1 = float(row["tp1"] or entry * 1.04)
        tp2 = float(row["tp2"] or entry * 1.10)
        sl = float(row["sl"] or entry * 0.98)
        trigger = float(row["trigger_price"] or entry * 1.001)

        try:
            t0 = datetime.fromisoformat(row["ts"]).replace(tzinfo=None)
            ts_str = t0.strftime("%Y-%m-%d %H:%M:%S")
            log.info(f"Outcome tracker: fetching cached klines for {symbol} since {ts_str}")
            
            df = get_candles_range(symbol, ts_str)
            
            if df is None or df.empty:
                continue

            if not pd.api.types.is_datetime64_any_dtype(df["time"]):
                df["time"] = pd.to_datetime(df["time"])

            max_high = float(df["high"].max())
            min_low = float(df["low"].min())

            max_up = round((max_high - entry) / entry * 100, 2)
            max_down = round((min_low - entry) / entry * 100, 2)

            # חישוב PnL% לפי מחיר סגירה אחרון
            last_close = float(df["close"].iloc[-1])
            pnl_pct = round((last_close - entry) / entry * 100, 2) if entry > 0 else 0.0

            trigger_hit = 1 if max_high >= trigger else 0
            tp1_hit = 1 if tp1 > 0 and max_high >= tp1 else 0
            tp2_hit = 1 if tp2 > 0 and max_high >= tp2 else 0
            sl_hit = 1 if sl > 0 and min_low <= sl else 0

            def first_time(level, series, direction="high"):
                mask = series >= level if direction == "high" else series <= level
                if mask.any():
                    t_event = df["time"][mask].iloc[0].to_pydatetime().replace(tzinfo=None)
                    return round((t_event - t0).total_seconds() / 60, 1)
                return None

            tp1_min = first_time(tp1, df["high"], "high") if tp1_hit else None
            tp2_min = first_time(tp2, df["high"], "high") if tp2_hit else None
            sl_min  = first_time(sl, df["low"], "low") if sl_hit else None
            trigger_min = first_time(trigger, df["high"], "high") if trigger_hit else None

            now = datetime.utcnow()
            hours_elapsed = (now - t0).total_seconds() / 3600
            if tp1_hit or tp2_hit or sl_hit or hours_elapsed >= 48:
                new_status = "FINAL"
            else:
                new_status = "ACTIVE"

            cur.execute("""
                UPDATE shadow_trades
                SET outcome_trigger_hit = ?, outcome_tp1_hit = ?, outcome_tp2_hit = ?,
                    outcome_sl_hit = ?, outcome_max_up_pct = ?, outcome_max_down_pct = ?,
                    outcome_mfe = ?, outcome_mae = ?, outcome_status = ?,
                    time_to_trigger_min = ?, time_to_tp1_min = ?, outcome_tp2_min = ?,
                    time_to_sl_min = ?, outcome_highest_price = ?, outcome_lowest_price = ?,
                    first_tp_hit_time = ?, last_update_time = ?,
                    pnl_pct = ?
                WHERE id = ?
            """, (
                trigger_hit, tp1_hit, tp2_hit, sl_hit,
                max_up, max_down, max_up, abs(max_down), new_status,
                trigger_min, tp1_min, tp2_min, sl_min,
                max_high, min_low,
                tp1_min or tp2_min or sl_min,
                datetime.utcnow().isoformat(),
                pnl_pct,
                row["id"]
            ))
            updated += 1
        except Exception as e:
            log.warning(f"Outcome error {symbol}: {e}")

    conn.commit()

    bad_rows = cur.execute("""
        SELECT COUNT(*) FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND (tp1 IS NULL OR sl IS NULL)
    """).fetchone()[0]
    if bad_rows > 0:
        log.warning(f"Outcome tracker: {bad_rows} rows with missing TP/SL after update")

    conn.close()

    log.info(f"Outcome tracker: updated {updated} rows out of {len(rows)} fetched")
    if updated < 50:
        log.warning(f"Outcome tracker: updated {updated} rows (less than target threshold 50)")

    if updated:
        try:
            from tools.shadow_mode import export_shadow_csv
            export_shadow_csv()
        except Exception as e:
            log.debug(f"Export shadow CSV error: {e}")
    else:
        log.info("Outcome tracker: no rows updated")
