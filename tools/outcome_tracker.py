"""
CRYPTO-BOT Elite — Outcome Tracker (v3 – robust)

- עובד על טבלת shadow_trades (צריך את כל עמודות ה-outcome)
- משתמש בנתוני Binance (דרך klines)
- מחשב Trigger/TP/SL היסטוריים
"""
import sqlite3
import os
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
LOOKBACK_HOURS = 12


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # מעבדים את כל השורות שלא נבדקו, ללא תלות בזמן
    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_checked = 0
          AND entry_price > 0
        ORDER BY id
        LIMIT 50
    """).fetchall()

    log.info(f"Outcome tracker: found {len(rows)} rows to process")

    updated = 0
    for row in rows:
        symbol = row["symbol"]
        entry_price = row["entry_price"]
        trigger_price = row["trigger_price"] or (entry_price * 1.001)
        tp1 = row["tp1"] or (entry_price * 1.04)
        tp2 = row["tp2"] or (entry_price * 1.10)
        sl = row["sl"] or (entry_price * 0.98)
        ts_str = row["ts"]

        try:
            alert_time = datetime.fromisoformat(ts_str).replace(tzinfo=None)
            start_ms = int(alert_time.timestamp() * 1000)

            # משוך נרות 5m
            url = "https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": "5m",
                "startTime": start_ms,
                "limit": 144  # 12h
            }
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                log.debug(f"Outcome tracker: no klines for {symbol}")
                continue

            df = pd.DataFrame(data, columns=[
                "time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
            df["time"] = pd.to_datetime(df["time"], unit="ms")

            max_high = df["high"].max()
            min_low = df["low"].min()
            max_up = round((max_high - entry_price) / entry_price * 100, 2)
            max_down = round((min_low - entry_price) / entry_price * 100, 2)

            trigger_hit = 1 if max_high >= trigger_price else 0
            tp1_hit = 1 if tp1 > 0 and max_high >= tp1 else 0
            tp2_hit = 1 if tp2 > 0 and max_high >= tp2 else 0
            sl_hit = 1 if sl > 0 and min_low <= sl else 0

            # זמני חצייה
            def time_to_hit(level, series, direction="high"):
                if direction == "high":
                    mask = series >= level
                else:
                    mask = series <= level
                if mask.any():
                    return round((df["time"][mask].iloc[0] - alert_time).total_seconds() / 60, 1)
                return None

            trigger_min = time_to_hit(trigger_price, df["high"], "high") if trigger_hit else None
            tp1_min = time_to_hit(tp1, df["high"], "high") if tp1_hit else None
            tp2_min = time_to_hit(tp2, df["high"], "high") if tp2_hit else None
            sl_min = time_to_hit(sl, df["low"], "low") if sl_hit else None

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
            """, (trigger_hit, tp1_hit, tp2_hit, sl_hit,
                  max_up, max_down,
                  trigger_min, tp1_min, tp2_min, sl_min,
                  float(max_high), float(min_low),
                  row["id"]))
            updated += 1

        except Exception as e:
            log.warning(f"Outcome failed for {symbol}: {e}")

    conn.commit()
    conn.close()

    if updated:
        log.info(f"Outcome tracker: updated {updated} rows")
        # גם לייצא CSV
        try:
            from tools.shadow_mode import export_shadow_csv
            export_shadow_csv()
        except:
            pass
    else:
        log.info("Outcome tracker: no rows updated (still waiting for data)")
