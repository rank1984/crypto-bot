"""
CRYPTO-BOT Elite — Telegram Renderer
עונה על: מה לעשות, למה, מה חסר, איפה כניסה.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)


def _fmt_price(p: float) -> str:
    if p <= 0:       return "—"
    if p >= 1:       return f"{p:.4f}"
    if p >= 0.01:    return f"{p:.5f}"
    if p >= 0.0001:  return f"{p:.6f}"
    return f"{p:.8f}"

def _fmt_pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _flow_label(f: float) -> str:
    if f >= 70: return "🟢 חזקה"
    if f >= 50: return "🟡 בינונית"
    return "🔴 חלשה"

def _why_positive(c: dict) -> list[str]:
    pos = []
    if c.get("flow_score", 0) >= 60:       pos.append("Flow חזק")
    if c.get("oi_change", 0) > 2:          pos.append("OI עולה — כסף נכנס")
    if c.get("is_compressed"):             pos.append("Compression — שקט לפני סערה")
    if c.get("rs_1h", 0) > 0:             pos.append("חוזק מול BTC")
    if c.get("whale_detected"):            pos.append("פעילות לווייתנים")
    if c.get("momentum_1h", 0) > 1:       pos.append(f"מומנטום 1H {_fmt_pct(c.get('momentum_1h',0))}")
    if c.get("is_sympathy"):              pos.append(f"Sympathy אחרי {c.get('leader','').replace('USDT','')}")
    return pos

def _why_missing(c: dict) -> list[str]:
    neg = []
    if c.get("flow_score", 0) < 60:       neg.append("Flow מעל 60")
    if c.get("oi_change", 0) <= 0:        neg.append("OI עולה")
    if not c.get("is_compressed"):        neg.append("Compression")
    if c.get("rs_1h", 0) <= 0:           neg.append("חוזק מול BTC")
    if c.get("entry_decision") != "BUY":  neg.append("אישור פריצה")
    return neg[:3]

def _medal(i: int) -> str:
    return ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}."

def _regime_label(r: str) -> str:
    return {"TRENDING_BULL":"🟢 טרנד עולה","ALTSEASON":"🚀 עונת אלטים",
            "RANGE":"🟡 ללא כיוון","RISK_OFF":"🔴 שוק בפחד",
            "TRENDING_BEAR":"⛔ טרנד יורד"}.get(r, "")


def _format_coin(i: int, c: dict) -> str:
    sig   = c.get("signal", "NO")
    sym   = c["symbol"]
    price = c.get("price", 0)
    flow  = c.get("flow_score", 0)
    pre   = c.get("pre_score", 0)
    pos   = _why_positive(c)
    neg   = _why_missing(c)

    lines = [f"{_medal(i)} {sym}",
             f"💰 מחיר: {_fmt_price(price)}",
             f"🌊 Flow: {flow:.0f}/100 {_flow_label(flow)}  |  📈 Pre: {pre:.0f}/100",
             ""]

    if sig == "BUY":
        ep  = c.get("entry_price", 0)
        sl  = c.get("entry_sl", 0)
        tp1 = c.get("entry_tp1", 0)
        tp2 = c.get("entry_tp2", 0)
        rr  = c.get("entry_rr", 0)
        lines += [
            "🟢 פעולה: קנה",
            "",
            f"📌 כניסה:    {_fmt_price(ep)}",
            f"🛑 סטופ:     {_fmt_price(sl)}",
            f"🎯 יעד 1:    {_fmt_price(tp1)}",
            f"🎯 יעד 2:    {_fmt_price(tp2)}",
            f"⚖️ R:R:      {rr:.1f}x",
        ]
        if pos:
            lines.append("")
            lines.append("למה?")
            for p in pos: lines.append(f"  ✅ {p}")

    elif sig == "PREPARE":
        lines += [
            "🟡 פעולה: התכונן",
            "",
            "הכסף מתחיל להיכנס — עדיין אין טריגר.",
            "",
            "מה לעשות?",
            "  ✅ הוסף ל-Watchlist",
            "  ✅ עקוב ב-30 הדקות הקרובות",
        ]
        if neg:
            lines.append("")
            lines.append("מה עוד חסר?")
            for n in neg: lines.append(f"  ❌ {n}")

    else:  # WATCH / NO
        lines += ["👀 פעולה: עקוב בלבד", ""]
        if pos:
            lines.append("מה חיובי?")
            for p in pos: lines.append(f"  ✅ {p}")
        if neg:
            lines.append("")
            lines.append("מה חסר?")
            for n in neg: lines.append(f"  ❌ {n}")

    return "\n".join(lines)


def format_message(coins: list[dict], **kwargs) -> str:
    if not coins:
        return "🔥 CRYPTO-BOT Elite\n\n❌ אין כרגע Setup איכותי.\n⏳ סבלנות."

    regime = coins[0].get("regime","") if coins else ""
    header = ["🔥 CRYPTO-BOT Elite"]
    if regime:
        header.append(f"📊 {_regime_label(regime)}")

    buy_coins     = [c for c in coins if c.get("signal") == "BUY"]
    prepare_coins = [c for c in coins if c.get("signal") == "PREPARE"]
    watch_coins   = [c for c in coins if c.get("signal") == "WATCH"]

    sections = []

    if buy_coins:
        sections.append("━━━━━━━━━━━━\n🚨 BUY ALERT")
        for i, c in enumerate(buy_coins):
            sections.append(_format_coin(i, c))

    if prepare_coins:
        sections.append("━━━━━━━━━━━━\n🟡 PREPARE")
        for i, c in enumerate(prepare_coins):
            sections.append(_format_coin(i, c))

    if watch_coins:
        sections.append("━━━━━━━━━━━━\n👀 WATCH")
        for i, c in enumerate(watch_coins):
            sections.append(_format_coin(i, c))

    if not sections:
        sections = ["━━━━━━━━━━━━"]
        for i, c in enumerate(coins[:3]):
            sections.append(_format_coin(i, c))

    return "\n".join(header + sections)


def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None) -> bool:
    # אם filtered קיים — שלח לפיו, אחרת שלח את coins ישירות
    if filtered:
        display = filtered.get("buy",[]) + filtered.get("prepare",[]) + filtered.get("watch",[])
    else:
        display = coins

    text = format_message(display)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing:")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    text,
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        # fallback ללא formatting
        try:
            plain = format_message(display)
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain[:4000]}, timeout=10)
        except Exception:
            pass
        return False
