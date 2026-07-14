"""
CRYPTO-BOT Elite — Circuit Breaker

מפסיק מסחר ב:
    - 3 הפסדים רצופים
    - Drawdown יומי 5%
    - Market Health < 25
    - High Impact Event
"""
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger("circuit_breaker")

class CircuitBreaker:
    def __init__(self):
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.daily_start = datetime.now()
        self.last_trade_time = None
        self.trading_blocked = False
        self.block_reason = ""
        self.block_until = None

    def update_on_close(self, pnl: float, market_health: float):
        """
        נקרא אחרי כל סגירת עסקה.
        """
        # בדיקת יום חדש
        if datetime.now().date() > self.daily_start.date():
            self.daily_pnl = 0.0
            self.daily_start = datetime.now()
            self.consecutive_losses = 0

        self.daily_pnl += pnl

        # 3 הפסדים רצופים
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.consecutive_losses >= 3:
            self.block("3 consecutive losses", hours=12)

        # Drawdown יומי 5%
        if self.daily_pnl < -5.0:  # נניח 5% מתיק 500$ = 25$
            self.block("Daily drawdown >5%", until_tomorrow=True)

        # Market Health נמוך
        if market_health < 25:
            self.block("Market Health < 25", hours=1)

    def block(self, reason: str, hours: int = 0, until_tomorrow: bool = False):
        self.trading_blocked = True
        self.block_reason = reason
        if until_tomorrow:
            tomorrow = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
            self.block_until = tomorrow
        elif hours > 0:
            self.block_until = datetime.now() + timedelta(hours=hours)
        log.warning(f"Circuit Breaker: {reason}. Blocked until {self.block_until}")

    def can_trade(self) -> bool:
        if not self.trading_blocked:
            return True
        if self.block_until and datetime.now() > self.block_until:
            self.trading_blocked = False
            log.info("Circuit Breaker: block expired, trading resumed")
            return True
        return False

    def status(self) -> str:
        if self.trading_blocked:
            return f"BLOCKED: {self.block_reason} until {self.block_until}"
        return "ACTIVE"
