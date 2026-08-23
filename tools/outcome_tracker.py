"""
CRYPTO-BOT Elite — Outcome Tracker v8.5
Single Source of Truth for trade outcomes.
Uses tools.exit_simulator to perfectly mirror live trading limits and exits.
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone

from utils.logger import get_logger
from storage.candle_cache import get_candles_range
from tools.exit_simulator import simulate_trade_path   # ✅ תיקון נתיב

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


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def safe_get(row, key, default=0):
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE') AND entry_price > 0
        ORDER BY id
    """).fetchall()

    executed_count = sum(1 for r in rows if safe_get(r, "was_executed", 0))
    log.info(f"Outcome tracker V8.5: {len(rows)} open outcomes ({executed_count} manually executed)")

    updated = 0
    no_candles = 0

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
                no_candles += 1
                log.warning(f"{symbol}: no candles returned — keeping outcome open")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])
            
            entry_ts = pd.Timestamp(t0, tz="UTC")
            
            # ✅ פילטר בטוח – ללא Look‑Ahead
            df = df[df["time"] >= entry_ts].copy()
            
            if df.empty:
                continue

            # ==========================================================
            # אבחון entry_candle_ambiguous (מחושב בנפרד, לא משפיע על הסימולציה)
            # ==========================================================
            entry_candle_ambiguous = 0
            df_diag = get_candles_range(symbol, ts_str)
            if df_diag is not None and not df_diag.empty:
                df_diag["time"] = pd.to_datetime(df_diag["time"], utc=True, errors="coerce")
                floored = entry_ts.floor('5min')
                if floored < entry_ts:
                    match = df_diag[df_diag["time"] == floored]
                    if not match.empty:
                        entry_candle_ambiguous = 1

            # ==========================================================
            # סימולציה – מקבלת 6 ערכים (כולל is_closed)
            # ==========================================================
            now_ts = pd.Timestamp(datetime.now(timezone.utc), tz="UTC")
            pnl_pct, exit_events, ambiguous_bar, mfe_pct, mae_pct, is_closed = simulate_trade_path(
                df=df, entry_price=entry, sl=sl, tp1=tp1, tp2=tp2,
                entry_ts=entry_ts, now_ts=now_ts, timeout_hours=TIMEOUT_HOURS
            )

            risk_pct = round(abs(entry - sl) / entry * 100, 4) if sl > 0 and entry > 0 else None
            pnl_r = round(pnl_pct / risk_pct, 3) if risk_pct else None
            mfe_r = round(mfe_pct / risk_pct, 3) if risk_pct else None
            mae_r = round(abs(mae_pct) / risk_pct, 3) if risk_pct else None

            first_outcome_type = exit_events[0][0] if exit_events else None

            # ✅ חדש: status נקבע לפי is_closed, לא לפי סכום המשקלים
            new_status = "FINAL" if is_closed else "ACTIVE"

            tp1_hit = 1 if any(ev[0] == "TP1" for ev in exit_events) else 0
            tp2_hit = 1 if any(ev[0] == "TP2" for ev in exit_events) else 0
            sl_hit = 1 if any(ev[0] == "SL" for ev in exit_events) else 0

            cur.execute("""
                UPDATE shadow_trades
                SET
                    outcome_tp1_hit = ?, outcome_tp2_hit = ?, outcome_sl_hit = ?,
                    outcome_mfe = ?, outcome_mae = ?, outcome_max_up_pct = ?, outcome_max_down_pct = ?,
                    outcome_status = ?, outcome_checked = ?,
                    first_outcome_type = ?, ambiguous_bar = ?, entry_candle_ambiguous = ?,
                    last_update_time = ?, pnl_pct = ?, pnl_r = ?, mfe_r = ?, mae_r = ?,
                    pnl_pct_method = ?
                WHERE id = ?
            """, (
                tp1_hit, tp2_hit, sl_hit,
                mfe_pct, abs(mae_pct), mfe_pct, mae_pct,
                new_status, 1 if new_status == "FINAL" else 0,
                first_outcome_type, ambiguous_bar, entry_candle_ambiguous,
                datetime.utcnow().isoformat(),
                pnl_pct, pnl_r, mfe_r, mae_r,
                "simulated_v8.5",
                row["id"]
            ))

            updated += 1

        except Exception as e:
            log.exception(f"Outcome error {row['symbol']}: {e}")

    conn.commit()
    conn.close()

    log.info(f"Outcome tracker V8.5 complete: {updated}/{len(rows)} updated")
    return updated


if __name__ == "__main__":
    update_outcomes()
