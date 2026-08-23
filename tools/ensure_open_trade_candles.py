"""
tools/ensure_open_trade_candles.py
מוודא שלכל symbol עם shadow trade פתוח (PENDING/ACTIVE) יש candles עדכניים
בקאש — ללא תלות אם הוא נמצא ב-Dynamic Universe של הסריקה הנוכחית.
נקרא לפני update_outcomes().
"""
import os
import sqlite3
from engines.market_data import get_candles
from utils.logger import get_logger

log = get_logger("ensure_open_trade_candles")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def ensure_candles_for_open_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    symbols = [r["symbol"] for r in conn.execute("""
        SELECT DISTINCT symbol FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE')
    """).fetchall()]
    conn.close()

    log.info(f"Ensuring 5m candles for {len(symbols)} symbols with open trades")
    ok, failed = 0, 0
    for symbol in symbols:
        try:
            df = get_candles(symbol, "5m")  # שומר ל-candle_cache כתופעת לוואי
            if df is not None and not df.empty:
                ok += 1
            else:
                failed += 1
                log.warning(f"{symbol}: still no candles available (API/liquidity issue)")
        except Exception as e:
            failed += 1
            log.error(f"{symbol}: candle fetch failed — {e}")

    log.info(f"Candle ensure complete: {ok} ok, {failed} failed")
    return ok, failed


if __name__ == "__main__":
    ensure_candles_for_open_trades()
