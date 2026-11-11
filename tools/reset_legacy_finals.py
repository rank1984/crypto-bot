"""
Reset FINAL trades to ACTIVE for re-computation by tracker v9.0.

SAFETY:
  - Only resets trades where pnl_pct_method != 'simulated_v9.0'
  - Backs up old values to *_legacy columns (added on first run)
  - Requires CONFIRM_RESET=YES env var to proceed
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger("reset_legacy")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _add_column_if_missing(cur, col, coltype):
    try:
        cur.execute(f"ALTER TABLE shadow_trades ADD COLUMN {col} {coltype}")
        log.info(f"Added legacy column: {col}")
    except sqlite3.OperationalError:
        pass


def reset_legacy_finals():
    if os.getenv("CONFIRM_RESET") != "YES":
        log.error("CONFIRM_RESET != YES — refusing to reset. Set CONFIRM_RESET=YES to proceed.")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Save legacy values before overwrite
    for col, typ in [
        ("legacy_pnl_pct", "REAL"),
        ("legacy_pnl_r", "REAL"),
        ("legacy_exit_reason", "TEXT"),
        ("legacy_duration_minutes", "INTEGER"),
    ]:
        _add_column_if_missing(cur, col, typ)

    rows = cur.execute("""
        SELECT id, pnl_pct, pnl_r, exit_reason, duration_minutes, pnl_pct_method
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND decision = 'BUY'
          AND (pnl_pct_method IS NULL OR pnl_pct_method != 'simulated_v9.0')
    """).fetchall()

    if not rows:
        log.info("No legacy FINAL trades to reset")
        conn.close()
        return 0

    log.warning(f"Resetting {len(rows)} FINAL trades to ACTIVE (will be re-computed)")
    for r in rows:
        cur.execute("""
            UPDATE shadow_trades
            SET legacy_pnl_pct = pnl_pct,
                legacy_pnl_r = pnl_r,
                legacy_exit_reason = exit_reason,
                legacy_duration_minutes = duration_minutes,
                outcome_status = 'ACTIVE',
                outcome_checked = 0,
                status = 'Pending ⏳ (recompute)',
                trade_state = 'ACTIVE'
            WHERE id = ?
        """, (r["id"],))

    conn.commit()
    conn.close()
    log.warning(f"Reset {len(rows)} trades. Now run: python -m tools.outcome_tracker")
    return len(rows)


if __name__ == "__main__":
    reset_legacy_finals()
