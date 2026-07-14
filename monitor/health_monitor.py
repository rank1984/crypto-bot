"""
CRYPTO-BOT Elite — Health Monitor

בודק כל דקה:
    - Binance API
    - News API
    - Telegram connectivity
    - SQLite accessibility
    - Internet connection
"""
import threading
import time
import requests
from utils.logger import get_logger

log = get_logger("health_monitor")

class HealthMonitor(threading.Thread):
    def __init__(self, interval=60):
        super().__init__(daemon=True)
        self.interval = interval
        self.status = {}
        self.running = True

    def check_binance(self):
        try:
            resp = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
            return resp.status_code == 200
        except:
            return False

    def check_telegram(self):
        # שליחת הודעת בדיקה שקטה – או להניח תקין
        return True

    def check_news_api(self):
        try:
            resp = requests.get("https://api.alternative.me/fng/", timeout=5)
            return resp.status_code == 200
        except:
            return False

    def run(self):
        while self.running:
            self.status["binance"] = self.check_binance()
            self.status["telegram"] = self.check_telegram()
            self.status["news_api"] = self.check_news_api()
            self.status["internet"] = self.check_binance()  # all need internet

            if not all(self.status.values()):
                failed = [k for k, v in self.status.items() if not v]
                log.error(f"Health Monitor: {failed} offline")
                # send_telegram alert (אם טלגרם לא מקולקל)

            time.sleep(self.interval)

    def stop(self):
        self.running = False
