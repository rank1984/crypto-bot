"""
CRYPTO-BOT Elite — Exit Alert
בודק עסקאות שבוצעו בפועל (/buy /done) מול המחיר החי,
ושולח התראת טלגרם ברגע שTP1/TP2/SL נחצה — פעם אחת בלבד לכל אירוע.
"""
import os
import sqlite3
from engines.market_data import get_candles
from notifier.sender import send_simple_message
from utils.logger import get_logger

log = get_logger("exit_alert")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def check_and_alert_exits():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, symbol, entry_price, tp1, tp2, sl,
               tp1_alert_sent, tp2_alert_sent, sl_alert_sent
        FROM shadow_trades
        WHERE was_executed = 1 AND outcome_status = 'ACTIVE'
    """).fetchall()

    log.info(f"Exit alert check: {len(rows)} executed open trades")
    alerted = 0

    for row in rows:
        symbol = row["symbol"]
        try:
            df = get_candles(symbol, "5m")
            if df is None or df.empty:
                continue
            last_price = float(df["close"].iloc[-1])
        except Exception as e:
            log.warning(f"{symbol}: price fetch failed — {e}")
            continue

        updates = {}

        if row["sl"] and last_price <= row["sl"] and not row["sl_alert_sent"]:
            send_simple_message(f"🔴 {symbol}: מחיר הגיע ל-SL ({row['sl']}) — שקול לצאת מהעסקה!")
            updates["sl_alert_sent"] = 1
            alerted += 1

        elif row["tp1"] and last_price >= row["tp1"] and not row["tp1_alert_sent"]:
            send_simple_message(f"🟢 {symbol}: מחיר הגיע ל-TP1 ({row['tp1']}) — שקול למכור חלק ולהזיז סטופ ל-Breakeven")
            updates["tp1_alert_sent"] = 1
            alerted += 1

        if row["tp2"] and last_price >= row["tp2"] and not row["tp2_alert_sent"]:
            send_simple_message(f"🟢🟢 {symbol}: מחיר הגיע ל-TP2 ({row['tp2']}) — שקול למכור חלק נוסף")
            updates["tp2_alert_sent"] = 1
            alerted += 1

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            cur.execute(f"UPDATE shadow_trades SET {set_clause} WHERE id=?",
                        (*updates.values(), row["id"]))

    conn.commit()
    conn.close()
    log.info(f"Exit alert check complete: {alerted} new alerts sent")
    return alerted
