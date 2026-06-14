"""
CRYPTO-BOT Elite — Cache
שמירת נרות לדיסק כדי לא לחרוג מ-Binance rate limits.
"""
import json
import os
import time
from pathlib import Path

from utils.config import CACHE_DIR, CACHE_TTL_SECONDS
from utils.logger import get_logger

log = get_logger(__name__)


def _path(symbol: str, tf: str) -> Path:
    return Path(CACHE_DIR) / f"{symbol}_{tf}.json"


def load(symbol: str, tf: str) -> list | None:
    """Return cached candles if still fresh, else None."""
    p = _path(symbol, tf)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        age = time.time() - data["ts"]
        if age < CACHE_TTL_SECONDS:
            return data["candles"]
        log.debug(f"Cache stale ({age:.0f}s) for {symbol}/{tf}")
        return None
    except Exception as e:
        log.warning(f"Cache read error {p}: {e}")
        return None


def save(symbol: str, tf: str, candles: list) -> None:
    """Persist candles to disk."""
    p = _path(symbol, tf)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({"ts": time.time(), "candles": candles}))
    except Exception as e:
        log.warning(f"Cache write error {p}: {e}")
