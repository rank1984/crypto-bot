"""
CRYPTO-BOT Elite — Universe Builder
משתמש ב-CoinGecko (חינמי, ללא הרשמה, עובד מ-GitHub Actions).
"""
import requests
from utils.config import COINGECKO_BASE, MIN_DAILY_VOLUME, MIN_PRICE, MAX_SYMBOLS
from utils.logger import get_logger

log = get_logger(__name__)

_HEADERS = {"User-Agent": "crypto-bot/1.0"}


def build_universe() -> list[str]:
    """
    מחזיר רשימת USDT pairs לפי volume.
    מקור: CoinGecko /coins/markets — חינמי לחלוטין.
    """
    log.info("Building universe from CoinGecko...")

    symbols = []
    for page in range(1, 4):   # 3 עמודים × 100 = 300 מטבעות
        try:
            resp = requests.get(
                f"{COINGECKO_BASE}/coins/markets",
                headers=_HEADERS,
                params={
                    "vs_currency": "usd",
                    "order":       "volume_desc",
                    "per_page":    100,
                    "page":        page,
                    "sparkline":   "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            coins = resp.json()
        except Exception as e:
            log.warning(f"CoinGecko page {page} failed: {e}")
            break

        for c in coins:
            vol    = c.get("total_volume") or 0
            price  = c.get("current_price") or 0
            symbol = (c.get("symbol") or "").upper()

            if vol   < MIN_DAILY_VOLUME: continue
            if price < MIN_PRICE:        continue
            if not symbol:               continue

            sym_usdt = f"{symbol}USDT"
            if sym_usdt not in symbols:
                symbols.append(sym_usdt)

        if len(symbols) >= MAX_SYMBOLS:
            break

    result = symbols[:MAX_SYMBOLS]
    log.info(f"Universe: {len(result)} symbols")
    return result


if __name__ == "__main__":
    coins = build_universe()
    print(f"\nTop 20:")
    for i, s in enumerate(coins[:20], 1):
        print(f"  {i:>3}. {s}")
