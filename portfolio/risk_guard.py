"""
CRYPTO-BOT Elite — Daily Risk Guard
"""
from datetime import datetime
from utils.logger import get_logger

log = get_logger("risk_guard")

class DailyRiskGuard:
    def __init__(self, max_daily_loss_pct=3.0, max_losing_trades=3, max_trades=2, max_exposure_pct=50.0):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_losing_trades = max_losing_trades
        self.max_trades = max_trades
        self.max_exposure_pct = max_exposure_pct
        self.daily_pnl = 0.0
        self.losing_trades_today = 0
        self.open_trades = 0
        self.exposure = 0.0
        self.trading_disabled = False
        self.reset_time = None

    def update(self, pnl: float, trade_closed: bool = False, is_loss: bool = False):
        now = datetime.now()
        if self.reset_time is None or now.date() > self.reset_time.date():
            self.reset()

        self.daily_pnl += pnl
        if trade_closed and is_loss:
            self.losing_trades_today += 1
            self.open_trades -= 1
        elif trade_closed:
            self.open_trades -= 1

        if self.daily_pnl < -self.max_daily_loss_pct * 100:  # percent?
            self.trading_disabled = True
            log.warning("Daily loss limit reached. Trading disabled.")
        if self.losing_trades_today >= self.max_losing_trades:
            self.trading_disabled = True
            log.warning("Max losing trades reached. Trading disabled.")

    def can_trade(self):
        return not self.trading_disabled and self.open_trades < self.max_trades

    def reset(self):
        self.daily_pnl = 0.0
        self.losing_trades_today = 0
        self.trading_disabled = False
        self.reset_time = datetime.now()
