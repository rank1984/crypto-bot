"""
CRYPTO-BOT Elite — Stable Telegram Renderer
עיצוב הודעות יציב שלא נשבר מ-MarkdownV2 או דאטה שבור
"""

import requests
from utils.logger import get_logger
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

log = get_logger(__name__)


# ─────────────────────────────────────────────
# Safe text (מונע שבירת Telegram)
# ─────────────────────────────────────────────
def safe_text(text: str) -> str:
    if text is None:
        return ""
    return str(text)


def clean_markdown_v2(text: str) -> str:
    """
    מסיר תווים ששוברים Telegram MarkdownV2
    """
    if not text:
        return ""

    bad_chars = r"_*[]()~`>#+-=|{}.!"
    for c in bad_chars:
        text = text.replace(c, "")
    return text


# ─────────────────────────────────────────────
# Fallback formatter (למצב חירום)
# ─────────────────────────────────────────────
def format_plain(top_coins: list[dict]) -> str:
    lines = ["CRYPTO-BOT Elite\n"]

    for i, c in enumerate(top_coins):
        lines.append(
            f"{i+1}. {c.get('symbol','?')} | "
            f"Score: {c.get('final_score',0):.0f} | "
            f"Flow: {c.get('flow_score',0):.0f} | "
            f"Pre: {c.get('pre_score',0):.0f} | "
            f"Signal: {c.get('signal','?')}"
        )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Main safe renderer
# ─────────────────────────────────────────────
def render_message(top_coins: list[dict]) -> tuple[str, str]:
    """
    מחזיר:
    (markdown_message, plain_message)
    """

    md = ["🔥 *CRYPTO BOT ELITE*"]
    plain = ["CRYPTO-BOT Elite"]

    if not top_coins:
        msg = "No signals"
        return msg, msg

    md.append("━━━━━━━━━━━━")
    plain.append("------------------")

    for i, c in enumerate(top_coins):
        sym   = safe_text(c.get("symbol"))
        score = c.get("final_score", 0)
        flow  = c.get("flow_score", 0)
        pre   = c.get("pre_score", 0)
        sig   = safe_text(c.get("signal", "NO"))

        # Markdown version (safe cleaned)
        md.append(
            f"{i+1}. {sym}\n"
            f"Score: {score:.0f} | Flow: {flow:.0f} | Pre: {pre:.0f}\n"
            f"Signal: {sig}"
        )

        # Plain version (always safe)
        plain.append(
            f"{i+1}. {sym} | Score {score:.0f} | Flow {flow:.0f} | Pre {pre:.0f} | {sig}"
        )

    return "\n".join(md), "\n".join(plain)


# ─────────────────────────────────────────────
# Safe sender with fallback
# ─────────────────────────────────────────────
def send_telegram(top_coins: list[dict]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured")
        print(format_plain(top_coins))
        return False

    md_text, plain_text = render_message(top_coins)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # ── ניסיון 1: Markdown ─────────────────────
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": md_text,
            "parse_mode": "Markdown"
        }, timeout=10)

        if resp.status_code == 200:
            log.info("Telegram sent (Markdown)")
            return True

        raise Exception(resp.text)

    except Exception as e:
        log.warning(f"Markdown failed → fallback to plain. Reason: {e}")

    # ── ניסיון 2: Plain text ───────────────────
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": clean_markdown_v2(plain_text),
            "parse_mode": None
        }, timeout=10)

        resp.raise_for_status()
        log.info("Telegram sent (Plain fallback)")
        return True

    except Exception as e:
        log.error(f"Telegram TOTAL FAIL: {e}")
        return False
