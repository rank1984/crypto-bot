"""
CRYPTO-BOT Elite — Why Not Engine
"""
from utils.logger import get_logger

log = get_logger("why_not")

def log_rejection(symbol: str, reason: str, details: dict = None):
    """
    שומר לקובץ / DB את סיבת הפסילה.
    """
    log.info(f"REJECTED {symbol}: {reason}")
    # later: write to DB
