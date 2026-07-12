"""
CRYPTO-BOT Elite — Shadow Mode & Trade Tracker

הבוט רץ בשקט, שומר את כל משתני המטבע בנקודת ההחלטה למסד נתונים, 
ובודק כל 5 דקות מול בינאנס האם העסקאות הגיעו ל-TP1 או ל-SL.
בסוף, מייצא CSV מסודר לאנליזה.
"""
import os
import sqlite3
import csv
import requests
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_shadow_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                decision TEXT,
                setup TEXT,
                entry_price REAL,
                tp1 REAL,
                tp2 REAL,
                sl REAL,
                ai_score REAL,
                flow_score REAL,
                pre_score REAL,
                oi_change REAL,
                rs_1h REAL,
                is_compressed TEXT,
                status TEXT,
                reason TEXT
            )
        """)
    log.info("Shadow DB initialized for Trade Tracking")
    
    # מפעיל אוטומטית עדכון מעקב פוזיציות וייצוא CSV בתחילת כל סריקה!
    try:
        update_open_trades()
        export_shadow_csv()
    except Exception as e:
        log.error(f"Shadow Engine Error: {e}")

def save_shadow_signal(coin: dict, signal: str):
    # פונקציית Legacy למקרה ש-main.py עדיין קורא לה, מונעת קריסה.
    pass

def record_trade(coin: dict, signal):
    """נקרת ישירות מתוך entry_engine ברגע ההחלטה"""
    if signal.decision not in ["BUY", "WAIT", "NO"]: 
        return
        
    ts = datetime.now(timezone.utc).isoformat()
    
    # קביעת סטטוס התחלתי
    initial_status = "Pending ⏳" if signal.decision == "BUY" else "-"
    
    with _conn() as c:
        c.execute("""
            INSERT INTO shadow_trades (
                ts, symbol, decision, setup, entry_price, tp1, tp2, sl,
                ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts,
            coin.get("symbol", "UNKNOWN"),
            signal.decision,
            signal.setup_type,
            signal.entry,
            signal.tp1,
            signal.tp2,
            signal.sl,
            coin.get("ai_score", 0),
            coin.get("flow_score", 0),
            coin.get("pre_score", 0),
            coin.get("oi_change", 0),
            coin.get("rs_1h", 0),
            str(coin.get("is_compressed", False)),
            initial_status,
            signal.reason
        ))

def _get_binance_price(symbol: str) -> float:
    try:
        # פניה חינמית לבינאנס שלא דורשת מפתחות API
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        data = r.json()
        return float(data.get("price", 0.0))
    except:
        return 0.0

def update_open_trades():
    with _conn() as c:
        open_trades = c.execute("SELECT * FROM shadow_trades WHERE status = 'Pending ⏳'").fetchall()
        
    updated_count = 0
    for trade in open_trades:
        current_price = _get_binance_price(trade["symbol"])
        if current_price <= 0: continue
        
        new_status = "Pending ⏳"
        if trade["tp1"] > 0 and current_price >= trade["tp1"]:
            new_status = "TP1 Hit 🎯"
        elif trade["sl"] > 0 and current_price <= trade["sl"]:
            new_status = "SL Hit 🛑"
        else:
            trade_time = datetime.fromisoformat(trade["ts"])
            if datetime.now(timezone.utc) - trade_time > timedelta(hours=24):
                new_status = "Timeout ⏱️"
                
        if new_status != "Pending ⏳":
            with _conn() as c:
                c.execute("UPDATE shadow_trades SET status = ? WHERE id = ?", (new_status, trade["id"]))
            updated_count += 1
            
    if updated_count > 0:
        log.info(f"Shadow Tracker: Updated {updated_count} trades with new outcomes (TP/SL).")

def export_shadow_csv():
    filepath = "shadow_results.csv"
    with _conn() as c:
        trades = c.execute("SELECT * FROM shadow_trades ORDER BY id DESC").fetchall()
        
    with open(filepath, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Coin", "Decision", "Setup", "Entry", "TP1", "SL", "AI", "Flow", "Pre", "OI", "RS", "Compression", "Status", "Reason"])
        
        for t in trades:
            dt_str = datetime.fromisoformat(t["ts"]).strftime("%H:%M:%S") if t["ts"] else ""
            writer.writerow([
                dt_str, t["symbol"], t["decision"], t["setup"], 
                t["entry_price"], t["tp1"], t["sl"],
                t["ai_score"], t["flow_score"], t["pre_score"], 
                t["oi_change"], t["rs_1h"], t["is_compressed"], 
                t["status"], t["reason"]
            ])
