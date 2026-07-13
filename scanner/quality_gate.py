"""
CRYPTO-BOT Elite — Quality Gate (Legacy - Disabled)
"""
from utils.logger import get_logger

log = get_logger(__name__)


def apply_quality_gate(coin: dict) -> dict:
    """
    מנוטרל לחלוטין כדי למנוע דריסת עסקאות (BUY -> WAIT).
    מחזיר את המטבע כפי שהוא ישירות למערכת.
    """
    return coin


def apply_quality_gate_all(coins: list[dict]) -> list[dict]:
    """הפעל gate על כל המטבעות."""
    return [apply_quality_gate(c) for c in coins]
