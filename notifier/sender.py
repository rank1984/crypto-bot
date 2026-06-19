"""
CRYPTO-BOT Elite — Telegram Sender (Optimized for Speed)
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

def _fmt_pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _fmt_price(p: float) -> str:
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    return f"{p:.8f}"

def format_message(top_coins: list[dict]) -> str:
    lines = ["🔥 <b>CRYPTO-BOT Elite</b>"]
    
    if top_coins:
        regime = top_coins[0].get("regime", "UNKNOWN")
        lines.append(f"<b>מצב שוק:</b> <code>{regime}</code>\n")

    for i, c in enumerate(top_coins, 1):
        # סיגנל כניסה (BUY / WAIT)
        decision = c.get("entry_decision", "WAIT")
        emoji = "🟢" if decision == "BUY" else "🟡"
        
        # בניית הבלוק הקומפקטי
        block = [
            f"<b>{i}. {c['symbol'].replace('USDT', '')}</b> | [ציון: {c['final_score']:.0f}]",
            f"{emoji} <b>{decision}</b> 🎯 פריצה: <code>{c.get('breakout_score', 0):.0f}</code>",
            f"💰 מחיר: <code>{_fmt_price(c['price'])}</code> | RVOL: <code>{c.get('rvol', 0):.1f}x</code>",
            f"⏱ מומנטום: 15ד' <code>{_fmt_pct(c.get('momentum_15m', 0))}</code> | 1ש' <code>{_fmt_pct(c.get('momentum_1h', 0))}</code>",
            f"💪 חוזק מול BTC: 1ש' <code>{_fmt_pct(c.get('rs_1h', 0))}</code> | 4ש' <code>{_fmt_pct(c.get('rs_4h', 0))}</code>"
        ]
        
        lines.append("\n".join(block))
        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)

def send_telegram(top_coins: list[dict]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(format_message(top_coins))
        return False

    text = format_message(top_coins)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        # שימוש ב-HTML מאפשר הודעות נקיות בלי Escape מסובך
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML", 
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False
