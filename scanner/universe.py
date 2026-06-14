"""
CRYPTO-BOT Elite — Universe Builder
סורק את Binance ומחזיר רשימת USDT pairs לפי פילטרים.
"""
import requests

from utils.config import (
    BINANCE_BASE_URL,
    MAX_SYMBOLS,
    MIN_DAILY_VOLUME,
    MIN_PRICE,
    QUOTE_ASSET,
)
from utils.logger import get_logger

log = get_logger(__name__)


def build_universe() -> list[str]:
    """
    Returns a sorted list of symbols that pass all filters, e.g.:
        ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', ...]

    Filters applied:
        - quoteAsset == USDT
        - status == TRADING
        - 24h quoteVolume > MIN_DAILY_VOLUME ($5M default)
        - lastPrice > MIN_PRICE (0.0001 default)
    """
    log.info("Building universe from Binance 24h ticker...")

    try:
        resp = requests.get(
            f"{BINANCE_BASE_URL}/api/v3/ticker/24hr",
            timeout=15,
        )
        resp.raise_for_status()
        tickers = resp.json()
    except Exception as e:
        log.error(f"Failed to fetch 24h ticker: {e}")
        return []

    # ─── Exchange info for status filter ──────────────────────────────────────
    try:
        info_resp = requests.get(
            f"{BINANCE_BASE_URL}/api/v3/exchangeInfo",
            timeout=15,
        )
        info_resp.raise_for_status()
        trading_symbols = {
            s["symbol"]
            for s in info_resp.json()["symbols"]
            if s["status"] == "TRADING" and s["quoteAsset"] == QUOTE_ASSET
        }
    except Exception as e:
        log.warning(f"Could not fetch exchangeInfo, skipping status filter: {e}")
        trading_symbols = None

    # ─── Apply filters ────────────────────────────────────────────────────────
    universe: list[tuple[float, str]] = []   # (volume, symbol) for sorting

    for t in tickers:
        sym = t.get("symbol", "")

        # USDT pair only
        if not sym.endswith(QUOTE_ASSET):
            continue

        # Trading status
        if trading_symbols is not None and sym not in trading_symbols:
            continue

        try:
            volume = float(t.get("quoteVolume", 0))   # 24h volume in USDT
            price  = float(t.get("lastPrice", 0))
        except (ValueError, TypeError):
            continue

        if volume < MIN_DAILY_VOLUME:
            continue
        if price < MIN_PRICE:
            continue

        universe.append((volume, sym))

    # Sort by volume descending, cap at MAX_SYMBOLS
    universe.sort(reverse=True)
    result = [sym for _, sym in universe[:MAX_SYMBOLS]]

    log.info(f"Universe built: {len(result)} symbols (filtered from {len(tickers)})")
    return result


if __name__ == "__main__":
    coins = build_universe()
    print(f"\nTop 20 by volume:")
    for i, sym in enumerate(coins[:20], 1):
        print(f"  {i:>3}. {sym}")
