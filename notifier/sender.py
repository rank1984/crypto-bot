"""
CRYPTO-BOT Elite — Telegram Sender
מעצב ושולח את ה-top picks לטלגרם.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

_GRADES = [
    (90, "A+"), (80, "A"), (70, "A-"),
    (60, "B+"), (50, "B"), (0,  "B-"),
]


def _grade(score: float) -> str:
    for threshold, letter in _GRADES:
        if score >= threshold:
            return letter
    return "C"


def _fmt_pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


def _fmt_price(p: float) -> str:
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    if p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"


def format_message(top_coins: list[dict]) -> str:
    lines = ["🔥 *CRYPTO-BOT Elite*\n"]

    for i, c in enumerate(top_coins, 1):
        grade = _grade(c["final_score"])
        sym   = c["symbol"]  # אין צורך בריפוד תווים מיוחדים במצב Markdown רגיל

        block = [
            f"*{i}. {sym}* [{grade}]",
            f"💰 Price: `{_fmt_price(c['price'])}`",
            "",
            f"📈 *Momentum*",
            f"  3m  {_fmt_pct(c['momentum_3m'])}",
            f"  5m  {_fmt_pct(c['momentum_5m'])}",
            f"  15m {_fmt_pct(c['momentum_15m'])}",
            f"  1h  {_fmt_pct(c['momentum_1h'])}",
            "",
            f"🚀 Vol Accel: `{c['vol_accel']:.1f}x`",
            f"📊 RVOL: `{c['rvol']:.1f}x`",
            f"🟢 VWAP dist: `{_fmt_pct(c['vwap_dist'])}`",
            f"📐 RSI-14: `{c['rsi_14']:.0f}`",
            "",
            f"🎯 Breakout Score: `{c['breakout_score']:.0f}`",
            f"⭐ *Final Score: {c['final_score']:.0f}*",
        ]
        lines.append("\n".join(block))
        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)


def send_telegram(top_coins: list[dict]) -> bool:
    """
    Returns True on success.
    Uses legacy Markdown parse mode to avoid escaping strictness.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — printing to stdout")
        print(format_message(top_coins))
        return False

    text = format_message(top_coins)
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "Markdown",  # שונה מ-MarkdownV2 ל-Markdown
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram message sent ✓")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False
