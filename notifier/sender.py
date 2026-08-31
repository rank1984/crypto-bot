"""
notifier/sender.py
עיצוב ושליחת הודעות לטלגרם - פורמט ממוקד, קריא וגמיש.
"""
import requests
from datetime import datetime
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)


def _fmt_price(p: float) -> str:
    if not p or p <= 0:
        return "—"
    if p >= 100:
        return f"{p:.2f}"
    if p >= 1:
        return f"{p:.4f}"
    if p >= 0.001:
        return f"{p:.5f}"
    return f"{p:.8f}"


def _build_buy_message(c: dict) -> str:
    """הודעת איתות חדה כשיש BUY."""
    sym = c.get('symbol', '').replace('USDT', '')
    entry = float(c.get('entry_price', c.get('price', c.get('last_price', 0))) or 0)
    sl = float(c.get('stop_loss', c.get('sl', c.get('entry_sl', entry * 0.97))) or 0)
    tp1 = float(c.get('target_1', c.get('tp1', c.get('entry_tp1', entry * 1.05))) or 0)
    
    risk_pct = (abs(entry - sl) / entry * 100) if entry > 0 else 0.0
    ai_score = c.get('ai_score', 0)
    rs_score = float(c.get('rs_1h', 0) or 0)

    lines = [
        f"🟢 BUY: {sym}",
        f"כניסה: {_fmt_price(entry)}  |  סטופ: {_fmt_price(sl)}  |  יעד: {_fmt_price(tp1)}",
        f"סיכון: {risk_pct:.1f}%  |  AI: {ai_score}  |  RS: {rs_score:.2f}",
        "",
        f"/done {sym} <מחיר> — אחרי קנייה",
        f"/skip {sym} <סיבה> — אם לא נכנסת",
    ]
    return "\n".join(lines)


def _build_watch_message(coins: list[dict], market_health: float, regime: str) -> str:
    """הודעת מעקב קצרה ונקייה כשאין BUY."""
    top = coins[0] if coins else None
    now = datetime.now().strftime("%H:%M")

    lines = [f"🔴 CRYPTO-BOT | {now} | {regime} | שוק {market_health:.0f}/100"]
    lines.append("אין הזדמנות כרגע.")
    lines.append("")

    if top:
        sym = top.get('symbol', '').replace('USDT', '')
        ai = top.get('ai_score', 0)
        dist = top.get('trigger_distance_pct')
        
        dist_str = ""
        if dist is not None:
            dist_val = float(dist)
            if abs(dist_val) <= 1.0:
                dist_str = f", בטריגר! ({dist_val:+.1f}%)"
            else:
                dist_str = f", מרחק: {dist_val:+.1f}%"

        lines.append(f"מוביל: {sym} (AI {ai}{dist_str})")

    others = coins[1:4] if len(coins) > 1 else []
    if others:
        names = ", ".join(c.get('symbol', '').replace('USDT', '') for c in others)
        lines.append(f"{len(others)} נוספים במעקב: {names}")

    return "\n".join(lines)


def format_message(coins: list[dict], market_health: float = 50.0, regime: str = "RANGE", **kwargs) -> str:
    """
    פורמט ההודעה לפי סוג האות (BUY מול WATCH).
    """
    if not coins:
        return "🔴 CRYPTO-BOT\nהשוק שקט. אין הזדמנויות כרגע."

    buy_coins = [
        c for c in coins 
        if c.get('decision') == 'BUY' 
        or c.get('final_decision') == 'BUY' 
        or c.get('signal') == 'BUY'
    ]

    if buy_coins:
        return "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(_build_buy_message(c) for c in buy_coins)

    return _build_watch_message(coins, market_health, regime)


def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0, filtered: dict = None, market_health: float = 50.0, regime: str = "RANGE", **kwargs) -> bool:
    """
    שולח את דוח הבוט לטלגרם.
    """
    display_coins = coins if coins else kwargs.get("all_coins", [])

    if not display_coins:
        log.warning("No coins available for telegram message.")
        return False

    text = format_message(display_coins, market_health=market_health, regime=regime, **kwargs)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096]
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram notification sent successfully ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False


def send_simple_message(text: str) -> bool:
    """שולח הודעת טקסט פשוטה לטלגרם."""
    if not text or not text.strip():
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096]
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram simple message sent ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False
