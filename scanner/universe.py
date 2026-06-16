"""
CRYPTO-BOT Elite — Universe Builder
סורק את Binance ומחזיר רשימת USDT pairs לפי פילטרים.
"""
import requests

BINANCE_MIRRORS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

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

    # נסה כל mirror עד שאחד עובד
    tickers = None
    working_base = None
    for mirror in BINANCE_MIRRORS:
        try:
            resp = requests.get(
                f"{mirror}/api/v3/ticker/24hr",
                timeout=15,
            )
            resp.raise_for_status()
            tickers = resp.json()
            working_base = mirror
            log.info(f"Connected via {mirror}")
            break
        except Exception as e:
            log.warning(f"{mirror} failed: {e}")
            continue

    if tickers is None:
        log.error("All Binance mirrors failed — falling back to CoinGecko")
        return _universe_from_coingecko()

    # ─── Exchange info for status filter ──────────────────────────────────────
    trading_symbols = None
    try:
        info_resp = requests.get(
            f"{working_base}/api/v3/exchangeInfo",
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


def _universe_from_coingecko() -> list[str]:
    """
    Fallback: שולף top 250 מטבעות מ-CoinGecko ומחזיר אותם כ-USDT pairs.
    CoinGecko חינמי ולא חסום ב-GitHub Actions.
    """
    log.info("Building universe from CoinGecko (fallback)...")
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            headers={"User-Agent": "Mozilla/5.0 (compatible; crypto-bot/1.0)"},
            params={
                "vs_currency":  "usd",
                "order":        "volume_desc",
                "per_page":     250,
                "page":         1,
                "sparkline":    "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        coins = resp.json()
    except Exception as e:
        log.error(f"CoinGecko fallback also failed: {e}")
        return []

    # פילטר לפי volume
    result = []
    for c in coins:
        vol = c.get("total_volume", 0) or 0
        price = c.get("current_price", 0) or 0
        symbol = (c.get("symbol", "") or "").upper()
        if vol < MIN_DAILY_VOLUME:
            continue
        if price < MIN_PRICE:
            continue
        if not symbol:
            continue
        result.append(f"{symbol}USDT")

    log.info(f"CoinGecko universe: {len(result)} symbols")
    return result[:MAX_SYMBOLS]


if __name__ == "__main__":
    coins = build_universe()
    print(f"\nTop 20 by volume:")
    for i, sym in enumerate(coins[:20], 1):
        print(f"  {i:>3}. {sym}")
