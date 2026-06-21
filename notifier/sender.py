"""
CRYPTO-BOT Elite — Telegram Pro (עברית)
פורמט מקצועי: למה נבחר, מה חסר, האם כדאי לעקוב.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _e(s: str) -> str:
    """Escape MarkdownV2"""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, f"\\{c}")
    return s

def _fmt_price(p: float) -> str:
    if p <= 0:      return "—"
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    if p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"

def _fmt_pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _grade(s: float) -> str:
    for t, l in [(90,"A+"),(80,"A"),(70,"A-"),(60,"B+"),(50,"B"),(0,"B-")]:
        if s >= t: return l
    return "C"

def _flow_label(f: float) -> str:
    if f >= 80: return "🔥 חזקה מאוד"
    if f >= 60: return "🟢 חזקה"
    if f >= 40: return "🟡 בינונית"
    if f >= 20: return "🟠 חלשה"
    return "🔴 חלשה מאוד"

def _phase_label(f: float) -> str:
    if f >= 80: return "⚡ פריצה קרובה"
    if f >= 60: return "👀 מעקב צמוד"
    if f >= 40: return "🟡 התחלת בנייה"
    return "😴 מוקדם מדי"

def _time_window(f: float, setup: str) -> str:
    if f >= 80: return "15–45 דקות"
    if f >= 60: return "30–90 דקות"
    if setup == "BREAKOUT": return "1–3 שעות"
    return "2–6 שעות"

def _regime_label(r: str) -> str:
    return {
        "TRENDING_BULL": "🟢 טרנד עולה",
        "ALTSEASON":     "🚀 עונת אלטים",
        "RANGE":         "🟡 שוק ללא כיוון",
        "RISK_OFF":      "🔴 שוק בפחד",
        "TRENDING_BEAR": "⛔ טרנד יורד",
    }.get(r, "⚪ לא ידוע")

def _rank_medal(i: int) -> str:
    return ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}."

def _build_reasons(c: dict) -> tuple[list[str], list[str]]:
    """מחזיר (✓ חיוביים, ✗ שליליים)"""
    pos, neg = [], []

    # Flow components
    comp = c.get("flow_components", {})
    if comp.get("oi", 0) >= 10:      pos.append("OI Expansion")
    else:                             neg.append("OI חלש")
    if comp.get("cvd", 0) >= 10:     pos.append("CVD חיובי — קונים תוקפים")
    if comp.get("funding", 0) >= 8:  pos.append("Funding בריא")
    elif comp.get("funding", 0) < 4: neg.append("Funding קיצוני")
    if comp.get("rs", 0) >= 15:      pos.append("חוזק מול BTC ו־ETH")
    elif comp.get("rs", 0) >= 7:     pos.append("חוזק מול BTC")
    else:                             neg.append("חולשה מול BTC")
    if comp.get("compression", 0) >= 7: pos.append("Compression — שקט לפני סערה")
    if comp.get("whale", 0) >= 7:    pos.append("פעילות Whale")
    else:                             neg.append("אין פעילות Whale")

    # Momentum
    m1h = c.get("momentum_1h", 0)
    m15 = c.get("momentum_15m", 0)
    if m1h > 2:   pos.append(f"מומנטום 1H חזק \\({_fmt_pct(m1h)}\\)")
    elif m1h < 0: neg.append("מומנטום 1H שלילי")
    if m15 > 1:   pos.append(f"מומנטום 15m חיובי")

    # RSI
    rsi = c.get("rsi_14", 50)
    if 50 <= rsi <= 65:  pos.append(f"RSI אידאלי \\({rsi:.0f}\\)")
    elif rsi > 75:        neg.append(f"RSI מתוח \\({rsi:.0f}\\)")

    # Entry
    dec = c.get("entry_decision", "NO")
    if dec == "BUY":      pos.append("טריגר כניסה הופעל")
    elif dec == "WAIT":   neg.append("טרם התקבל אישור פריצה")
    else:                 neg.append("אין טריגר כניסה")

    # Sympathy
    if c.get("is_sympathy") and c.get("leader"):
        pos.append(f"Sympathy אחרי {c['leader'].replace('USDT','')}")

    return pos[:5], neg[:3]   # מקסימום 5 חיוביים, 3 שליליים


# ─── Main Formatter ───────────────────────────────────────────────────────────

def format_message(top_coins: list[dict]) -> str:
    lines = ["🔥 *CRYPTO\\-BOT Elite*"]

    # כותרת שוק
    if top_coins:
        regime = top_coins[0].get("regime", "")
        lines.append(f"📊 מצב שוק: {_e(_regime_label(regime))}")
    lines.append("")

    for i, c in enumerate(top_coins):
        sym      = c["symbol"]
        score    = c.get("final_score", 0)
        flow     = c.get("flow_score", 0)
        dec      = c.get("entry_decision", "NO")
        setup    = c.get("entry_setup", "")
        phase    = _phase_label(flow)
        pos_r, neg_r = _build_reasons(c)

        # ── כותרת מטבע ───────────────────────────────────────────────────────
        lines.append(f"{_rank_medal(i)} *{_e(sym)}*")
        lines.append(f"👑 ציון: `{score:.0f}` \\[{_grade(score)}\\]   🌊 Flow: `{flow:.0f}` {_e(_flow_label(flow))}")

        # ── שלב ──────────────────────────────────────────────────────────────
        lines.append(f"⚡ שלב: {phase}")

        # ── מחיר + נתוני volume ──────────────────────────────────────────────
        lines.append(
            f"💰 מחיר: `{_fmt_price(c.get('price',0))}` \\| "
            f"RVOL: `{c.get('rvol',0):.1f}x` \\| "
            f"RSI: `{c.get('rsi_14',0):.0f}`"
        )

        # ── מצב כניסה ────────────────────────────────────────────────────────
        if dec == "BUY":
            lines.append(f"🎯 מצב כניסה: 🟢 *BUY* — {_e(setup)}")
            lines.append(f"📌 כניסה: `{_fmt_price(c.get('entry_price',0))}`")
            lines.append(f"🛑 SL: `{_fmt_price(c.get('entry_sl',0))}`  🎯 TP1: `{_fmt_price(c.get('entry_tp1',0))}`  TP2: `{_fmt_price(c.get('entry_tp2',0))}`")
            lines.append(f"⚖️ R:R: `{c.get('entry_rr',0):.1f}x`")
        elif dec == "WAIT":
            lines.append(f"🎯 מצב כניסה: 🟡 המתנה — Setup: {_e(setup)}")
            lines.append(f"⏳ חלון זמן צפוי: {_e(_time_window(flow, setup))}")
        else:
            lines.append("🎯 מצב כניסה: 🔴 אין טריגר")

        # ── מומנטום קצר ──────────────────────────────────────────────────────
        lines.append(
            f"⏱ Mom: "
            f"5m `{_fmt_pct(c.get('momentum_5m',0))}` "
            f"15m `{_fmt_pct(c.get('momentum_15m',0))}` "
            f"1h `{_fmt_pct(c.get('momentum_1h',0))}`  "
            f"BTC RS: `{_fmt_pct(c.get('rs_1h',0))}`"
        )

        # ── סיבות ────────────────────────────────────────────────────────────
        if pos_r or neg_r:
            reason_lines = []
            for r in pos_r: reason_lines.append(f"  ✓ {_e(r)}")
            for r in neg_r: reason_lines.append(f"  ✗ {_e(r)}")
            lines.append("\n".join(reason_lines))

        # ── תגית מועמד ───────────────────────────────────────────────────────
        if flow >= 60 and dec == "WAIT":
            lines.append("💡 *מועמד חזק למהלך*")
        elif flow >= 40 and dec == "NO":
            lines.append("👁 *שווה מעקב*")

        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────

def send_telegram(top_coins: list[dict]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing to stdout")
        print(format_message(top_coins))
        return False

    text = format_message(top_coins)
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "MarkdownV2",
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram MarkdownV2 failed: {e}")
        # fallback: טקסט פשוט
        try:
            plain = "CRYPTO-BOT Elite\n\n"
            for i, c in enumerate(top_coins):
                dec = c.get("entry_decision","NO")
                icon = "🟢" if dec=="BUY" else "🟡" if dec=="WAIT" else "🔴"
                plain += (
                    f"{_rank_medal(i)} {c['symbol']}\n"
                    f"ציון: {c.get('final_score',0):.0f} | Flow: {c.get('flow_score',0):.0f}\n"
                    f"{icon} {dec}"
                )
                if dec == "BUY":
                    plain += f" | כניסה: {_fmt_price(c.get('entry_price',0))}"
                plain += "\n\n"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
        except Exception:
            pass
        return False
