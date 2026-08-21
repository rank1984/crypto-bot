"""
CRYPTO-BOT Elite — Outcome Tracker v8
Single Source of Truth for trade outcomes.
Simulates realized PnL following trade_manager's partial-exit state machine.
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


def _simulate_realized_outcome(df, entry, sl, tp1, tp2, risk_pct):
    """
    מדמה את מנגנון ה-Partial Exit של trade_manager.py:
      TP1 -> מוכרים 20%, SL -> Breakeven
      TP2 -> מוכרים עוד 20%, שאר ה-60% ב-Runner עם Trailing מקורב (risk_pct * 1.8)
    כלל שמרני: TP ו-SL באותו candle -> SL קודם (ambiguous_bar=1).
    מחזיר: (realized_pnl_pct, exit_events, ambiguous_bar)
    """
    position = 1.0
    current_sl = sl
    tp1_done = False
    tp2_done = False
    realized_pnl_weighted = 0.0
    highest_since_entry = entry
    ambiguous_bar = 0
    exit_events = []

    runner_trail_pct = risk_pct * 1.8 if risk_pct else None

    for _, bar in df.iterrows():
        high, low = float(bar["high"]), float(bar["low"])
        if high > highest_since_entry:
            highest_since_entry = high

        hit_sl_now = current_sl > 0 and low <= current_sl
        hit_tp1_now = (not tp1_done) and tp1 > 0 and high >= tp1
        hit_tp2_now = tp1_done and (not tp2_done) and tp2 > 0 and high >= tp2

        if hit_sl_now and (hit_tp1_now or hit_tp2_now):
            ambiguous_bar = 1
            hit_tp1_now = False
            hit_tp2_now = False

        if hit_sl_now:
            sl_pct = (current_sl - entry) / entry * 100
            realized_pnl_weighted += sl_pct * position
            exit_events.append(("SL", sl_pct, position))
            position = 0.0
            break

        if hit_tp1_now:
            tp1_pct = (tp1 - entry) / entry * 100
            realized_pnl_weighted += tp1_pct * 0.2
            exit_events.append(("TP1", tp1_pct, 0.2))
            position -= 0.2
            tp1_done = True
            current_sl = entry  # Breakeven

        if hit_tp2_now:
            tp2_pct = (tp2 - entry) / entry * 100
            realized_pnl_weighted += tp2_pct * 0.2
            exit_events.append(("TP2", tp2_pct, 0.2))
            position -= 0.2
            tp2_done = True

        if tp2_done and runner_trail_pct:
            trail_level = highest_since_entry * (1 - runner_trail_pct / 100)
            current_sl = max(current_sl, trail_level)

    else:
        if position > 0:
            last_close = float(df["close"].iloc[-1])
            timeout_pct = (last_close - entry) / entry * 100
            realized_pnl_weighted += timeout_pct * position
            exit_events.append(("TIMEOUT", timeout_pct, position))

    return round(realized_pnl_weighted, 3), exit_events, ambiguous_bar


def _first_hit_index(df, level, column, direction):
    if level <= 0:
        return None
    mask = df[column] >= level if direction == "high" else df[column] <= level
    if not mask.any():
        return None
    return int(df.index[mask][0])


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE') AND entry_price > 0
        ORDER BY id
    """).fetchall()

    executed_count = sum(1 for r in rows if r["was_executed"])
    log.info(f"Outcome tracker V8: {len(rows)} open outcomes ({executed_count} manually executed)")

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
            df = df[df["time"] >= entry_ts].copy()   # ✅ מאושר: time=OPEN, אין look-ahead
            if df.empty:
                continue

            df = df.sort_values("time").reset_index(drop=True)

            max_high = float(df["high"].max())
            min_low = float(df["low"].min())
            max_up = round((max_high - entry) / entry * 100, 2)
            max_down = round((min_low - entry) / entry * 100, 2)

            trigger_hit = 1 if trigger > 0 and max_high >= trigger else 0
            tp1_hit = 1 if tp1 > 0 and max_high >= tp1 else 0
            tp2_hit = 1 if tp2 > 0 and max_high >= tp2 else 0
            sl_hit = 1 if sl > 0 and min_low <= sl else 0

            risk_pct = round(abs(entry - sl) / entry * 100, 4) if sl > 0 and entry > 0 else None

            # 🆕 סימולציית Partial Exit במקום last_close
            realized_pnl_pct, exit_events, ambiguous_bar = _simulate_realized_outcome(
                df, entry, sl, tp1, tp2, risk_pct
            )
            first_outcome_type = exit_events[0][0] if exit_events else None

            def minutes_at_index(idx):
                if idx is None:
                    return None
                t_event = df.loc[idx, "time"].to_pydatetime().replace(tzinfo=None)
                return round((t_event - t0).total_seconds() / 60, 1)

            trigger_min = minutes_at_index(_first_hit_index(df, trigger, "high", "high")) if trigger_hit else None
            tp1_min = minutes_at_index(_first_hit_index(df, tp1, "high", "high")) if tp1_hit else None
            tp2_min = minutes_at_index(_first_hit_index(df, tp2, "high", "high")) if tp2_hit else None
            sl_min = minutes_at_index(_first_hit_index(df, sl, "low", "low")) if sl_hit else None

            now = datetime.utcnow()
            hours_elapsed = (now - t0).total_seconds() / 3600
            timed_out = hours_elapsed >= TIMEOUT_HOURS
            new_status = "FINAL" if (tp1_hit or tp2_hit or sl_hit or timed_out) else "ACTIVE"
            if new_status == "FINAL" and first_outcome_type is None and timed_out:
                first_outcome_type = "TIMEOUT"

            pnl_pct = realized_pnl_pct
            pnl_r = round(pnl_pct / risk_pct, 3) if risk_pct else None
            mfe_r = round(max_up / risk_pct, 3) if risk_pct else None
            mae_r = round(abs(max_down) / risk_pct, 3) if risk_pct else None

            cur.execute("""
                UPDATE shadow_trades
                SET
                    outcome_trigger_hit = ?, outcome_tp1_hit = ?, outcome_tp2_hit = ?, outcome_sl_hit = ?,
                    outcome_max_up_pct = ?, outcome_max_down_pct = ?, outcome_mfe = ?, outcome_mae = ?,
                    outcome_status = ?, outcome_checked = ?,
                    time_to_trigger_min = ?, time_to_tp1_min = ?, outcome_tp2_min = ?, time_to_sl_min = ?,
                    outcome_highest_price = ?, outcome_lowest_price = ?,
                    first_tp_hit_time = ?, first_outcome_type = ?, ambiguous_bar = ?,
                    last_update_time = ?, pnl_pct = ?, pnl_r = ?, mfe_r = ?, mae_r = ?,
                    pnl_pct_method = ?
                WHERE id = ?
            """, (
                trigger_hit, tp1_hit, tp2_hit, sl_hit,
                max_up, max_down, max_up, abs(max_down),
                new_status, 1 if new_status == "FINAL" else 0,
                trigger_min, tp1_min, tp2_min, sl_min,
                max_high, min_low,
                minutes_at_index(_first_hit_index(df, sl if first_outcome_type == "SL" else 0, "low", "low")),
                first_outcome_type, ambiguous_bar,
                datetime.utcnow().isoformat(),
                pnl_pct, pnl_r, mfe_r, mae_r,
                "simulated_v8",
                row["id"]
            ))

            updated += 1
            log.info(f"{symbol}: status={new_status} first={first_outcome_type} "
                     f"PnL={pnl_pct:.2f}% ({pnl_r if pnl_r is not None else 'n/a'}R) ambiguous={ambiguous_bar}")

        except Exception as e:
            log.exception(f"Outcome error {row['symbol']}: {e}")

    conn.commit()
    conn.close()

    log.info(f"Outcome tracker V8 complete: {updated}/{len(rows)} updated, {no_candles} no-candle (kept open)")

    if updated:
        try:
            from tools.shadow_mode import export_shadow_csv
            export_shadow_csv()
        except Exception as e:
            log.warning(f"CSV export failed: {e}")

    return updated
