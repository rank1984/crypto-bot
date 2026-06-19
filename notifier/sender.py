"""
CRYPTO-BOT Elite — Telegram Sender
מעצב ושולח את ה-top picks לטלגרם בעברית ובמבנה קומפקטי לפעולה מהירה.
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
    lines = ["🔥 <b>CRYPTO-BOT Elite</b>\n"]

    # Regime header בתרגום לעברית
    if top_coins:
        regime = top_coins[0].get("regime", "")
        regime_translations = {
            "TRENDING_BULL": "🟢 מגמה שורית (Bull)",
            "ALTSEASON": "🚀 עונת אלטים (Altseason)",
            "RANGE": "🟡 דשדוש (Range)",
            "RISK_OFF": "🔴 סיכון כבוי (Risk-Off)",
            "TRENDING_BEAR": "⛔ מגמה דובית (Bear)"
        }
        regime_text = regime_translations.get(regime, f"⚪ {regime}")
        if regime:
            lines.append(f"<b>מצב שוק:</b> <code>{regime_text}</code>\n")

    for i, c in enumerate(top_coins, 1):
        grade = _grade(c["final_score"])
        sym = c["symbol"].replace("USDT", "") 

        sympathy_line = ""
        if c.get("is_sympathy") and c.get("leader"):
            leader = c["leader"].replace("USDT", "")
            sympathy_line = f"🔗 <b>אפקט סימפתיה אחרי:</b> <code>{leader}</code>"

        # בניית בלוק נתונים קומפקטי ורוחבי בעברית
        block = [
            f"<b>{i}. {sym}</b> [{grade}]",
            f"👑 <b>ציון סופי:</b> <code>{c['final_score']:.0f}</code> | 🎯 <b>פריצה:</b> <code>{c.get('breakout_score', 0):.0f}</code>",
            f"💰 <b>מחיר:</b> <code>{_fmt_price(c['price'])}</code>",
            sympathy_line if sympathy_line else None,
            "",
            f"📊 <b>ווליום:</b> האצה <code>{c.get('vol_accel', 0):.1f}x</code> | יחסי (RVOL) <code>{c.get('rvol', 0):.1f}x</code>",
            f"🟢 <b>מרחק VWAP:</b> <code>{_fmt_pct(c.get('vwap_dist', 0))}</code> | 📐 <b>RSI-14:</b> <code>{c.get('rsi_14', 0):.0f}</code>",
            "",
            f"⏱️ <b>מומנטום:</b> 3ד': <code>{_fmt_pct(c.get('momentum_3m', 0))}</code> | 5ד': <code>{_fmt_pct(c.get('momentum_5m', 0))}</code> | 15ד': <code>{_fmt_pct(c.get('momentum_15m', 0))}</code> | 1ש': <code>{_fmt_pct(c.get('momentum_1h', 0))}</code>",
            f"💪 <b>חוזק מול BTC:</b> שעה: <code>{_fmt_pct(c.get('rs_1h', 0))}</code> | 4 שעות: <code>{_fmt_pct(c.get('rs_4h', 0))}</code>",
        ]
        
        # סינון שורות ריקות (כמו שורת סימפתיה כשאינה רלוונטית)
        lines.append("\n".join(filter(None, block)))
        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)


def send_telegram(top_coins: list[dict]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — printing to stdout")
        print(format_message(top_coins))
        return False

    text = format_message(top_coins)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram message sent ✓")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"Telegram API Response: {e.response.text}")
        return False
