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

    # Regime header
    if top_coins:
        regime = top_coins[0].get("regime", "")
        regime_emoji = {"TRENDING_BULL":"🟢","ALTSEASON":"🚀","RANGE":"🟡","RISK_OFF":"🔴","TRENDING_BEAR":"⛔"}.get(regime, "⚪")
        if regime:
            lines.append(f"{regime_emoji} Regime: <code>{regime}</code>\n")

    for i, c in enumerate(top_coins, 1):
        grade = _grade(c["final_score"])
        # הסרתי את ה-Replace המסורבל שהיה מיועד ל-Markdown
        sym   = c["symbol"].replace("USDT", "") 

        sympathy_line = ""
        if c.get("is_sympathy") and c.get("leader"):
            leader = c["leader"].replace("USDT", "")
            sympathy_line = f"🔗 Sympathy play after <code>{leader}</code>"

        # שימוש ב-HTML מאפשר להכניס מספרים וסימנים חופשי
        block = [
            f"<b>{i}. {sym}</b> [{grade}]",
            sympathy_line if sympathy_line else None,
            f"💰 Price: <code>{_fmt_price(c['price'])}</code>",
            "",
            "📈 <b>Momentum</b>",
            f"  3m  {_fmt_pct(c.get('momentum_3m', 0))}",
            f"  5m  {_fmt_pct(c.get('momentum_5m', 0))}",
            f"  15m {_fmt_pct(c.get('momentum_15m', 0))}",
            f"  1h  {_fmt_pct(c.get('momentum_1h', 0))}",
            "",
            f"🚀 Vol Accel: <code>{c.get('vol_accel', 0):.1f}x</code>",
            f"📊 RVOL: <code>{c.get('rvol', 0):.1f}x</code>",
            f"🟢 VWAP dist: <code>{_fmt_pct(c.get('vwap_dist', 0))}</code>",
            f"📐 RSI-14: <code>{c.get('rsi_14', 0):.0f}</code>",
            "",
            f"🎯 Breakout Score: <code>{c.get('breakout_score', 0):.0f}</code>",
            f"💪 RS vs BTC: <code>{_fmt_pct(c.get('rs_1h', 0))}</code> 1h / <code>{_fmt_pct(c.get('rs_4h', 0))}</code> 4h",
            f"⭐ <b>Final Score: {c['final_score']:.0f}</b>"
        ]
        
        # מסנן שורות ריקות כמו sympathy_line כשאין
        lines.append("\n".join(filter(None, block)))
        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)

def send_telegram(top_coins: list[dict]) -> bool:
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
            "parse_mode": "HTML", # המעבר ל-HTML
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram message sent ✓")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        # הוספתי הדפסה של סיבת השגיאה המדויקת מטלגרם כדי שיעזור בדיבוג עתידי
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"Telegram API Response: {e.response.text}")
        return False
