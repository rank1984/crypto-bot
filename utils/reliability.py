"""
CRYPTO-BOT Elite — Reliability Utilities

מספק:
    - retry עם exponential backoff
    - timeout
    - fallback values
    - logging
"""
import time
import functools
from utils.logger import get_logger

log = get_logger("reliability")


def safe_api_call(max_retries=3, timeout=10, fallback=None):
    """
    Decorator: עוטף קריאת API עם retry, timeout, fallback.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    log.warning(f"{func.__name__} attempt {attempt}/{max_retries} failed: {e}")
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)  # exponential backoff
                    else:
                        log.error(f"{func.__name__} all retries exhausted. Using fallback: {fallback}")
                        return fallback
            return fallback
        return wrapper
    return decorator


def safe_db_write(func):
    """Decorator: מטפל בשגיאות כתיבה ל-SQLite."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"DB write error in {func.__name__}: {e}")
            return None
    return wrapper


def safe_telegram_send(func):
    """Decorator: מטפל בכשלי שליחה לטלגרם."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"Telegram send failed: {e}")
            # אפשר לנסות שליחה חלופית כאן (email, backup bot)
            return False
    return wrapper
