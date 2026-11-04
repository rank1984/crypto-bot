"""
notifier/sender.py — v8.9 with SILENT_MODE
Suppresses all Telegram messages when SILENT_MODE is on.
"""
import os
import requests

from utils.logger import get_logger

log = get_logger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Try to import from config, fallback to env
try:
    from utils.config import SILENT_MODE as _SILENT_FROM_CONFIG
    SILENT_MODE = _SILENT_FROM_CONFIG
except Exception:
    SILENT_MODE = os.getenv("SILENT_MODE", "true").lower() == "true"


def send_simple_message(text: str) -> bool:
    """
    Send a message to Telegram.
    If SILENT_MODE is on, log instead of sending.
    Returns True if sent (or suppressed), False on error.
    """
    if SILENT_MODE:
        # Log to stdout only, no Telegram
        preview = text[:120].replace("\n", " | ")
        log.info(f"[SILENT_MODE] Message suppressed ({len(text)} chars): {preview}...")
        return True

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials missing — message not sent")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("Telegram message sent ✓")
            return True
        else:
            log.error(f"Telegram error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False