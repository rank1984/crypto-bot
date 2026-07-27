import sqlite3, os
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def check():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    missing_entry = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE entry_price=0").fetchone()[0]
    missing_tp = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE outcome_status='FINAL' AND outcome_tp1_hit IS NULL").fetchone()[0]
    missing_sl = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE outcome_status='FINAL' AND outcome_sl_hit IS NULL").fetchone()[0]
    
    print(f"Rows with entry_price=0: {missing_entry}")
    print(f"FINAL rows missing TP1: {missing_tp}")
    print(f"FINAL rows missing SL: {missing_sl}")
