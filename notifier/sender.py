"""
CRYPTO-BOT Elite — Telegram Renderer v3
פילוסופיה: מטבעות שיכולים לעשות 50%-100% היום.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)


def _fmt_price(p: float) -> str:
    if p <= 0:      return "—"
    if p >= 100:    return f"{p:.2f}"
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    if p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"

def _medal(i: int) -> str:
    return ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}."

def _regime_line(r: str) -> tuple[str, str]:
    m = {
        "TRENDING_BULL": ("🟢 שוק עולה",  "היום מחפשים פוטנציאל 50%+ עם מומנטום"),
        "ALTSEASON":     ("🚀 עונת אלטים", "היום מחפשים פוטנציאל 100%+ — אגרסיביים"),
        "RANGE":         ("🟡 שוק מדשדש",  "היום מחפשים רק פוטנציאל 50%+ חזק"),
        "RISK_OFF":      ("🔴 שוק בפחד",   "היום ממתינים — סיכון גבוה"),
        "TRENDING_BEAR": ("⛔ שוק יורד",   "היום לא קונים — ממתינים לתחתית"),
    }
    return m.get(r, ("📊 שוק", ""))

def _probability(flow: float, pre: float, oi: float,
                 compressed: bool, whale: bool) -> int:
    """הסתברות למהלך גדול 0-100%"""
    score = (
        flow  * 0.35 +
        pre   * 0.30 +
        min(oi * 5, 20) +
        (10 if compressed else 0) +
        (5  if whale else 0)
    )
    return min(99, max(1, round(score)))

def _prob_emoji(p: int) -> str:
    if p >= 70: return "🟢"
    if p >= 50: return "🟡"
    if p >= 35: return "🟠"
    return "🔴"

def _stars(p: int) -> str:
    if p >= 75: return "★★★★★"
    if p >= 60: return "★★★★☆"
    if p >= 45: return "★★★☆☆"
    if p >= 30: return "★★☆☆☆"
    return "★☆☆☆☆"

def _positives(c: dict) -> list[str]:
    pos = []
    if c.get("vol_explosion"):            pos.append("💥 פיצוץ נפח — נבנה בנרות האחרונים")
    if c.get("flow_score", 0) >= 60:     pos.append("Flow מתחזק")
    if c.get("oi_change", 0) > 2:        pos.append(f"OI קפץ {c['oi_change']:+.1f}%")
    if c.get("is_compressed"):            pos.append("Compression נשבר")
    if c.get("rs_1h", 0) > 0.5:         pos.append(f"חזק מ-BTC ב-{c['rs_1h']:+.1f}%")
    elif c.get("rs_1h", 0) > 0:         pos.append("חזק מ-BTC")
    if c.get("whale_detected"):           pos.append("לווייתנים פעילים")
    if c.get("momentum_1h", 0) > 1.5:   pos.append(f"מומנטום חזק {c['momentum_1h']:+.1f}%")
    if c.get("is_sympathy"):             pos.append(f"גורר אחרי {c.get('leader','').replace('USDT','')}")
    return pos

def _negatives(c: dict) -> list[str]:
    neg = []
    if c.get("oi_change", 0) <= 0:       neg.append("OI עדיין לא עולה")
    if not c.get("is_compressed"):        neg.append("אין Compression")
    if c.get("rs_1h", 0) <= 0:          neg.append("חולשה מול BTC")
    if c.get("flow_score", 0) < 55:      neg.append("Flow עדיין חלש")
    return neg[:3]


def _format_buy(medal: str, c: dict, prob: int) -> str:
    pos = _positives(c)
    ep  = c.get("entry_price", 0)
    sl  = c.get("entry_sl", 0)
    tp1 = c.get("entry_tp1", 0)
    tp2 = c.get("entry_tp2", 0)

    lines = [
        f"🚨 BUY NOW",
        f"",
        f"{medal} {c['symbol'].replace('USDT','')}",
        f"{_stars(prob)}",
        f"",
        f"סיכוי גבוה למהלך 50%-100%",
        f"",
        f"כניסה:       {_fmt_price(ep)}",
        f"סטופ:        {_fmt_price(sl)}",
        f"יעד ראשון:   {_fmt_price(tp1)}",
        f"יעד שני:     {_fmt_price(tp2)}",
        f"R:R:         {c.get('entry_rr',0):.1f}x",
    ]
    if pos:
        lines += ["", "למה עכשיו?"]
        for p in pos: lines.append(f"  ✅ {p}")
    return "\n".join(lines)


def _format_prepare(medal: str, c: dict, prob: int) -> str:
    pos = _positives(c)
    neg = _negatives(c)
    sym = c['symbol'].replace('USDT','')

    lines = [
        f"{medal} {sym}",
        f"{_prob_emoji(prob)} הסתברות למהלך גדול: {prob}%",
        f"💰 מחיר: {_fmt_price(c.get('price',0))}",
    ]
    if pos:
        lines += ["", "למה ברשימה?"]
        for p in pos: lines.append(f"  ✅ {p}")
    if neg:
        lines += ["", "מה עדיין חסר?"]
        for n in neg: lines.append(f"  ❌ {n}")
    lines += [
        "",
        "👉 פעולה:",
        "להוסיף ל-Watchlist.",
        "לחכות לפריצה.",
    ]
    return "\n".join(lines)


def _format_watch(medal: str, c: dict, prob: int) -> str:
    sym = c['symbol'].replace('USDT','')
    action = "רק מעקב.\nעדיין לא מספיק חזק." if prob >= 40 else "לא מומלץ כרגע."
    return f"{medal} {sym}\n{_prob_emoji(prob)} הסתברות: {prob}%\n\n👉 {action}"


def format_message(coins: list[dict], **kwargs) -> str:
    if not coins:
        return (
            "🔥 CRYPTO-BOT ELITE\n\n"
            "❌ אין כרגע מועמדים למהלך גדול.\n\n"
            "⏳ ממשיכים לסרוק."
        )

    regime = coins[0].get("regime", "")
    r_title, r_tip = _regime_line(regime)

    lines = [
        "🔥 CRYPTO-BOT ELITE",
        "",
        f"📊 מצב שוק: {r_title}",
    ]
    if r_tip:
        lines.append(f"🎯 {r_tip}")
    lines.append("")

    buy_coins     = [c for c in coins if c.get("signal") == "BUY"]
    prepare_coins = [c for c in coins if c.get("signal") == "PREPARE"]
    watch_coins   = [c for c in coins if c.get("signal") == "WATCH"]

    # ── BUY ──────────────────────────────────────────────────────────────────
    for i, c in enumerate(buy_coins):
        prob = _probability(c.get("flow_score",0), c.get("pre_score",0),
                            c.get("oi_change",0), c.get("is_compressed",False),
                            c.get("whale_detected",False))
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(_format_buy(_medal(i), c, prob))
        lines.append("")

    # ── PREPARE ───────────────────────────────────────────────────────────────
    if prepare_coins or watch_coins:
        lines.append("━━━━━━━━━━━━━━━━━━")

    idx = 0
    for c in prepare_coins:
        prob = _probability(c.get("flow_score",0), c.get("pre_score",0),
                            c.get("oi_change",0), c.get("is_compressed",False),
                            c.get("whale_detected",False))
        lines.append(_format_prepare(_medal(idx), c, prob))
        lines.append("")
        idx += 1

    # ── WATCH ─────────────────────────────────────────────────────────────────
    for c in watch_coins:
        prob = _probability(c.get("flow_score",0), c.get("pre_score",0),
                            c.get("oi_change",0), c.get("is_compressed",False),
                            c.get("whale_detected",False))
        lines.append(_format_watch(_medal(idx), c, prob))
        lines.append("")
        idx += 1

    return "\n".join(lines).strip()


def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None) -> bool:
    if filtered:
        display = filtered.get("buy",[]) + filtered.get("prepare",[]) + filtered.get("watch",[])
    else:
        display = coins

    text = format_message(display)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    text[:4096],
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False
