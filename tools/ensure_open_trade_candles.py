"""
tools/ensure_open_trade_candles.py
מוודא שלכל symbol עם shadow trade פתוח יש candles עדכניים.
כולל rate limit protection + retry logic + cache fallback.
"""
import os
import time
import sqlite3
from utils.logger import get_logger

log = get_logger("ensure_open_trade_candles")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

# 🆕 Rate limit configuration
DELAY_BETWEEN_FETCHES = 0.4   # 400ms between symbols
MAX_RETRIES = 3                # retry 3 times on failure
RETRY_DELAY = 2.0              # 2s between retries
BATCH_PAUSE_EVERY = 20         # pause every N symbols
BATCH_PAUSE_SECONDS = 3.0      # pause duration


def _get_candles_with_retry(symbol: str, interval: str, max_retries: int = MAX_RETRIES):
    """Fetch candles with retry logic + exponential backoff."""
    from scanner.market_data import get_candles

    for attempt in range(max_retries):
        try:
            df = get_candles(symbol, interval, limit=100)
            if df is not None and not df.empty:
                return df

            # Empty response – wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                wait = RETRY_DELAY * (attempt + 1)
                log.debug(f"{symbol}: empty response, retry in {wait}s")
                time.sleep(wait)

        except Exception as e:
            log.debug(f"{symbol}: attempt {attempt+1} failed - {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

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
        # Rate limit: delay between symbols
        if i > 1:
            time.sleep(DELAY_BETWEEN_FETCHES)

        # Batch pause every N symbols to avoid rate limit
        if i > 1 and i % BATCH_PAUSE_EVERY == 0:
            log.info(f"  Batch pause ({i}/{len(symbols)}) – sleeping {BATCH_PAUSE_SECONDS}s")
            time.sleep(BATCH_PAUSE_SECONDS)

        df = _get_candles_with_retry(symbol, "5m")

        if df is not None and not df.empty:
            ok += 1
            if i % 20 == 0:
                log.info(f"  Progress: {i}/{len(symbols)} | ok={ok} failed={failed}")
        else:
            failed += 1
            failed_symbols.append(symbol)
            if failed <= 10:
                log.warning(f"{symbol}: no candles after {MAX_RETRIES} retries")

    # Summary
    log.info(f"Candle ensure complete: {ok} ok, {failed} failed")
    log.info(f"  (Rate limit: {DELAY_BETWEEN_FETCHES}s between symbols, "
             f"{BATCH_PAUSE_SECONDS}s pause every {BATCH_PAUSE_EVERY} symbols)")

    if failed_symbols:
        log.warning(f"Failed symbols ({len(failed_symbols)}): {failed_symbols[:20]}")

    return ok, failed


if __name__ == "__main__":
    ensure_candles_for_open_trades()
