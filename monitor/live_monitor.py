"""
CRYPTO-BOT Elite — Live Monitor

עוקב אחרי מטבעות READY/ARMED בתדירות גבוהה (15s).
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
        self.send = send_callback  # פונקציית שליחה לטלגרם
        self.watchlist = []        # רשימת מטבעות במעקב צמוד
        self.running = True
        self.interval = 15         # שניות

    def add_to_watchlist(self, coin: dict):
        """הוסף מטבע למעקב צמוד (READY/ARMED)"""
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
            log.info(f"Live Monitor: added {symbol} (trigger={coin.get('trigger_price', 0):.5f})")

    def remove_from_watchlist(self, symbol: str):
        self.watchlist = [c for c in self.watchlist if c["symbol"] != symbol]

    def run(self):
        while self.running:
            for item in self.watchlist[:]:  # copy for safe removal
                try:
                    df = get_candles(item["symbol"], "1m", limit=2)
                    if df is None or len(df) < 2:
                        continue
                    last_close = float(df["close"].iloc[-1])
                    prev_close = float(df["close"].iloc[-2])
                    rvol = float(df["volume"].iloc[-1]) / float(df["volume"].iloc[-10:-1].mean()) if len(df) >= 10 else 0

                    trigger = item["trigger"]

                    # בדיקת פריצת טריגר עם Volume
                    if last_close >= trigger and rvol > 1.2:
                        log.info(f"LIVE TRIGGER: {item['symbol']} @ {last_close:.5f} (RVOL={rvol:.1f})")
                        # Order Validation
                        if self._validate_order(item, last_close, rvol):
                            # פתח עסקה
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
                                self.send(f"🟢 LIVE BUY {item['symbol']} @ {last_close:.5f}")
                            self.remove_from_watchlist(item["symbol"])
                except Exception as e:
                    log.error(f"Live Monitor error for {item['symbol']}: {e}")

            time.sleep(self.interval)

    def _validate_order(self, item: dict, price: float, rvol: float) -> bool:
        """בדיקה אחרונה לפני כניסה"""
        if rvol < 1.2:
            return False
        # אפשר להוסיף Market Health, News, Spread checks
        return True

    def stop(self):
        self.running = False
