"""
notifier/sender.py — v10.0

Changes from v8.9:
  - ADD: retry with exponential backoff (3 attempts)
  - ADD: rate limit handling (429 with retry_after)
  - ADD: 5xx retry (server errors are transient)
  - ADD: 1-second minimum interval between sends (avoid rate limit)
  - KEEP: SILENT_MODE behavior (unchanged)
"""
import os
import time
import requests

from utils.logger import get_logger

log = get_logger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

try:
    from utils.config import SILENT_MODE as _SILENT_FROM_CONFIG
    SILENT_MODE = _SILENT_FROM_CONFIG
except Exception:
    SILENT_MODE = os.getenv("SILENT_MODE", "true").lower() == "true"

# ── Retry config ──────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 15]  # seconds between attempts
MIN_INTERVAL = 1.0          # min seconds between any two sends
_LAST_SEND_TS = 0.0


def send_simple_message(text: str) -> bool:
    global _LAST_SEND_TS

    if SILENT_MODE:
        preview = text[:120].replace("\n", " | ")
        log.info(f"[SILENT_MODE] Message suppressed ({len(text)} chars): {preview}...")
        return True

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials missing — message not sent")
        return False

    # Rate limit — 1 second minimum between sends
    now = time.time()
    wait = MIN_INTERVAL - (now - _LAST_SEND_TS)
    if wait > 0:
        time.sleep(wait)
    _LAST_SEND_TS = time.time()

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, json=payload, timeout=10)

            if r.status_code == 200:
                log.info("Telegram message sent ✓")
                return True

            if r.status_code == 429:
                try:
                    retry_after = r.json().get("parameters", {}).get("retry_after", 30)
                except Exception:
                    retry_after = 30
                log.warning(f"Telegram rate limit — waiting {retry_after}s")
                time.sleep(min(int(retry_after), 60))
                continue

            if r.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    log.warning(f"Telegram 5xx ({r.status_code}) — retrying")
                    time.sleep(RETRY_DELAYS[attempt])
                    continue
                log.error(f"Telegram server error after {MAX_RETRIES} attempts: {r.status_code}")
                return False

            # 4xx (client error) — don't retry
            log.error(f"Telegram error {r.status_code}: {r.text[:200]}")
            return False

        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt < MAX_RETRIES - 1:
                log.warning(f"Telegram attempt {attempt+1} failed: {e} — retrying")
                time.sleep(RETRY_DELAYS[attempt])
                continue
            log.error(f"Telegram failed after {MAX_RETRIES} attempts: {e}")
            return False

        except Exception as e:
            log.error(f"Telegram unexpected error: {e}")
            return False

    return False
