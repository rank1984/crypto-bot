"""
tools/notification_state.py
שומר את מצב ההתראה האחרונה כדי למנוע שליחת הודעות כפולות/דומות.
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger("notification_state")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

AI_CHANGE_THRESHOLD = 5  # נקודות AI Score שמצדיקות הודעה חדשה


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_state (
            key TEXT PRIMARY KEY,
            top_symbol TEXT,
            top_ai_score REAL
        )
    """)


def should_send_watch_update(top_coin: dict) -> bool:
    """
    מחזיר True אם צריך לשלוח הודעת WATCH (משהו השתנה מהותית),
    False אם המצב זהה למה שכבר נשלח - כדי לא להציף.
    """
    if not top_coin:
        return False

    symbol = top_coin.get("symbol", "")
    ai_score = float(top_coin.get("ai_score", 0) or 0)

    with _conn() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT top_symbol, top_ai_score FROM notification_state WHERE key='last_watch'"
        ).fetchone()

        if row is None:
            # אף פעם לא נשלחה הודעה - שולחים ושומרים
            conn.execute(
                "INSERT INTO notification_state (key, top_symbol, top_ai_score) VALUES ('last_watch', ?, ?)",
                (symbol, ai_score)
            )
            return True

        symbol_changed = row["top_symbol"] != symbol
        ai_changed = abs((row["top_ai_score"] or 0) - ai_score) >= AI_CHANGE_THRESHOLD

        if symbol_changed or ai_changed:
            conn.execute(
                "UPDATE notification_state SET top_symbol=?, top_ai_score=? WHERE key='last_watch'",
                (symbol, ai_score)
            )
            log.info(f"Watch update triggered: symbol_changed={symbol_changed}, ai_changed={ai_changed}")
            return True

        log.info(f"Watch update skipped: {symbol} AI={ai_score} unchanged from last notification")
        return False