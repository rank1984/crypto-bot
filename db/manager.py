import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = "db/crypto_bot.db"
EXPORT_DIR = "exports/"

def init_db():
    """מאתחל את בסיס הנתונים והטבלאות על בסיס הארכיטקטורה שהגדרת"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. טבלת המטבעות שנפסלו
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS filtered_coins (
            timestamp TEXT,
            symbol TEXT,
            final_score REAL,
            flow_score REAL,
            pre_score REAL,
            rvol REAL,
            oi_change REAL,
            rs_1h REAL,
            rs_4h REAL,
            is_compressed INTEGER,
            whale_detected INTEGER,
            reason_filtered TEXT
        )
    ''')
    
    # [כאן יבואו בהמשך שאר הטבלאות: winners, trade_log, replay_results]
    
    conn.commit()
    conn.close()

def log_filtered_coin(data: dict):
    """שומר מטבע שנפסל בזמן אמת"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        INSERT INTO filtered_coins 
        VALUES (:timestamp, :symbol, :final_score, :flow_score, :pre_score, 
                :rvol, :oi_change, :rs_1h, :rs_4h, :is_compressed, :whale_detected, :reason_filtered)
    '''
    cursor.execute(query, data)
    conn.commit()
    conn.close()

def export_daily_csv():
    """מייצא את נתוני היום הנוכחי לקובץ CSV נקי"""
    today_str = datetime.now().strftime("%Y_%m_%d")
    csv_filename = f"{EXPORT_DIR}filtered_coins_{today_str}.csv"
    
    conn = sqlite3.connect(DB_PATH)
    # שליפת המידע של היום בלבד על בסיס ה-Timestamp
    query = "SELECT * FROM filtered_coins WHERE date(timestamp) = date('now')"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if not df.empty:
        df.to_csv(csv_filename, index=False)
        print(f"✓ Daily export saved to {csv_filename}")
