"""
Mark ACTIVE trades that failed recomputation as UNRECOVERABLE.

Run this AFTER 'main.py --once' if you want to clean up stats.
Only marks trades that have been ACTIVE for > 24h with reset_attempted_at set.
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from utils.logger import get_logger

log = get_logger("mark_unrecoverable")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

MIN_AGE_HOURS = int(os.getenv("MIN_AGE_HOURS", "24"))
CONFIRM = os.getenv("CONFIRM_MARK") == "YES"
DRY_RUN = os.getenv("DRY_RUN") == "YES"


def mark_unrecoverable():
    if not CONFIRM and not DRY_RUN:
        log.error("Set CONFIRM_MARK=YES or DRY_RUN=YES")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MIN_AGE_HOURS)).isoformat()

    rows = cur.execute("""
        SELECT id, symbol, ts, reset_attempted_at, pnl_pct, pnl_r
        FROM shadow_trades
        WHERE outcome_status = 'ACTIVE'
          AND decision = 'BUY'
          AND reset_attempted_at IS NOT NULL
          AND reset_attempted_at < ?
          AND (pnl_pct IS NULL OR pnl_pct_net IS NULL)
        ORDER BY id ASC
    """, (cutoff,)).fetchall()

    if not rows:
        log.info(f"No unrecoverable trades found (older than {MIN_AGE_HOURS}h)")
        conn.close()
        return 0

    log.warning(f"Found {len(rows)} trades still ACTIVE after reset (no candles)")

    if DRY_RUN:
        for r in rows[:20]:
            log.info(f"  id={r['id']:4d} {r['symbol']:12s} reset_at={r['reset_attempted_at']}")
        if len(rows) > 20:
            log.info(f"  ... and {len(rows) - 20} more")
        conn.close()
        return len(rows)

    for r in rows:
        cur.execute("""
            UPDATE shadow_trades
            SET outcome_status = 'UNRECOVERABLE',
                status = 'Unrecoverable ⚠️',
                unrecoverable_reason = ?,
                outcome_checked = 1
            WHERE id = ?
        """, (f"reset at {r['reset_attempted_at']} but no candles found", r["id"]))

    conn.commit()
    conn.close()

    log.info(f"Marked {len(rows)} trades as UNRECOVERABLE")
    return len(rows)


if __name__ == "__main__":
    mark_unrecoverable()
