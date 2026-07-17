"""
CRYPTO-BOT Elite — Outcome Tracker

מחשב בדיעבד:
- האם הטריגר הופעל
- האם TP1, TP2, SL הושגו
- Max עלייה / Max ירידה
"""
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
from scanner.market_data import get_candles

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
OUTCOME_DELAY_HOURS = 6   # אחרי כמה שעות לבדוק


def update_outcomes():
    """מעדכן תוצאות עבור שורות שטרם נבדקו ועבר להן מספיק זמן."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # בחר שורות עם entry_price > 0, outcome_checked=0, ועברו >= OUTCOME_DELAY_HOURS
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=OUTCOME_DELAY_HOURS)).isoformat()
    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_checked = 0
          AND entry_price > 0
          AND ts <= ?
        ORDER BY id
    """, (cutoff,)).fetchall()

    updated = 0
    for row in rows:
        symbol = row["symbol"]
        entry_price = row["entry_price"]
        trigger_price = row["trigger_price"] or (entry_price * 1.001)  # fallback
        tp1 = row["tp1"] or (entry_price * 1.04)
        tp2 = row["tp2"] or (entry_price * 1.10)
        sl = row["sl"] or (entry_price * 0.98)
        ts_str = row["ts"]

        # משיכת נרות 5m מהזמן של הסריקה ועד עכשיו
        try:
            # get_candles יכול לקבל start/end? נשתמש ב-limit גדול
            df = get_candles(symbol, "5m", limit=72)  # 6 שעות = 72 נרות
        except Exception:
            continue
        if df is None or len(df) < 2:
            continue

        # סינון נרות שאחרי ts_str (אם אפשר)
        try:
            ts_dt = datetime.fromisoformat(ts_str).replace(tzinfo=None)
            df["datetime"] = pd.to_datetime(df["datetime"] if "datetime" in df.columns else df.index)
            df = df[df["datetime"] >= ts_dt]
        except Exception:
            pass

        if len(df) == 0:
            continue

        high_prices = df["high"].astype(float)
        low_prices = df["low"].astype(float)
        close_prices = df["close"].astype(float)

        max_high = high_prices.max()
        min_low = low_prices.min()

        max_up_pct = ((max_high - entry_price) / entry_price) * 100
        max_down_pct = ((min_low - entry_price) / entry_price) * 100

        trigger_hit = 1 if max_high >= trigger_price else 0
        tp1_hit = 1 if max_high >= tp1 else 0
        tp2_hit = 1 if max_high >= tp2 else 0
        sl_hit = 1 if min_low <= sl else 0

        cur.execute("""
            UPDATE shadow_trades
            SET outcome_trigger_hit = ?,
                outcome_tp1_hit = ?,
                outcome_tp2_hit = ?,
                outcome_sl_hit = ?,
                outcome_max_up_pct = ?,
                outcome_max_down_pct = ?,
                outcome_checked = 1
            WHERE id = ?
        """, (trigger_hit, tp1_hit, tp2_hit, sl_hit,
              round(max_up_pct, 2), round(max_down_pct, 2), row["id"]))
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        log.info(f"Outcome tracker: updated {updated} rows")
