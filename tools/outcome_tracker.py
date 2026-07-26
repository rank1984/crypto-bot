import sqlite3
import os
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

log = get_logger("outcome_tracker")

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def _fetch_klines(symbol: str, start_ms: int, limit=144):
    """מושך נרות 5m ומחזיר DataFrame."""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "5m",
        "startTime": start_ms,
        "limit": limit
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            log.debug(f"Outcome: empty klines for {symbol}")
            return None
        # Binance error handling (e.g., {"code": -1121, "msg": "Invalid symbol"})
        if isinstance(data, dict) and "code" in data:
            log.warning(f"Binance API error for {symbol}: {data}")
            return None
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df
    except Exception as e:
        log.warning(f"Klines request failed for {symbol}: {e}")
        return None


def update_outcomes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # בחר שורות ב-PENDING או ACTIVE
    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE')
          AND entry_price > 0
        ORDER BY id
        LIMIT 50
    """).fetchall()

    log.info(f"Outcome tracker: found {len(rows)} rows to process")

    updated = 0
    for row in rows:
        symbol = row["symbol"]
        entry_price = float(row["entry_price"])
        trigger_price = float(row["trigger_price"] or (entry_price * 1.001))
        tp1 = float(row["tp1"] or (entry_price * 1.04))
        tp2 = float(row["tp2"] or (entry_price * 1.10))
        sl = float(row["sl"] or (entry_price * 0.98))
        ts_str = row["ts"]

        try:
            alert_time = datetime.fromisoformat(ts_str).replace(tzinfo=None)
            start_ms = int(alert_time.timestamp() * 1000)

            df = _fetch_klines(symbol, start_ms)
            if df is None or df.empty:
                log.debug(f"Outcome: no data for {symbol} (still may be too recent, will retry)")
                continue

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

            # סמן כ-ACTIVE (יש נתונים, המעקב בעיצומו)
            new_status = "ACTIVE"
            
            # בדוק תנאי סיום (פגיעה ביעדים או עברו 48 שעות)
            if tp1_hit or tp2_hit or sl_hit:
                new_status = "FINAL"
            elif (datetime.utcnow() - alert_time).total_seconds() > 172800:
                new_status = "FINAL"

            cur.execute("""
                UPDATE shadow_trades
                SET outcome_trigger_hit = ?,
                    outcome_tp1_hit = ?,
                    outcome_tp2_hit = ?,
                    outcome_sl_hit = ?,
                    outcome_max_up_pct = ?,
                    outcome_max_down_pct = ?,
                    outcome_status = ?,
                    outcome_trigger_min = ?,
                    outcome_tp1_min = ?,
                    outcome_tp2_min = ?,
                    outcome_sl_min = ?,
                    outcome_highest_price = ?,
                    outcome_lowest_price = ?
                WHERE id = ?
            """, (
                trigger_hit, tp1_hit, tp2_hit, sl_hit,
                max_up, max_down,
                new_status,
                trigger_min, tp1_min, tp2_min, sl_min,
                float(max_high), float(min_low),
                row["id"]
            ))
            updated += 1

        except Exception as e:
            log.warning(f"Outcome calculation failed for {symbol}: {e}")

    conn.commit()
    conn.close()

    if updated:
        log.info(f"Outcome tracker: updated {updated} rows")
        try:
            from tools.shadow_mode import export_shadow_csv
            export_shadow_csv()
        except:
            pass
    else:
        log.info("Outcome tracker: no rows updated (still waiting for data)")
