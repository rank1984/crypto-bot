"""
CRYPTO-BOT Elite — Outcome Tracker v9.0
Changes from v8.8:
  - FIX: duration_min uses actual exit time for closed trades (not now_ts)
  - FIX: writes exit_price / final_exit_price / final_exit_time to DB
  - FIX: writes realized_pnl_pct (partial sells) separately
  - FIX: writes sl_type_at_exit (INITIAL / BREAKEVEN / TRAILING)
  - FIX: writes fee_paid_pct / slippage_pct
  - FIX: exit_reason reflects FINAL exit, not first event
  - FIX: outlier guard uses net pnl (after fees/slippage)
  - FIX: skips STILL_OPEN as first_outcome_type
  - FIX: avoids double-fetch of candles
  - FIX: validates SL/TP ordering
  - FIX: writes pnl_pct_net and pnl_r_net (new columns)
  - ADD: ensure_schema() — idempotent migration for new columns
"""
import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone

from utils.logger import get_logger
from storage.candle_cache import get_candles_range
from engines.exit_simulator import simulate_trade_path

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
TIMEOUT_HOURS = 48

# ── Outlier thresholds ─────────────────────────────────────────
MAX_PNL_PCT = 50.0
MAX_ABS_R = 10.0
MAX_DURATION_MIN = 60 * 24 * 7  # 7 days

# ── Defaults for costs (override per-trade when available) ─────
DEFAULT_FEE_PCT = 0.0        # e.g. 0.2 for 0.1% × 2 sides
DEFAULT_SLIPPAGE_PCT = 0.0   # e.g. 0.1 for round-trip slippage estimate

# ── New columns added in v9.0 ──────────────────────────────────
NEW_COLUMNS = {
    "pnl_pct_net": "REAL",
    "pnl_r_net": "REAL",
    "final_exit_price": "REAL",
    "final_exit_time": "TEXT",
    "realized_pnl_pct": "REAL",
    "sl_type_at_exit": "TEXT",
    "fee_paid_pct": "REAL",
    "slippage_pct": "REAL",
    "entry_bar_ambiguous": "INTEGER DEFAULT 0",
}


def ensure_schema(conn):
    """Add any new columns that don't exist yet (idempotent)."""
    cur = conn.cursor()
    existing = {row[1] for row in cur.execute("PRAGMA table_info(shadow_trades)").fetchall()}
    added = 0
    for col, coltype in NEW_COLUMNS.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE shadow_trades ADD COLUMN {col} {coltype}")
                added += 1
                log.info(f"Schema migration: added column {col} {coltype}")
            except sqlite3.OperationalError as e:
                log.warning(f"Could not add column {col}: {e}")
    if added:
        conn.commit()
    return added


def _parse_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _compute_exit_reason(exit_events, is_closed):
    """Return the FINAL exit reason (not the first event)."""
    if not is_closed:
        return None

    final_type = None
    for ev in reversed(exit_events):
        if ev.get("type") in ("SL", "TIMEOUT", "TP2"):
            final_type = ev["type"]
            break

    if final_type is None:
        return "UNKNOWN"

    tp1_hit = any(e.get("type") == "TP1" for e in exit_events)
    tp2_hit = any(e.get("type") == "TP2" for e in exit_events)

    if final_type == "TIMEOUT":
        return "TIMEOUT"
    if final_type == "SL":
        if tp2_hit:
            return "TP2_THEN_SL"
        if tp1_hit:
            return "TP1_THEN_SL"
        return "SL"
    if final_type == "TP2":
        return "TP2"
    return final_type


def _first_outcome_type(exit_events):
    """First meaningful event (skip STILL_OPEN)."""
    for ev in exit_events:
        if ev.get("type") in ("SL", "TP1", "TP2", "TIMEOUT"):
            return ev["type"]
    return None


