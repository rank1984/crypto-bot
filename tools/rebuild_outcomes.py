"""
CRYPTO-BOT Elite — Outcomes Rebuilder
Recalculates past FINAL trades utilizing the new V8 Exit Simulator.
Leaves Human Execution data completely intact.
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime
from tools.outcome_tracker import update_outcomes
from utils.logger import get_logger

log = get_logger("rebuild_outcomes")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def rebuild_all_outcomes():
    log.info("Starting Full Rebuild of all BUY trades...")
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # מאפסים בחזרה ל-PENDING רק את שדות ה-Outcome
    # ה-UPDATE אינו פוגע ב-was_executed, execution_delay_sec, actual_fill_price
    cur.execute("""
        UPDATE shadow_trades
        SET 
            outcome_status = 'PENDING',
            outcome_checked = 0,
            pnl_pct_method = 'pending_rebuild'
        WHERE decision = 'BUY' 
          AND entry_price > 0
    """)
    rows_affected = cur.rowcount
    conn.commit()
    conn.close()
    
    log.info(f"Reset {rows_affected} BUY trades to PENDING. Triggering Outcome Tracker V8.1...")
    
    # הרצת מנגנון ה-Tracking המעודכן שלנו
    updated_count = update_outcomes()
    
    log.info(f"Rebuild Complete! Successfully recalculated {updated_count} trades via Exit Simulator.")

if __name__ == "__main__":
    rebuild_all_outcomes()
