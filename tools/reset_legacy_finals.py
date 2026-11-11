"""
Reset legacy FINAL trades to ACTIVE for re-computation by tracker v9.0.

SAFETY LAYERS:
  1. Requires CONFIRM_RESET=YES
  2. Backs up old values to *_legacy columns (added on first run)
  3. Records reset timestamp
  4. Optional age filter: MAX_AGE_HOURS (default 168 = 7 days)
     Trades older than this are marked UNRECOVERABLE (not reset)
  5. DRY_RUN=YES shows what would be reset without doing it

USAGE:
  # Preview only
  DRY_RUN=YES python -m tools.reset_legacy_finals

  # Reset all (default 7-day age filter)
  CONFIRM_RESET=YES python -m tools.reset_legacy_finals

  # Reset only trades <= 72h old (safer — candles likely available)
  CONFIRM_RESET=YES MAX_AGE_HOURS=72 python -m tools.reset_legacy_finals

  # Reset without age limit (may fail for very old trades due to missing candles)
  CONFIRM_RESET=YES MAX_AGE_HOURS=99999 python -m tools.reset_legacy_finals
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from utils.logger import get_logger

log = get_logger("reset_legacy")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "168"))  # default 7 days
DRY_RUN = os.getenv("DRY_RUN") == "YES"
CONFIRM = os.getenv("CONFIRM_RESET") == "YES"


def _add_column_if_missing(cur, col, coltype):
    try:
        cur.execute(f"ALTER TABLE shadow_trades ADD COLUMN {col} {coltype}")
        log.info(f"Added legacy column: {col}")
        return True
    except sqlite3.OperationalError:
        return False


def _ensure_legacy_columns(cur):
    for col, typ in [
        ("legacy_pnl_pct", "REAL"),
        ("legacy_pnl_r", "REAL"),
        ("legacy_exit_reason", "TEXT"),
        ("legacy_duration_minutes", "INTEGER"),
        ("legacy_pnl_pct_method", "TEXT"),
        ("reset_attempted_at", "TEXT"),
        ("unrecoverable_reason", "TEXT"),
    ]:
        _add_column_if_missing(cur, col, typ)


def reset_legacy_finals():
    if not CONFIRM and not DRY_RUN:
        log.error("=" * 60)
        log.error("REFUSING TO RUN")
        log.error("Set CONFIRM_RESET=YES to proceed, or DRY_RUN=YES to preview")
        log.error("=" * 60)
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    _ensure_legacy_columns(cur)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).isoformat()

    # Legacy trades: FINAL, BUY, not already v9.0
    rows = cur.execute("""
        SELECT id, symbol, ts, pnl_pct, pnl_r, exit_reason, duration_minutes,
               pnl_pct_method, outcome_status
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND decision = 'BUY'
          AND (pnl_pct_method IS NULL OR pnl_pct_method != 'simulated_v9.0')
        ORDER BY id ASC
    """).fetchall()

    if not rows:
        log.info("No legacy FINAL trades found — nothing to reset")
        conn.close()
        return 0

    log.info(f"Found {len(rows)} legacy FINAL trades")

    # Split by age
    recent = []      # <= MAX_AGE_HOURS — will reset
    old = []         # > MAX_AGE_HOURS — will mark UNRECOVERABLE

    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_hours <= MAX_AGE_HOURS:
                recent.append((r, age_hours))
            else:
                old.append((r, age_hours))
        except Exception as e:
            log.warning(f"id={r['id']}: cannot parse ts={r['ts']}: {e} — treating as old")
            old.append((r, None))

    log.info(f"  ├─ Recent (<= {MAX_AGE_HOURS}h): {len(recent)} → will RESET")
    log.info(f"  └─ Old    (>  {MAX_AGE_HOURS}h): {len(old)} → will mark UNRECOVERABLE")

    if DRY_RUN:
        log.info("=" * 60)
        log.info("DRY RUN — no changes made")
        log.info("=" * 60)
        log.info("\nWould RESET:")
        for r, age in recent[:20]:
            log.info(f"  id={r['id']:4d} {r['symbol']:12s} age={age:.1f}h pnl_r={r['pnl_r']} ({r['pnl_pct_method']})")
        if len(recent) > 20:
            log.info(f"  ... and {len(recent) - 20} more")
        log.info("\nWould MARK UNRECOVERABLE:")
        for r, age in old[:10]:
            age_str = f"{age:.1f}h" if age is not None else "unknown"
            log.info(f"  id={r['id']:4d} {r['symbol']:12s} age={age_str} pnl_r={r['pnl_r']}")
        if len(old) > 10:
            log.info(f"  ... and {len(old) - 10} more")
        conn.close()
        return len(recent)

    now_str = datetime.now(timezone.utc).isoformat()

    # ── Reset recent trades to ACTIVE ──────────────────────
    reset_count = 0
    for r, age in recent:
        cur.execute("""
            UPDATE shadow_trades
            SET legacy_pnl_pct = pnl_pct,
                legacy_pnl_r = pnl_r,
                legacy_exit_reason = exit_reason,
                legacy_duration_minutes = duration_minutes,
                legacy_pnl_pct_method = pnl_pct_method,
                reset_attempted_at = ?,
                outcome_status = 'ACTIVE',
                outcome_checked = 0,
                status = 'Pending ⏳ (recompute)',
                trade_state = 'ACTIVE',
                pnl_pct = NULL,
                pnl_r = NULL,
                pnl_pct_net = NULL,
                pnl_r_net = NULL,
                mfe_r = NULL,
                mae_r = NULL,
                exit_reason = NULL,
                final_exit_price = NULL,
                final_exit_time = NULL,
                realized_pnl_pct = NULL,
                sl_type_at_exit = NULL,
                pnl_pct_method = NULL
            WHERE id = ?
        """, (now_str, r["id"]))
        reset_count += 1

    # ── Mark old trades as UNRECOVERABLE ────────────────────
    unrecoverable_count = 0
    for r, age in old:
        age_str = f"{age:.0f}h" if age is not None else "unknown"
        cur.execute("""
            UPDATE shadow_trades
            SET legacy_pnl_pct = pnl_pct,
                legacy_pnl_r = pnl_r,
                legacy_exit_reason = exit_reason,
                legacy_duration_minutes = duration_minutes,
                legacy_pnl_pct_method = pnl_pct_method,
                outcome_status = 'UNRECOVERABLE',
                status = 'Unrecoverable ⚠️',
                unrecoverable_reason = ?,
                outcome_checked = 1
            WHERE id = ?
        """, (f"age={age_str} > {MAX_AGE_HOURS}h — no candles available", r["id"]))
        unrecoverable_count += 1

    conn.commit()
    conn.close()

    log.info("=" * 60)
    log.info(f"RESET COMPLETE")
    log.info(f"  Reset to ACTIVE:      {reset_count} (will be re-computed)")
    log.info(f"  Marked UNRECOVERABLE: {unrecoverable_count} (excluded from stats)")
    log.info("=" * 60)
    log.info("NEXT STEP: python main.py --once")
    log.info("  This will fetch candles + recompute PnL for the reset trades")

    return reset_count


if __name__ == "__main__":
    reset_legacy_finals()
