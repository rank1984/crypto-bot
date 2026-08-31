"""
Crypto-Bot — Notification State Manager
ניהול ומעקב אחר מצב ההתראות בטלגרם למניעת הצפת הודעות כפולות.
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger("notification_state")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

AI_CHANGE_THRESHOLD = 5.0
TRIGGER_DIST_THRESHOLD = 1.5
NEAR_TRIGGER_PERCENT = 1.0


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_state (
                key TEXT PRIMARY KEY,
                top_symbol TEXT,
                top_ai_score REAL,
                trigger_dist_pct REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()


_init_db()


def should_send_watch_update(top_coin: dict) -> bool:
    if not top_coin:
        return False

    symbol = top_coin.get("symbol", "")
    ai_score = float(top_coin.get("ai_score", 0) or 0)
    
    trigger_dist = top_coin.get("trigger_distance_pct")
    trigger_dist_val = float(trigger_dist) if trigger_dist is not None else 999.0

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT top_symbol, top_ai_score, trigger_dist_pct FROM notification_state WHERE key='last_watch'"
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO notification_state (key, top_symbol, top_ai_score, trigger_dist_pct)
                   VALUES ('last_watch', ?, ?, ?)""",
                (symbol, ai_score, trigger_dist_val)
            )
            conn.commit()
            return True

        last_symbol = row["top_symbol"]
        last_ai = float(row["top_ai_score"] or 0)
        last_dist = float(row["trigger_dist_pct"]) if row["trigger_dist_pct"] is not None else 999.0

        symbol_changed = last_symbol != symbol
        ai_changed = abs(last_ai - ai_score) >= AI_CHANGE_THRESHOLD
        dist_changed = abs(last_dist - trigger_dist_val) >= TRIGGER_DIST_THRESHOLD
        now_near_trigger = abs(trigger_dist_val) <= NEAR_TRIGGER_PERCENT and abs(last_dist) > NEAR_TRIGGER_PERCENT

        if symbol_changed or ai_changed or dist_changed or now_near_trigger:
            conn.execute(
                """UPDATE notification_state 
                   SET top_symbol=?, top_ai_score=?, trigger_dist_pct=?, updated_at=CURRENT_TIMESTAMP 
                   WHERE key='last_watch'""",
                (symbol, ai_score, trigger_dist_val)
            )
            conn.commit()
            log.info(
                f"Watch update triggered: symbol_changed={symbol_changed}, "
                f"ai_changed={ai_changed}, dist_changed={dist_changed}, near_trigger={now_near_trigger}"
            )
            return True

        log.info(f"Watch update skipped: {symbol} AI={ai_score} dist={trigger_dist_val:.2f}% unchanged")
        return False
