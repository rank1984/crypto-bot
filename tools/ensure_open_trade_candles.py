"""
tools/ensure_open_trade_candles.py — v2.0

Changes from v1.0:
  - After fetching, EXPLICITLY verify candles landed in candle_cache.db
  - Log a warning if get_candles succeeded but candle_cache is empty
  - Report per-symbol whether candles made it to the cache
"""
import os
import time
import sqlite3
from utils.logger import get_logger

log = get_logger("ensure_open_trade_candles")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

DELAY_BETWEEN_FETCHES = 0.4
MAX_RETRIES = 3
RETRY_DELAY = 2.0
BATCH_PAUSE_EVERY = 20
BATCH_PAUSE_SECONDS = 3.0


def _get_candles_with_retry(symbol: str, interval: str, max_retries: int = MAX_RETRIES):
    from scanner.market_data import get_candles

    for attempt in range(max_retries):
        try:
            df = get_candles(symbol, interval, limit=100)
            if df is not None and not df.empty:
                return df

            if attempt < max_retries - 1:
                wait = RETRY_DELAY * (attempt + 1)
                log.debug(f"{symbol}: empty response, retry in {wait}s")
                time.sleep(wait)

        except Exception as e:
            log.debug(f"{symbol}: attempt {attempt+1} failed - {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

    return None


def _verify_in_cache(symbol: str) -> int:
    """Check how many candles exist in candle_cache.db for this symbol."""
    try:
        from storage.candle_cache import get_candles_range
        import pandas as pd
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
        df = get_candles_range(symbol, start)
        return 0 if df is None or df.empty else len(df)
    except Exception as e:
        log.debug(f"{symbol}: cache verify failed - {e}")
        return 0


def ensure_candles_for_open_trades():
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
    not_in_cache = []    # ← v2.0: symbols that fetched OK but not in candle_cache

    for i, symbol in enumerate(symbols, 1):
        if i > 1:
            time.sleep(DELAY_BETWEEN_FETCHES)

        if i > 1 and i % BATCH_PAUSE_EVERY == 0:
            log.info(f"  Batch pause ({i}/{len(symbols)}) – sleeping {BATCH_PAUSE_SECONDS}s")
            time.sleep(BATCH_PAUSE_SECONDS)

        df = _get_candles_with_retry(symbol, "5m")

        if df is not None and not df.empty:
            # v2.0: verify it actually landed in candle_cache.db
            n_cached = _verify_in_cache(symbol)
            if n_cached == 0:
                not_in_cache.append(symbol)
                log.warning(f"{symbol}: fetched {len(df)} bars but cache is empty!")
                failed += 1
            else:
                ok += 1

            if i % 20 == 0:
                log.info(f"  Progress: {i}/{len(symbols)} | ok={ok} failed={failed}")
        else:
            failed += 1
            failed_symbols.append(symbol)
            if failed <= 10:
                log.warning(f"{symbol}: no candles after {MAX_RETRIES} retries")

    log.info(f"Candle ensure complete: {ok} ok, {failed} failed")
    log.info(f"  (Rate limit: {DELAY_BETWEEN_FETCHES}s between symbols, "
             f"{BATCH_PAUSE_SECONDS}s pause every {BATCH_PAUSE_EVERY} symbols)")

    if failed_symbols:
        log.warning(f"Fetch-failed symbols ({len(failed_symbols)}): {failed_symbols[:20]}")

    if not_in_cache:
        log.error(f"NOT-IN-CACHE symbols ({len(not_in_cache)}): {not_in_cache[:20]}")
        log.error("  → These fetched OK but didn't reach candle_cache.db.")
        log.error("  → This should NOT happen with market_data.py v10.1")

    return ok, failed


if __name__ == "__main__":
    ensure_candles_for_open_trade_candles = None  # guard against typo
    ensure_candles_for_open_trades()
