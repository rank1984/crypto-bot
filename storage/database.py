"""
CRYPTO-BOT Elite — Storage Engine
מנהל את בסיס הנתונים SQLite לשמירת סריקות וניתוח היסטורי.
"""
import os
import sqlite3
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

# הגדרת נתיב דינמי לקובץ ה-DB באותה תיקייה של הקובץ הנוכחי
DB_PATH = os.path.join(os.path.dirname(__file__), "scans.db")


def get_connection():
    """מייצר חיבור לבסיס הנתונים עם תמיכה בהחזרת שורות כמילונים"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """מאתחל את הטבלאות והאינדקסים במידה ואינם קיימים"""
    query = """
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        symbol TEXT,
        price REAL,

        mom_3m REAL,
        mom_5m REAL,
        mom_15m REAL,
        mom_1h REAL,

        rvol REAL,
        vol_accel REAL,

        vwap_dist REAL,
        rsi14 REAL,

        freshness_score REAL,
        momentum_score REAL,
        breakout_score REAL,
        pattern_score REAL,

        final_score REAL
    );
    """
    try:
        with get_connection() as conn:
            conn.execute(query)
            # יצירת אינדקסים לחיפושים מהירים בעתיד
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_symbol ON scans(symbol);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);")
            conn.commit()
        log.info("Database initialized successfully ✓")
    except Exception as e:
        log.error(f"Failed to initialize database: {e}")


def _extract_row_data(row: dict) -> tuple:
    """פונקציית עזר הממפה ומחלצת את הנתונים מתוך המילון של הבוט לעמודות ה-DB"""
    # יצירת חותמת זמן אם לא קיימת בנתונים הגולמיים
    timestamp = row.get("timestamp", datetime.utcnow().isoformat())
    
    return (
        timestamp,
        row.get("symbol"),
        row.get("price"),
        # תמיכה בכתיבה מקוצרת או מלאה של המפתחות לביטחון
        row.get("mom_3m", row.get("momentum_3m", 0.0)),
        row.get("mom_5m", row.get("momentum_5m", 0.0)),
        row.get("mom_15m", row.get("momentum_15m", 0.0)),
        row.get("mom_1h", row.get("momentum_1h", 0.0)),
        row.get("rvol", 0.0),
        row.get("vol_accel", 0.0),
        row.get("vwap_dist", 0.0),
        row.get("rsi14", row.get("rsi_14", 50.0)),
        row.get("freshness_score", 0.0),
        row.get("momentum_score", 0.0),
        row.get("breakout_score", 0.0),
        row.get("pattern_score", 0.0),
        row.get("final_score", 0.0)
    )


def save_scan(row: dict) -> bool:
    """שומר שורת סריקה בודדת"""
    query = """
    INSERT INTO scans (
        timestamp, symbol, price, mom_3m, mom_5m, mom_15m, mom_1h,
        rvol, vol_accel, vwap_dist, rsi14, freshness_score,
        momentum_score, breakout_score, pattern_score, final_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        data = _extract_row_data(row)
        with get_connection() as conn:
            conn.execute(query, data)
            conn.commit()
        return True
    except Exception as e:
        log.error(f"Failed to save single scan for {row.get('symbol')}: {e}")
        return False


def save_scan_batch(rows: list[dict]) -> int:
    """
    שומר רשימה של סריקות בפעימה אחת (Batch) בצורה יעילה ומהירה
    מחזיר את מספר השורות שנשמרו בהצלחה.
    """
    if not rows:
        return 0

    query = """
    INSERT INTO scans (
        timestamp, symbol, price, mom_3m, mom_5m, mom_15m, mom_1h,
        rvol, vol_accel, vwap_dist, rsi14, freshness_score,
        momentum_score, breakout_score, pattern_score, final_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        data_batch = [_extract_row_data(row) for row in rows]
        with get_connection() as conn:
            cursor = conn.executemany(query, data_batch)
            conn.commit()
            count = cursor.rowcount
        log.info(f"Saved batch of {count} scans to database ✓")
        return count
    except Exception as e:
        log.error(f"Failed to save scan batch: {e}")
        return 0


def get_history(symbol: str, days: int = 30) -> list[dict]:
    """שולף היסטוריית סריקות עבור מטבע ספציפי X ימים אחורה"""
    cutoff_time = (datetime.utcnow() - timedelta(days=days)).isoformat()
    query = """
    SELECT * FROM scans 
    WHERE symbol = ? AND timestamp >= ? 
    ORDER BY timestamp ASC
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(query, (symbol, cutoff_time)).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        log.error(f"Failed to fetch history for {symbol}: {e}")
        return []


def get_top_history(limit: int = 1000) -> list[dict]:
    """שולף את הסריקות המובילות ביותר שנרשמו במערכת (לפי הציון הסופי)"""
    query = "SELECT * FROM scans ORDER BY final_score DESC LIMIT ?"
    try:
        with get_connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        log.error(f"Failed to fetch top history: {e}")
        return []
