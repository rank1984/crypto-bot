"""
tools/reset_legacy_finals.py — הרצה חד-פעמית
מאפס עסקאות FINAL שחושבו תחת גרסת V8 ישנה (לא V8.6),
כדי שיעברו עיבוד מחדש עם הסימולציה הנוכחית (עם תיקון is_closed/now_ts).
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger("reset_legacy_finals")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

CURRENT_VERSION = "simulated_v8.6"


def reset_legacy():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, symbol, pnl_pct_method FROM shadow_trades
        WHERE decision='BUY' AND outcome_status='FINAL'
          AND (pnl_pct_method IS NULL OR pnl_pct_method != ?)
    """, (CURRENT_VERSION,)).fetchall()

    log.info(f"Found {len(rows)} legacy-finalized trades not on {CURRENT_VERSION}")
    for r in rows:
        log.info(f"  resetting id={r['id']} symbol={r['symbol']} old_method={r['pnl_pct_method']}")

    cur.execute("""
        UPDATE shadow_trades
        SET outcome_status='ACTIVE', outcome_checked=0
        WHERE decision='BUY' AND outcome_status='FINAL'
          AND (pnl_pct_method IS NULL OR pnl_pct_method != ?)
    """, (CURRENT_VERSION,))

    conn.commit()
    conn.close()
    log.info(f"Reset {len(rows)} trades back to ACTIVE for V8.6 reprocessing")
    return len(rows)


if __name__ == "__main__":
    reset_legacy()
