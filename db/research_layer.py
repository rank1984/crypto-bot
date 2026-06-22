import sqlite3
import os
from datetime import datetime

DB_PATH = "db/crypto_bot.db"

def init_research_db():
    """מאתחל את בסיס הנתונים ומקים את 4 טבלאות המחקר האסטרטגיות"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. טבלת מטבעות שנפסלו בשומר הסף (Hard Filters)
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
            is_compressed INTEGER,
            whale_detected INTEGER,
            reason_filtered TEXT
        )
    ''')
    
    # 2. טבלת המנצחים הגדולים של השוק בפועל (מקור האמת החיצוני)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            symbol TEXT,
            date TEXT,
            move_pct REAL,
            anchor_time TEXT
        )
    ''')
    
    # 3. טבלת תוצאות ה-Replay Engine בנקודות זמן קריטיות לאחור
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS replay_results (
            symbol TEXT,
            hours_before INTEGER,
            final_score REAL,
            flow_score REAL,
            pre_score REAL,
            signal TEXT
        )
    ''')
    
    # 4. יומן הטריידים המלא (נרשם רק בפקודות BUY אקטיביות)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_log (
            timestamp TEXT,
            symbol TEXT,
            entry_price REAL,
            stop_price REAL,
            tp1 REAL,
            tp2 REAL,
            confidence REAL,
            position_size REAL,
            future_return_1h REAL,
            future_return_4h REAL,
            future_return_24h REAL,
            max_runup REAL,
            max_drawdown REAL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✓ SQLite Research Layer initialized with 4 core tables.")

# --- פונקציות הזרקת נתונים קריטיות ---

def log_filtered_coin(data: dict):
    """רישום מטבע שנפסל בזמן אמת או בריצת סימולציה"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = '''
        INSERT INTO filtered_coins VALUES 
        (:timestamp, :symbol, :final_score, :flow_score, :pre_score, 
         :rvol, :oi_change, :rs_1h, :is_compressed, :whale_detected, :reason_filtered)
    '''
    cursor.execute(query, data)
    conn.commit()
    conn.close()

def log_actual_winner(symbol: str, date: str, move_pct: float, anchor_time: str):
    """רישום ידני או אוטומטי של מטבע שהשלים תנועה חריגה בשוק"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO winners VALUES (?, ?, ?, ?)",
        (symbol, date, move_pct, anchor_time)
    )
    conn.commit()
    conn.close()

# --- מנוע הניתוח והסקת המסקנות ---

def analyze_opportunity_cost():
    """
    מריץ את שאילתת ה-JOIN האסטרטגית כדי לחשב במדויק
    אילו פילטרים קשיחים עלו לנו בהפסד של מטבעות מנצחים
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            f.reason_filtered,
            COUNT(DISTINCT w.symbol) as missed_winners,
            ROUND(AVG(w.move_pct), 2) as avg_move_pct
        FROM filtered_coins f
        JOIN winners w ON f.symbol = w.symbol
        GROUP BY f.reason_filtered
        ORDER BY missed_winners DESC;
    '''
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    print("\n" + "="*50)
    print("        RESEARCH REPORT: OPPORTUNITY COST")
    print("="*50)
    print(f"{'Reason Filtered':<20} | {'Missed Winners':<14} | {'Avg Move %':<10}")
    print("-"*50)
    for row in results:
        print(f"{row[0]:<20} | {row[1]:<14} | {row[2]}%")
    print("="*50 + "\n")
    return results
