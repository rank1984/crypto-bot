"""
tools/ensure_open_trade_candles.py
מוודא שלכל symbol עם shadow trade פתוח יש candles עדכניים.
כולל rate limit protection + retry logic.
"""
import os
import time
import sqlite3
from utils.logger import get_logger

log = get_logger("ensure_open_trade_candles")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

# 🆕 Rate limit configuration
DELAY_BETWEEN_FETCHES = 0.5   # 500ms between symbols
MAX_RETRIES = 2                # retry twice on failure
RETRY_DELAY = 2.0              # 2s between retries


def _get_candles_with_retry(symbol: str, interval: str, max_retries: int = MAX_RETRIES):
    """Fetch candles with retry logic."""
    from scanner.market_data import get_candles
    
    for attempt in range(max_retries):
        try:
            df = get_candles(symbol, interval, limit=100)
            if df is not None and not df.empty:
                return df
            # If empty, wait before retry
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            log.debug(f"{symbol}: attempt {attempt+1} failed - {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
    
    return None


def ensure_candles_for_open_trades():
    """Ensure candles for all symbols with open trades – with rate limiting."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    symbols = [r["symbol"] for r in conn.execute("""
        SELECT DISTINCT symbol FROM shadow_trades
        WHERE outcome_status IN ('PENDING', 'ACTIVE')
    """).fetchall()]
    conn.close()

    log.info(f"Ensuring 5m candles for {len(symbols)} symbols with open trades")
    
    ok = 0
    failed = 0
    failed_symbols = []

    for i, symbol in enumerate(symbols, 1):
        # 🆕 Rate limit: delay between symbols
        if i > 1:
            time.sleep(DELAY_BETWEEN_FETCHES)
        
        df = _get_candles_with_retry(symbol, "5m")
        
        if df is not None and not df.empty:
            ok += 1
            if i % 20 == 0:
                log.info(f"  Progress: {i}/{len(symbols)} | ok={ok} failed={failed}")
        else:
            failed += 1
            failed_symbols.append(symbol)
            if failed <= 10:
                log.warning(f"{symbol}: no candles after retries")

    # Summary
    log.info(f"Candle ensure complete: {ok} ok, {failed} failed")
    
    if failed_symbols:
        log.warning(f"Failed symbols (first 20): {failed_symbols[:20]}")
    
    return ok, failed


if __name__ == "__main__":
    ensure_candles_for_open_trades()
