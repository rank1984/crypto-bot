"""
tools/backfill_buckets.py — הרצה חד-פעמית
ממלא rs_bucket/ai_bucket לעסקאות היסטוריות שכבר קיימות ב-DB
"""
import os
import sqlite3
from tools.shadow_mode import _rs_bucket, _ai_bucket, export_shadow_csv
from utils.logger import get_logger

log = get_logger("backfill_buckets")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, rs_1h, ai_score FROM shadow_trades
        WHERE rs_bucket IS NULL OR ai_bucket IS NULL OR rs_bucket = '' OR ai_bucket = ''
    """).fetchall()

    log.info(f"Backfilling {len(rows)} rows missing rs_bucket/ai_bucket")

    updated = 0
    for row in rows:
        rs_b = _rs_bucket(row["rs_1h"])
        ai_b = _ai_bucket(row["ai_score"])
        cur.execute(
            "UPDATE shadow_trades SET rs_bucket = ?, ai_bucket = ? WHERE id = ?",
            (rs_b, ai_b, row["id"])
        )
        updated += 1

    conn.commit()
    conn.close()
    log.info(f"Backfill complete: {updated} rows updated")
    export_shadow_csv()


if __name__ == "__main__":
    backfill()
