"""
CRYPTO-BOT Elite — Live Monitor

עוקב אחרי מטבעות ARM כל 10 שניות.
מזהה פריצת טריגר ומייצר BUY מיידי.
"""
import time
import threading
from datetime import datetime
from utils.logger import get_logger
from scanner.market_data import get_candles

log = get_logger("live_monitor")

class LiveMonitor(threading.Thread):
    def __init__(self, trade_manager, send_callback):
        super().__init__(daemon=True)
        self.trade_mgr = trade_manager
        self.send = send_callback
        self.watchlist = []
        self.running = True
        self.interval = 10   # 10 שניות

    def clear_watchlist(self):
        """נקה את הרשימה (תקרא כל סריקה ראשית)"""
        self.watchlist = []

    def add_to_watchlist(self, coin: dict):
        symbol = coin["symbol"]
        if not any(c["symbol"] == symbol for c in self.watchlist):
            self.watchlist.append({
                "symbol": symbol,
                "trigger": coin.get("trigger_price", 0),
                "entry_price": coin.get("entry_price", 0),
                "sl": coin.get("sl", 0),
                "tp1": coin.get("tp1", 0),
                "tp2": coin.get("tp2", 0),
                "setup_type": coin.get("setup_type", "BREAKOUT"),
                "added": datetime.now(),
            })
            log.info(f"Live Monitor: ARM {symbol} (trigger={coin.get('trigger_price', 0):.5f})")

    def run(self):
        while self.running:
            for item in self.watchlist[:]:
                try:
                    df = get_candles(item["symbol"], "1m", limit=3)
                    if df is None or len(df) < 2:
                        continue
                    last_close = float(df["close"].iloc[-1])
                    rvol = float(df["volume"].iloc[-1]) / float(df["volume"].iloc[-10:-1].mean()) if len(df) >= 10 else 1.0

                    if last_close >= item["trigger"] and rvol > 1.2:
                        log.info(f"ARM TRIGGER: {item['symbol']} @ {last_close:.5f}")
                        signal = {
                            "symbol": item["symbol"],
                            "entry": last_close,
                            "sl": item["sl"],
                            "tp1": item["tp1"],
                            "tp2": item["tp2"],
                            "setup_type": item["setup_type"],
                        }
                        trade = self.trade_mgr.open_trade(signal, last_close)
                        if trade:
                            self.send(f"🟢 ARM→BUY {item['symbol']} @ {last_close:.5f}")
                        self.watchlist.remove(item)
                except Exception as e:
                    log.error(f"Live Monitor error {item['symbol']}: {e}")
            time.sleep(self.interval)

    def stop(self):
        self.running = False
