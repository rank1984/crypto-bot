"""
tools/exit_alerts.py
בודק מחיר נוכחי מול TP1/TP2/SL של עסקאות פתוחות ושולח התראת טלגרם.
נקרא בכל ריצת cron, לפני/אחרי outcome_tracker.
"""
import os
import sqlite3
from datetime import datetime, timezone
from engines.market_data import get_ticker_24h, get_candles
from notifier.sender import send_simple_message
from utils.logger import get_logger

log = get_logger("exit_alerts")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _get_current_price(symbol: str):
    """מחיר עדכני — מנסה candle אחרון, נופל ל-ticker."""
    try:
        df = get_candles(symbol, "5m", limit=1)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    ticker = get_ticker_24h(symbol)
    if ticker and "lastPrice" in ticker:
        return float(ticker["lastPrice"])
    return None


def check_exit_alerts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE decision='BUY' AND outcome_status IN ('PENDING', 'ACTIVE')
          AND entry_price > 0
    """).fetchall()

    sent = 0
    for row in rows:
        symbol = row["symbol"]
        entry = float(row["entry_price"] or 0)
        tp1, tp2, sl = float(row["tp1"] or 0), float(row["tp2"] or 0), float(row["sl"] or 0)

        price = _get_current_price(symbol)
        if price is None:
            continue

        alerts = []
        if sl > 0 and price <= sl and not row["sl_alert_sent"]:
            pnl = (sl - entry) / entry * 100
            alerts.append(("sl_alert_sent", f"🔴 *{symbol}* — SL נפגע!\nמחיר: {price}\nPnL: {pnl:+.2f}%\n➡️ שקול לצאת מהפוזיציה כולה."))
        if tp1 > 0 and price >= tp1 and not row["tp1_alert_sent"]:
            pnl = (tp1 - entry) / entry * 100
            alerts.append(("tp1_alert_sent", f"🟢 *{symbol}* — TP1 הושג!\nמחיר: {price}\nPnL: {pnl:+.2f}%\n➡️ לפי האסטרטגיה: מכור 20%, הזז סטופ ל-Breakeven ({entry})."))
        if tp2 > 0 and price >= tp2 and row["tp1_alert_sent"] and not row["tp2_alert_sent"]:
            pnl = (tp2 - entry) / entry * 100
            alerts.append(("tp2_alert_sent", f"🟢 *{symbol}* — TP2 הושג!\nמחיר: {price}\nPnL: {pnl:+.2f}%\n➡️ מכור עוד 20%, השאר Runner עם Trailing Stop."))

        for column, message in alerts:
            send_simple_message(message)
            cur.execute(f"UPDATE shadow_trades SET {column}=1 WHERE id=?", (row["id"],))
            sent += 1
            log.info(f"{symbol}: exit alert sent ({column})")

    conn.commit()
    conn.close()
    log.info(f"Exit alerts check complete: {sent} alerts sent")
    return sent


if __name__ == "__main__":
    check_exit_alerts()
