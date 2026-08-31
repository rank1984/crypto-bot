"""
tools/reset_legacy_finals.py
Reset only FINAL trades that were NOT computed by V8+ (legacy).
Sets outcome_status='PENDING', outcome_checked=0 so update_outcomes() will recalculate them.
"""

import os
import sqlite3
from utils.logger import get_logger

log = get_logger("reset_legacy_finals")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def reset_legacy_finals():
    """
    Reset all FINAL trades that are not V8 (i.e., pnl_pct_method is NULL or not 'simulated_v8%')
    back to PENDING so they can be recalculated by the current V8 outcome tracker.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Audit query: count legacy vs V8
    cur.execute("""
        SELECT
            COUNT(*) AS total_final,
            SUM(CASE WHEN pnl_pct_method LIKE 'simulated_v8%' THEN 1 ELSE 0 END) AS v8,
            SUM(CASE WHEN pnl_pct_method IS NULL
                      OR pnl_pct_method NOT LIKE 'simulated_v8%'
                     THEN 1 ELSE 0 END) AS legacy
        FROM shadow_trades
        WHERE decision='BUY'
          AND outcome_status='FINAL'
          AND outcome_checked=1
    """)
    row = cur.fetchone()
    total, v8, legacy = row[0], row[1], row[2]
    log.info(f"Audit: total FINAL={total}, V8={v8}, legacy={legacy}")

    if legacy == 0:
        log.info("No legacy FINAL trades to reset.")
        conn.close()
        return 0

    # Reset only legacy FINAL trades to PENDING
    cur.execute("""
        UPDATE shadow_trades
        SET outcome_status='PENDING',
            outcome_checked=0,
            pnl_pct_method=NULL,
            pnl_r=NULL,
            mfe_r=NULL,
            mae_r=NULL,
            first_outcome_type=NULL,
            outcome_tp1_hit=0,
            outcome_tp2_hit=0,
            outcome_sl_hit=0,
            outcome_mfe=NULL,
            outcome_mae=NULL,
            outcome_max_up_pct=NULL,
            outcome_max_down_pct=NULL,
            ambiguous_bar=0,
            entry_candle_ambiguous=0,
            last_update_time=NULL
        WHERE decision='BUY'
          AND outcome_status='FINAL'
          AND outcome_checked=1
          AND (pnl_pct_method IS NULL OR pnl_pct_method NOT LIKE 'simulated_v8%')
    """)
    updated = cur.rowcount
    conn.commit()
    conn.close()

    log.info(f"Reset {updated} legacy FINAL trades back to PENDING")
    return updated


if __name__ == "__main__":
    reset_legacy_finals()
