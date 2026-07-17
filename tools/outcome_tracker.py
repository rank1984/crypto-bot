"""
CRYPTO-BOT Elite — Outcome Tracker (v2)

- קורא אוטומטית שורות שלא נבדקו מ-shadow_trades
- משתמש בזמן האיתות האמיתי (ts) לחישוב חלון
- מחשב MFE, MAE, זמני טריגר, TP1, TP2
- שומר Highest / Lowest Price
"""
import sqlite3
import os
import pandas as pd
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
from scanner.market_data import get_candles

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
LOOKBACK_HOURS = 12         # חלון בדיקה לאחור (שעות מהאיתות)


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # בחר שורות עם entry_price>0, outcome_checked=0, ועברו מספיק זמן (12h)
    # מעבדים את כל השורות שלא נבדקו (ללא תלות בזמן)
    rows = cur.execute("""
    SELECT * FROM shadow_trades
    WHERE outcome_checked = 0
      AND entry_price > 0
    ORDER BY id
    LIMIT 50
    """).fetchall()

    updated = 0
    for row in rows:
        symbol = row["symbol"]
        entry_price = row["entry_price"]
        trigger_price = row["trigger_price"] or (entry_price * 1.001)
        tp1 = row["tp1"] or (entry_price * 1.04)
        tp2 = row["tp2"] or (entry_price * 1.10)
        sl = row["sl"] or (entry_price * 0.98)

        # זמן האיתות
        try:
            alert_time = datetime.fromisoformat(row["ts"]).replace(tzinfo=None)
        except:
            continue

        # משיכת נרות 5m – מכסה את כל התקופה מהאיתות ועד עכשיו (מקסימום LOOKBACK_HOURS)
        try:
            # נבקש נרות ב‑limit גבוה (12h * 12 נרות לשעה = 144)
            df = get_candles(symbol, "5m", limit=144)
        except Exception as e:
            log.warning(f"Cannot fetch candles for {symbol}: {e}")
            continue

        if df is None or len(df) < 2:
            continue

        # המרת אינדקס ל‑datetime
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        else:
            df["datetime"] = pd.to_datetime(df.index)
        df = df.sort_values("datetime")

        # סינון נרות שאחרי זמן האיתות
        df = df[df["datetime"] >= alert_time]
        if df.empty:
            continue

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        times = df["datetime"]

        max_high = high.max()
        min_low = low.min()
        max_up_pct = round((max_high - entry_price) / entry_price * 100, 2)
        max_down_pct = round((min_low - entry_price) / entry_price * 100, 2)

        # בדיקת חציית רמות
        trigger_hit = int(max_high >= trigger_price)
        tp1_hit = int(max_high >= tp1)
        tp2_hit = int(max_high >= tp2)
        sl_hit = int(min_low <= sl)

        # זמני חצייה (דקות מהאיתות)
        def time_to_hit(level, price_series, times_series, direction="high"):
            if direction == "high":
                mask = price_series >= level
            else:
                mask = price_series <= level
            if mask.any():
                first_time = times_series[mask].iloc[0]
                return round((first_time - alert_time).total_seconds() / 60, 1)
            return None

        trigger_min = time_to_hit(trigger_price, high, times, "high") if trigger_hit else None
        tp1_min = time_to_hit(tp1, high, times, "high") if tp1_hit else None
        tp2_min = time_to_hit(tp2, high, times, "high") if tp2_hit else None
        sl_min = time_to_hit(sl, low, times, "low") if sl_hit else None

        # עדכון הטבלה
        cur.execute("""
            UPDATE shadow_trades
            SET outcome_trigger_hit = ?,
                outcome_tp1_hit = ?,
                outcome_tp2_hit = ?,
                outcome_sl_hit = ?,
                outcome_max_up_pct = ?,
                outcome_max_down_pct = ?,
                outcome_checked = 1,
                outcome_trigger_min = ?,
                outcome_tp1_min = ?,
                outcome_tp2_min = ?,
                outcome_sl_min = ?,
                outcome_highest_price = ?,
                outcome_lowest_price = ?
            WHERE id = ?
        """, (
            trigger_hit, tp1_hit, tp2_hit, sl_hit,
            max_up_pct, max_down_pct,
            trigger_min, tp1_min, tp2_min, sl_min,
            float(max_high), float(min_low),
            row["id"]
        ))
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        log.info(f"Outcome tracker: updated {updated} rows")
