"""
CRYPTO-BOT Elite — Alternative Data Engine

מקורות:
    - Binance WebSocket Order Book (Bid/Ask Ratio)
    - CoinGecko Trending
    - Whale Alert (placeholder)
    - Stablecoin Flow (placeholder)
"""
import asyncio
import json
import time
import threading
import requests
from collections import defaultdict
from utils.logger import get_logger

log = get_logger("alt_data")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Order Book via WebSocket
# ═══════════════════════════════════════════════════════════════════════════════
class BinanceOrderBookMonitor(threading.Thread):
    """
    מתחבר ל‑WebSocket של Binance (depth@100ms) למטבע בודד.
    שומר את ספר הפקודות המקומי ומחשב bid/ask ratio.
    """
    def __init__(self, symbol: str, callback=None, depth_levels=20):
        super().__init__(daemon=True)
        self.symbol = symbol.lower()
        self.callback = callback
        self.depth_levels = depth_levels
        self.bids = {}
        self.asks = {}
        self.ws = None
        self.running = True

    def run(self):
        import websocket  # pip install websocket-client
        url = f"wss://stream.binance.com:9443/ws/{self.symbol}@depth@100ms"
        self.ws = websocket.WebSocketApp(url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close)
        self.ws.run_forever()

    def _on_message(self, ws, message):
        data = json.loads(message)
        # עדכון ספר הפקודות
        for side, key in [("bids", "bids"), ("asks", "asks")]:
            for update in data.get(side, []):
                price, qty = float(update[0]), float(update[1])
                if qty == 0:
                    self.__dict__[key].pop(price, None)
                else:
                    self.__dict__[key][price] = qty

        # חישוב יחס
        bid_total = sum(sorted(self.bids.values(), reverse=True)[:self.depth_levels])
        ask_total = sum(sorted(self.asks.values())[:self.depth_levels])
        ratio = bid_total / ask_total if ask_total > 0 else 0

        if self.callback:
            self.callback({
                "symbol": self.symbol.upper(),
                "bid_ask_ratio": round(ratio, 2),
                "bid_volume": round(bid_total, 2),
                "ask_volume": round(ask_total, 2),
                "timestamp": time.time()
            })

    def _on_error(self, ws, error):
        log.error(f"WebSocket error {self.symbol}: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        log.warning(f"WebSocket closed for {self.symbol}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.keep_running = False

# ═══════════════════════════════════════════════════════════════════════════════
# 2. CoinGecko Trending
# ═══════════════════════════════════════════════════════════════════════════════
def get_coingecko_trending():
    """מחזיר רשימת סימבולים (ללא USDT) שנמצאים ב‑Trending."""
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        r = requests.get(url, timeout=10)
        data = r.json()
        coins = []
        for item in data.get("coins", []):
            coin = item.get("item", {})
            symbol = coin.get("symbol", "").upper()
            if symbol:
                coins.append(symbol)
        return coins
    except Exception as e:
        log.warning(f"CoinGecko trending error: {e}")
        return []

def trending_bonus(symbol: str, trending_list: list) -> float:
    """מחזיר בונוס (0-10) אם המטבע נמצא ב‑Trending."""
    if symbol.replace("USDT", "") in trending_list:
        return 10.0
    return 0.0

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Whale Alert (placeholder)
# ═══════════════════════════════════════════════════════════════════════════════
def get_whale_activity(symbol: str) -> bool:
    """בדוק תנועות גדולות. כרגע מחזיר False."""
    # TODO: implement using Whale Alert API or similar
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Stablecoin Flow (placeholder)
# ═══════════════════════════════════════════════════════════════════════════════
def stablecoin_inflow_score() -> float:
    """בודק שינוי בהיצע USDT/USDC. כרגע מחזיר 0."""
    # TODO: implement using Glassnode/CoinMetrics
    return 0.0