def _mark_invalid(cur, trade_id, reason):
    """Mark a trade as INVALID (preserve row, exclude from stats)."""
    cur.execute("""
        UPDATE shadow_trades
        SET outcome_status = 'INVALID',
            exit_reason = ?,
            status = 'INVALID ⚠️',
            outcome_checked = 1,
            pnl_pct = NULL,
            pnl_pct_net = NULL,
            pnl_r = NULL,
            pnl_r_net = NULL,
            mfe_r = NULL,
            mae_r = NULL,
            exit_price = NULL,
            final_exit_price = NULL,
            final_exit_time = NULL,
            realized_pnl_pct = NULL,
            sl_type_at_exit = NULL
        WHERE id = ?
    """, (reason, trade_id))


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Migrate schema if needed
    ensure_schema(conn)

    def safe_get(row, key, default=0):
        try:
            val = row[key]
            return default if val is None else val
        except (IndexError, KeyError):
            return default

    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE')
          AND decision = 'BUY'
          AND entry_price > 0
        ORDER BY id
    """).fetchall()

    executed_count = sum(1 for r in rows if safe_get(r, "was_executed", 0))
    log.info(f"Outcome tracker V9.0: {len(rows)} open BUY outcomes ({executed_count} manually executed)")

    updated = 0
    invalidated = 0
    no_candles = 0
    now_ts = pd.Timestamp.now(tz="UTC")

    for row in rows:
        try:
            symbol = row["symbol"]
            entry = float(row["entry_price"] or 0)
            if entry <= 0:
                continue

            tp1 = float(row["tp1"] or 0)
            tp2 = float(row["tp2"] or 0)
            sl = float(row["sl"] or 0)

            # ── Validate SL ─────────────────────────────────
            if sl <= 0 or sl >= entry:
                log.warning(f"{symbol} id={row['id']}: invalid SL={sl} (entry={entry}) → INVALID")
                _mark_invalid(cur, row["id"], "INVALID_SL")
                invalidated += 1
                continue

            # ── Validate TP1 ────────────────────────────────
            if tp1 > 0 and tp1 <= entry:
                log.warning(f"{symbol} id={row['id']}: invalid TP1={tp1} (entry={entry}) → INVALID")
                _mark_invalid(cur, row["id"], "INVALID_TP1")
                invalidated += 1
                continue

            t0 = _parse_ts(row["ts"])
            if t0 is None:
                continue

            ts_str = t0.strftime("%Y-%m-%d %H:%M:%S")
            df = get_candles_range(symbol, ts_str)

            if df is None or df.empty:
                no_candles += 1
                log.warning(f"{symbol}: no candles — keeping outcome open")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])

            entry_ts = pd.Timestamp(t0, tz="UTC")
            # Include entry bar (floor to bar boundary); ambiguity handled by simulator
            bar_floor = entry_ts.floor(f"{5}min")
            df = df[df["time"] >= bar_floor].copy()

            if df.empty:
                continue

            # ── Simulate ────────────────────────────────────
            result = simulate_trade_path(
                df=df,
                entry_price=entry,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                entry_ts=entry_ts,
                now_ts=now_ts,
                timeout_hours=TIMEOUT_HOURS,
                fee_pct=DEFAULT_FEE_PCT,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
            )

            pnl_pct = result["pnl_pct"]
            pnl_pct_net = result["pnl_pct_net"]
            exit_events = result["exit_events"]
            is_closed = result["is_closed"]

            # ── Risk and R ──────────────────────────────────
            risk_pct = round(abs(entry - sl) / entry * 100, 4) if sl > 0 and entry > 0 else None
            pnl_r = round(pnl_pct / risk_pct, 3) if risk_pct and risk_pct > 0 else None
            pnl_r_net = round(pnl_pct_net / risk_pct, 3) if risk_pct and risk_pct > 0 else None

            mfe_pct = result["mfe_pct"]
            mae_pct = result["mae_pct"]
            mfe_r = round(mfe_pct / risk_pct, 3) if risk_pct and risk_pct > 0 else None
            mae_r = round(abs(mae_pct) / risk_pct, 3) if risk_pct and risk_pct > 0 else None

            # ── Event flags ─────────────────────────────────
            tp1_hit = 1 if any(ev.get("type") == "TP1" for ev in exit_events) else 0
            tp2_hit = 1 if any(ev.get("type") == "TP2" for ev in exit_events) else 0
            sl_hit = 1 if any(ev.get("type") == "SL" for ev in exit_events) else 0

            first_outcome_type = _first_outcome_type(exit_events)

            new_status = "FINAL" if is_closed else "ACTIVE"

            # ── Duration (use ACTUAL exit time for closed) ──
            duration_min = None
            try:
                if is_closed and result["final_exit_time"] is not None:
                    exit_ts = pd.Timestamp(result["final_exit_time"])
                    if exit_ts.tzinfo is None:
                        exit_ts = exit_ts.tz_localize("UTC")
                    dur_seconds = (exit_ts - entry_ts).total_seconds()
                    duration_min = int(dur_seconds / 60.0)
                elif not is_closed:
                    dur_seconds = (now_ts - entry_ts).total_seconds()
                    duration_min = int(dur_seconds / 60.0)
            except Exception as e:
                log.warning(f"{symbol} id={row['id']}: duration calc failed: {e}")

            # ══════════════════════════════════════════════════
            # OUTLIER GUARD (uses NET pnl for conservatism)
            # ══════════════════════════════════════════════════
            if is_closed:
                if pnl_pct_net is not None and abs(pnl_pct_net) > MAX_PNL_PCT:
                    log.warning(
                        f"SUSPECT: {symbol} id={row['id']} "
                        f"pnl_net={pnl_pct_net:.2f}% > ±{MAX_PNL_PCT}% → INVALID"
                    )
                    _mark_invalid(cur, row["id"], "OUTLIER_PNL")
                    invalidated += 1
                    continue

                if pnl_r_net is not None and abs(pnl_r_net) > MAX_ABS_R:
                    log.warning(
                        f"SUSPECT: {symbol} id={row['id']} "
                        f"R_net={pnl_r_net:.2f} > ±{MAX_ABS_R} → INVALID"
                    )
                    _mark_invalid(cur, row["id"], "OUTLIER_R")
                    invalidated += 1
                    continue

                if duration_min is not None and duration_min > MAX_DURATION_MIN:
                    log.warning(
                        f"STALE: {symbol} id={row['id']} "
                        f"dur={duration_min}m > 7d → INVALID"
                    )
                    _mark_invalid(cur, row["id"], "OUTLIER_STALE")
                    invalidated += 1
                    continue

            # ── Compute final exit_reason ──────────────────
            exit_reason = _compute_exit_reason(exit_events, is_closed) if is_closed else None
            new_status_field = "FINAL ✅" if is_closed else "Pending ⏳"

            # ── Final exit info ─────────────────────────────
            final_exit_price = result["final_exit_price"]
            final_exit_time = result["final_exit_time"]
            final_exit_time_str = (
                final_exit_time.isoformat() if hasattr(final_exit_time, "isoformat")
                else (str(final_exit_time) if final_exit_time else None)
            )

            cur.execute("""
                UPDATE shadow_trades
                SET
                    outcome_tp1_hit = ?, outcome_tp2_hit = ?, outcome_sl_hit = ?,
                    outcome_mfe = ?, outcome_mae = ?,
                    outcome_max_up_pct = ?, outcome_max_down_pct = ?,
                    outcome_status = ?, outcome_checked = ?,
                    first_outcome_type = ?, ambiguous_bar = ?, entry_candle_ambiguous = ?,
                    last_update_time = ?,
                    pnl_pct = ?, pnl_pct_net = ?,
                    pnl_r = ?, pnl_r_net = ?,
                    mfe_r = ?, mae_r = ?,
                    pnl_pct_method = ?,
                    exit_reason = ?,
                    exit_price = ?, final_exit_price = ?, final_exit_time = ?,
                    realized_pnl_pct = ?,
                    sl_type_at_exit = ?,
                    fee_paid_pct = ?, slippage_pct = ?,
                    duration_minutes = ?,
                    status = ?,
                    trade_state = ?
                WHERE id = ?
            """, (
                tp1_hit, tp2_hit, sl_hit,
                mfe_pct, abs(mae_pct), mfe_pct, mae_pct,
                new_status, 1 if new_status == "FINAL" else 0,
                first_outcome_type,
                result["ambiguous_bar"],
                result["entry_bar_ambiguous"],
                datetime.utcnow().isoformat(),
                pnl_pct, pnl_pct_net,
                pnl_r, pnl_r_net,
                mfe_r, mae_r,
                "simulated_v9.0",
                exit_reason,
                final_exit_price, final_exit_price, final_exit_time_str,
                result["realized_pnl_partial"],
                result["sl_type_at_exit"],
                DEFAULT_FEE_PCT, DEFAULT_SLIPPAGE_PCT,
                duration_min,
                new_status_field,
                "CLOSED" if is_closed else "ACTIVE",
                row["id"],
            ))

            if cur.rowcount != 1:
                log.error(f"{symbol} id={row['id']}: UPDATE affected {cur.rowcount} rows (expected 1)")

            updated += 1
            if is_closed:
                log.info(
                    f"{symbol} id={row['id']} → {exit_reason} | "
                    f"pnl={pnl_pct:.2f}% net={pnl_pct_net:.2f}% "
                    f"R={pnl_r} R_net={pnl_r_net} dur={duration_min}m "
                    f"sl_type={result['sl_type_at_exit']}"
                )

        except Exception as e:
            log.exception(f"Outcome error {row['symbol']}: {e}")

    conn.commit()
    conn.close()

    log.info(
        f"Outcome tracker V9.0 complete: "
        f"{updated}/{len(rows)} updated, "
        f"{invalidated} invalidated, "
        f"{no_candles} without candles"
    )
    return updated


if __name__ == "__main__":
    update_outcomes()
