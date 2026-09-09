"""
tools/health_check.py
Quick health check for Market Data sources.
Run: python -c "from tools.health_check import health_check; health_check()"
"""

import requests
import json
from utils.logger import get_logger
from utils.config import KUCOIN_BASE

log = get_logger("health_check")
_HEADERS = {"User-Agent": "crypto-bot/1.0"}


def health_check():
    print("\n=== MARKET DATA HEALTH CHECK ===\n")

    # 1. Binance connectivity
    try:
        r = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
        print(f"Binance ping: HTTP {r.status_code}")
    except Exception as e:
        print(f"Binance ping: FAILED - {e}")

    # 2. Binance bulk ticker
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            headers=_HEADERS,
            timeout=10
        )
        print(f"Binance bulk ticker: HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            usdt_count = sum(1 for item in data if item.get("symbol", "").endswith("USDT"))
            print(f"  Total symbols: {len(data)}")
            print(f"  USDT symbols: {usdt_count}")
            # Sample first 3 USDT symbols
            sample = [item["symbol"] for item in data if item.get("symbol", "").endswith("USDT")][:3]
            print(f"  Sample USDT symbols: {sample}")
        else:
            print(f"  Response: {r.text[:200]}")
    except Exception as e:
        print(f"Binance bulk ticker: FAILED - {e}")

    # 3. KuCoin connectivity
    try:
        r = requests.get(f"{KUCOIN_BASE}/market/status", headers=_HEADERS, timeout=5)
        print(f"KuCoin status: HTTP {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.json().get('msg')}")
    except Exception as e:
        print(f"KuCoin status: FAILED - {e}")

    # 4. KuCoin allTickers
    try:
        r = requests.get(
            f"{KUCOIN_BASE}/market/allTickers",
            headers=_HEADERS,
            timeout=10
        )
        print(f"KuCoin allTickers: HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "200000":
                tickers = data.get("data", {}).get("ticker", [])
                usdt_count = sum(1 for item in tickers if item.get("symbol", "").replace("-", "").endswith("USDT"))
                print(f"  Total tickers: {len(tickers)}")
                print(f"  USDT symbols: {usdt_count}")
                # Sample first 3 USDT symbols
                sample = []
                for item in tickers:
                    sym = item.get("symbol", "").replace("-", "")
                    if sym.endswith("USDT"):
                        sample.append(sym)
                        if len(sample) >= 3:
                            break
                print(f"  Sample USDT symbols: {sample}")
            else:
                print(f"  KuCoin API error: {data.get('msg')}")
        else:
            print(f"  Response: {r.text[:200]}")
    except Exception as e:
        print(f"KuCoin allTickers: FAILED - {e}")

    print("\n=== END HEALTH CHECK ===\n")


if __name__ == "__main__":
    health_check()