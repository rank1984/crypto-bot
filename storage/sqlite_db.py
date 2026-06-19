"""
CRYPTO-BOT Elite — Storage Engine

שומר כל סריקה ל-SQLite. אחרי חודש — עשרות אלפי שורות.
זה הבסיס ל-Probability Engine.

Schema:
    scans  — כל סריקה שנשלחה לטלגרם
    signals — כל מטבע שעבר threshold בכל סריקה
"""
import sqlite3
import os
from datetime import datetime
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/history.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """יצירת הטבלאות אם לא קיימות."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT    NOT NULL,
                symbol        TEXT    NOT NULL,
                price         REAL,
                regime        TEXT,
                -- Volume
                rvol          REAL,
                vol_accel     REAL,
                dollar_volume REAL,
                -- Momentum
                momentum_3m   REAL,
                momentum_5m   REAL,
                momentum_15m  REAL,
                momentum_1h   REAL,
                -- Indicators
                vwap_dist     REAL,
                rsi_14        REAL,
                atr_14        REAL,
                -- Relative Strength
                rs_1h         REAL,
                rs_4h         REAL,
                -- Scores
                freshness_score REAL,
                momentum_score  REAL,
                breakout_score  REAL,
                final_score     REAL,
                -- Sympathy
                is_sympathy_play INTEGER DEFAULT 0,
                leader_symbol    TEXT,
                -- Future returns (מתמלא בסריקה הבאה)
                ret_5m          REAL,
                ret_15m         REAL,
                ret_30m         REAL,
                ret_1h          REAL,
                ret_4h          REAL
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_ts
            ON signals(ts)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_symbol
            ON signals(symbol)
        """)
        log.info("DB initialized")


def save_signal(coin: dict, regime: str = "RANGE",
                is_sympathy: bool = False,
                leader: str = "") -> int:
    """
    שומר signal לDB. מחזיר row id.
    """
    ts = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO signals (
                ts, symbol, price, regime,
                rvol, vol_accel, dollar_volume,
                momentum_3m, momentum_5m, momentum_15m, momentum_1h,
                vwap_dist, rsi_14, atr_14,
                rs_1h, rs_4h,
                freshness_score, momentum_score, breakout_score, final_score,
                is_sympathy_play, leader_symbol
            ) VALUES (
                ?,?,?,?,
                ?,?,?,
                ?,?,?,?,
                ?,?,?,
                ?,?,
                ?,?,?,?,
                ?,?
            )
        """, (
            ts, coin["symbol"], coin.get("price"), regime,
            coin.get("rvol"), coin.get("vol_accel"), coin.get("dollar_volume"),
            coin.get("momentum_3m"), coin.get("momentum_5m"),
            coin.get("momentum_15m"), coin.get("momentum_1h"),
            coin.get("vwap_dist"), coin.get("rsi_14"), coin.get("atr_14"),
            coin.get("rs_1h"), coin.get("rs_4h"),
            coin.get("freshness_score"), coin.get("momentum_score"),
            coin.get("breakout_score"), coin.get("final_score"),
            int(is_sympathy), leader,
        ))
        return cur.lastrowid


def update_returns(row_id: int, returns: dict) -> None:
    """
    מעדכן את ה-future returns אחרי שהם ידועים.
    returns = {"5m": 1.2, "15m": 2.3, "30m": -0.5, "1h": 3.1, "4h": 5.2}
    """
    with _conn() as c:
        c.execute("""
            UPDATE signals SET
                ret_5m=?, ret_15m=?, ret_30m=?, ret_1h=?, ret_4h=?
            WHERE id=?
        """, (
            returns.get("5m"), returns.get("15m"),
            returns.get("30m"), returns.get("1h"), returns.get("4h"),
            row_id,
        ))


def get_stats(min_score: float = 65.0) -> dict:
    """
    מחזיר סטטיסטיקות בסיסיות על הסריקות ההיסטוריות.
    """
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM signals WHERE final_score >= ?", (min_score,)
        ).fetchone()[0]

        if total == 0:
            return {"total": 0}

        win_1h = c.execute("""
            SELECT COUNT(*) FROM signals
            WHERE final_score >= ? AND ret_1h > 1.0
        """, (min_score,)).fetchone()[0]

        avg_ret_1h = c.execute("""
            SELECT AVG(ret_1h) FROM signals
            WHERE final_score >= ? AND ret_1h IS NOT NULL
        """, (min_score,)).fetchone()[0] or 0

        return {
            "total":        total,
            "win_rate_1h":  round(win_1h / total * 100, 1) if total > 0 else 0,
            "avg_ret_1h":   round(avg_ret_1h, 3),
        }


if __name__ == "__main__":
    init_db()
    stats = get_stats()
    print(f"DB stats: {stats}")
