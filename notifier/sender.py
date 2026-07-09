"""
CRYPTO-BOT Elite — Telegram Renderer v5

עונה על 3 שאלות בלבד:
1. יש עסקה עכשיו?
2. אם אין — על מה לעקוב?
3. מה בדיוק חסר?

ללא Pipeline Heatmap, Loss Rate, EV — אלה כלי דיבוג, לא כלי מסחר.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_price(p: float) -> str:
    if p <= 0:      return "—"
    if p >= 100:    return f"{p:.2f}"
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    if p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"

def _medal(i: int) -> str:
    return ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}."

def _regime_line(r: str) -> str:
    return {
        "TRENDING_BULL": "🟢 שוק עולה — כניסות מותרות",
        "ALTSEASON":     "🚀 עונת אלטים — אגרסיביים",
        "RANGE":         "🟡 שוק מדשדש — רק עסקאות חזקות",
        "RISK_OFF":      "🔴 שוק בפחד — זהירות מירבית",
        "TRENDING_BEAR": "⛔ שוק יורד — לא קונים",
    }.get(r, "📊 שוק")

def _ready_pct(c: dict) -> int:
    """אחוז מוכנות — ישירות מ-confidence שכבר מחושב ב-decision_engine."""
    return int(c.get("confidence", c.get("flow_score", 0)))

def _ready_emoji(pct: int) -> str:
    if pct >= 85: return "🟢"
    if pct >= 65: return "🟡"
    return "🔴"

def _what_missing(c: dict) -> list[str]:
    """מה בדיוק חסר — מקסימום 3 דברים. קורא מה-coin, לא מ-decision_engine."""
    rvol_min = c.get("required_rvol", 0.8)   # נשמר ע"י decision_engine
    m = []
    if c.get("oi_change", 0) <= 0:
        m.append("OI עולה")
    if c.get("rvol", 0) < rvol_min:
        m.append(f"RVOL מעל {rvol_min:.1f} (יש {c.get('rvol',0):.1f}x)")
    if c.get("rs_1h", 0) <= 0:
        m.append("חוזק מול BTC")
    if c.get("flow_score", 0) < 55:
        m.append(f"Flow מעל 55 (יש {c.get('flow_score',0):.0f})")
    if c.get("entry_decision","NO") != "BUY":
        m.append("אישור פריצה")
    return m[:3]

def _why_no_signal(stats) -> str:
    """סיבה מבוססת נתונים אמיתיים מהסריקה."""
    if stats is None:
        return "אין כרגע מטבע שעומד בכל התנאים."
    try:
        n        = getattr(stats, "scanned", 0)
        rv_fail  = getattr(stats, "rvol_fail", 0)
        hd_fail  = getattr(stats, "hard_fail", 0)
        sc_fail  = getattr(stats, "score_fail", 0)
        fl_fail  = getattr(stats, "flow_fail", 0)
        si_fail  = getattr(stats, "signal_ignore", 0)

        # בנה breakdown
        parts = []
        if rv_fail > 0: parts.append(f"{rv_fail} נפסלו — RVOL נמוך")
        if hd_fail > 0: parts.append(f"{hd_fail} נפסלו — RSI/VWAP קיצוני")
        if sc_fail > 0: parts.append(f"{sc_fail} נפסלו — Score נמוך")
        if fl_fail > 0: parts.append(f"{fl_fail} נפסלו — Flow/OI חלש")
        if si_fail > 0: parts.append(f"{si_fail} נפסלו — Quality Gate")

        # הסיבה המרכזית
        bn, _ = stats.main_bottleneck()
        reason_map = {
            "RVOL נמוך":    "אין מספיק נפח מסחר (RVOL נמוך).",
            "Flow חלש":     "אין כניסת כסף לשוק (OI/Flow חלש).",
            "Hard Filters": "מטבעות חרגו מגבולות RSI/VWAP.",
            "Score נמוך":   "אין מטבע חזק מספיק.",
            "Signal → IGNORE": "מטבעות לא עמדו ב-Quality Gate.",
        }
        main = reason_map.get(bn, "אין מטבע שעומד בכל התנאים.")
        return main + (" | " + " | ".join(parts[:2]) if parts else "")
    except Exception:
        return "אין כרגע מטבע שעומד בכל התנאים."


def _is_soft(coin: dict) -> bool:
    """Soft candidate: מוכן 40-69%, יכול להפוך ל-BUY תוך 30-90 דקות."""
    return (
        coin.get("rvol", 0) >= 0.8 and
        coin.get("flow_score", 0) >= 40 and
        coin.get("confidence", 0) >= 40
    )

# ─── BUY Format ───────────────────────────────────────────────────────────────

def _format_buy(c: dict) -> str:
    ep  = c.get("entry_price", 0)
    sl  = c.get("entry_sl", 0)
    tp1 = c.get("entry_tp1", 0)
    tp2 = c.get("entry_tp2", 0)
    rr  = c.get("entry_rr", 0)

    conf     = c.get("confidence", 0)
    pos_pct  = 5 if conf >= 85 else (3 if conf >= 70 else 1)
    portfolio = 1000  # ברירת מחדל — אפשר לשנות ב-env
    try:
        import os
        portfolio = float(os.getenv("PORTFOLIO_USD","1000"))
    except Exception:
        pass
    pos_usd  = round(portfolio * pos_pct / 100)

    pos = []
    if c.get("vol_explosion"):            pos.append("💥 פיצוץ נפח")
    if c.get("flow_score", 0) >= 60:     pos.append("Flow חזק")
    if c.get("oi_change", 0) > 2:        pos.append(f"OI עולה {c['oi_change']:+.1f}%")
    if c.get("is_compressed"):            pos.append("Compression")
    if c.get("rs_1h", 0) > 0.5:         pos.append(f"חזק מ-BTC {c['rs_1h']:+.1f}%")
    if c.get("whale_detected"):           pos.append("פעילות לווייתנים")

    ready = _ready_pct(c)
    lines = [
        f"🚨 עסקת BUY — {c['symbol'].replace('USDT','')}",
        f"מוכן: {ready}%",
        "",
        f"כניסה:   {_fmt_price(ep)}",
        f"סטופ:    {_fmt_price(sl)}",
        f"יעד 1:   {_fmt_price(tp1)}",
        f"יעד 2:   {_fmt_price(tp2)}",
        f"R:R:     {rr:.1f}x",
    ]
    lines += ["", f"💰 גודל פוזיציה: {pos_pct}%  (${pos_usd})"]
    if pos:
        lines += ["", "למה עכשיו?"]
        for p in pos: lines.append(f"  ✅ {p}")
    return "\n".join(lines)


# ─── Watchlist Candidate ──────────────────────────────────────────────────────

def _format_candidate(i: int, c: dict) -> str:
    sym     = c["symbol"].replace("USDT","")
    ready   = _ready_pct(c)
    emoji   = _ready_emoji(ready)
    missing = _what_missing(c)
    price   = c.get("price", 0)
    entry   = c.get("entry_price", 0) or price
    sl      = c.get("entry_sl", 0)
    tp1     = c.get("entry_tp1", 0)

    lines = [f"{_medal(i)} {sym}"]
    lines.append(f"{emoji} מוכן: {ready}%")
    if entry > 0:
        lines.append(f"כניסה: {_fmt_price(entry)}")
    if sl > 0:
        lines.append(f"סטופ:  {_fmt_price(sl)}")
    if tp1 > 0:
        lines.append(f"יעד:   {_fmt_price(tp1)}")
    if missing:
        lines.append("חסר:")
        for m in missing:
            lines.append(f"  • {m}")
    return "\n".join(lines)


# ─── Main Format ──────────────────────────────────────────────────────────────

def format_message(coins: list[dict], stats=None, all_coins=None, **kwargs) -> str:
    source = all_coins or coins
    regime = source[0].get("regime","") if source else ""

    buy_coins  = [c for c in source if c.get("decision") in ("ELITE_BUY","BUY")]
    spec_coins = [c for c in source if c.get("decision") == "SPECULATIVE"]

    # Soft candidates: מתקרבים ל-BUY
    candidates = sorted(
        [c for c in source
         if c.get("decision") != "BUY" and c.get("signal") != "BUY"
         and _is_soft(c)],
        key=lambda x: x.get("confidence", x.get("flow_score", 0)), reverse=True
    )[:5]

    try:
        import os
        mode = os.getenv("TRADE_MODE","BALANCED")
        mode_icon = {"ELITE":"🛡️","BALANCED":"⚖️","AGGRESSIVE":"⚡"}.get(mode,"⚖️")
    except Exception:
        mode_icon, mode = "⚖️", "BALANCED"

    lines = [
        "🔥 CRYPTO-BOT ELITE",
        f"📊 {_regime_line(regime)}  {mode_icon} {mode}",
    ]

    # ── יש BUY ──────────────────────────────────────────────────────────────
    if buy_coins:
        lines += ["", "━━━━━━━━━━━━━━━━━━"]
        for c in buy_coins:
            lines.append(_format_buy(c))
        return "\n".join(lines)

    # ── יש SPECULATIVE אבל לא BUY ──────────────────────────────────────────
    if not buy_coins and spec_coins:
        lines += ["", "━━━━━━━━━━━━━━━━━━", "🔵 SPECULATIVE (רבע פוזיציה):", ""]
        for i, co in enumerate(spec_coins[:3]):
            sym  = co["symbol"].replace("USDT","")
            conf = co.get("confidence", 0)
            ep   = co.get("entry_price", 0)
            sl   = co.get("entry_sl", 0)
            tp1  = co.get("entry_tp1", 0)
            pos  = _positives(co)
            miss = _what_missing(co)
            lines += [f"🔵 {sym}  ציון: {conf}/100  ({co.get('pos_size','1%')})"]
            if ep: lines.append(f"   כניסה: {_fmt_price(ep)}  סטופ: {_fmt_price(sl)}  יעד: {_fmt_price(tp1)}")
            if pos: lines.append(f"   ✅ {' | '.join(pos[:3])}")
            if miss: lines.append(f"   ❌ {' | '.join(miss[:2])}")
            lines.append("")

    # ── אין BUY ──────────────────────────────────────────────────────────────
    if not buy_coins:
        lines += ["", "❌ אין עסקת BUY כרגע."]

    # Watchlist
    if candidates:
        lines += ["", "━━━━━━━━━━━━━━━━━━", "👀 מתקרבים ל-BUY:",""]
        for i, c in enumerate(candidates):
            lines.append(_format_candidate(i, c))
            lines.append("")

    lines += ["━━━━━━━━━━━━━━━━━━", "📈 תמונת השוק", ""]

    # distribution ציונים
    if source:
        above80  = sum(1 for co in source if co.get("confidence",0) >= 80)
        bet6080  = sum(1 for co in source if 60 <= co.get("confidence",0) < 80)
        below60  = sum(1 for co in source if co.get("confidence",0) < 60)
        lines += [
            "", "━━━━━━━━━━━━━━━━━━",
            "📊 איכות המועמדים:",
            f"  🟢 מעל 80%: {above80}",
            f"  🟡 60–80%:  {bet6080}",
            f"  🔴 מתחת 60%: {below60}",
        ]

    # תמונת שוק + breakdown
    if stats:
        n       = getattr(stats, "scanned", len(source))
        rv_fail = getattr(stats, "rvol_fail", 0)
        fl_fail = getattr(stats, "flow_fail", 0)
        hd_fail = getattr(stats, "hard_fail", 0)
        sc_fail = getattr(stats, "score_fail", 0)
        near    = len(candidates)
        lines += [
            "", f"נסרקו: {n}  קרובים: {near}  BUY: 0",
            "", "למה אין BUY?",
        ]
        if rv_fail > 0: lines.append(f"  ❌ {rv_fail} נפסלו — RVOL נמוך")
        if fl_fail > 0: lines.append(f"  ❌ {fl_fail} נפסלו — Flow/OI חלש")
        if hd_fail > 0: lines.append(f"  ❌ {hd_fail} נפסלו — RSI/VWAP חריג")
        if sc_fail > 0: lines.append(f"  ❌ {sc_fail} נפסלו — Score נמוך")
        if near == 0:   lines.append("  ❌ אין פריצות כרגע")

        # המועמד הקרוב ביותר
        if candidates:
            best = candidates[0]
            bsym = best["symbol"].replace("USDT","")
            bpct = best.get("confidence", 0)
            bmiss = _what_missing(best)
            lines += ["", f"המועמד הקרוב: {bsym} ({bpct}%)"]
            if bmiss:
                lines.append("חסר:")
                for m in bmiss[:2]: lines.append(f"  • {m}")
    else:
        lines += [f"נסרקו: {len(source)}", "BUY: 0"]

    if candidates:
        lines += ["", "⏳ הבא בתור: " + candidates[0]["symbol"].replace("USDT","")]

    # Top 10 watchlist table
    top10 = sorted(source, key=lambda x: x.get("confidence",0), reverse=True)[:10]
    if top10:
        lines += ["", "━━━━━━━━━━━━━━━━━━",
                  "📋 Top 10 עכשיו:", ""]
        lines.append(f"{'מטבע':<10} {'ציון':>5}  למה לא BUY")
        lines.append("─" * 40)
        for co in top10:
            sym  = co["symbol"].replace("USDT","")
            conf = co.get("confidence", 0)
            miss = _what_missing(co)
            reason = miss[0] if miss else "✅ מוכן"
            lines.append(f"{sym:<10} {conf:>5.0f}%  {reason}")

    if candidates:
        lines += [
            "",
            "ברגע שאחד מהם ישלים את התנאי החסר —",
            "תישלח התראת BUY.",
        ]

    lines.append("\n⏳ ממשיכים לסרוק...")
    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────

def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None, stats=None, all_coins=None) -> bool:

    source = all_coins or coins
    if filtered:
        display = filtered.get("buy",[]) + filtered.get("prepare",[]) + filtered.get("watch",[])
    else:
        display = coins

    text = format_message(display, stats=stats, all_coins=source)

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
