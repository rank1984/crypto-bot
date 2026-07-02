"""
CRYPTO-BOT Elite — Telegram Renderer v4

פילוסופיה: תשובה לשלוש שאלות בלבד.
    1. יש עסקה?
    2. למה אין?
    3. מה לחכות שיקרה?

אין "הסתברות". יש "דירוג איכות" (A+/A/B+/B).
אין WATCH חלש. יש "מועמד קרוב" עם מה חסר לו.
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
    return ["🥇","🥈","🥉","4.","5."][i] if i < 5 else f"{i+1}."

def _regime_line(r: str) -> str:
    return {
        "TRENDING_BULL": "🟢 שוק עולה",
        "ALTSEASON":     "🚀 עונת אלטים",
        "RANGE":         "🟡 שוק מדשדש",
        "RISK_OFF":      "🔴 שוק בפחד",
        "TRENDING_BEAR": "⛔ שוק יורד",
    }.get(r, "📊 שוק")

def _what_is_missing(c: dict) -> list[str]:
    """מה בדיוק חסר למטבע כדי לקבל BUY."""
    missing = []
    if c.get("oi_change", 0) <= 1:
        missing.append("OI חיובי — כניסת כסף")
    if c.get("rvol", 0) < 1.5:
        missing.append(f"RVOL מעל 1.5 (יש {c.get('rvol',0):.1f}x)")
    if not c.get("is_compressed"):
        missing.append("Compression — צבירה שקטה")
    if c.get("rs_1h", 0) <= 0:
        missing.append("חוזק מול BTC")
    if c.get("flow_score", 0) < 60:
        missing.append(f"Flow מעל 60 (יש {c.get('flow_score',0):.0f})")
    return missing[:3]

def _why_blocked(c: dict) -> list[str]:
    """למה נחסם — סיבות קצרות."""
    reasons = []
    if c.get("oi_change", 0) <= 0:
        reasons.append("אין כניסת כסף חדשה (OI)")
    if c.get("rvol", 0) < 1.0:
        reasons.append("נפח מסחר חלש")
    if c.get("flow_score", 0) < 45:
        reasons.append("Flow חלש מדי")
    if c.get("rs_1h", 0) < -0.5:
        reasons.append("חולשה מול BTC")
    if not c.get("is_compressed"):
        reasons.append("אין צבירה (Compression)")
    return reasons[:3]

def _positives(c: dict) -> list[str]:
    pos = []
    if c.get("vol_explosion"):            pos.append("💥 פיצוץ נפח")
    if c.get("flow_score", 0) >= 60:     pos.append("Flow חזק")
    if c.get("oi_change", 0) > 2:        pos.append(f"OI עולה {c['oi_change']:+.1f}%")
    if c.get("is_compressed"):            pos.append("Compression — שקט לפני סערה")
    if c.get("rs_1h", 0) > 0.5:         pos.append(f"חזק מ-BTC {c['rs_1h']:+.1f}%")
    if c.get("whale_detected"):           pos.append("פעילות לווייתנים")
    if c.get("momentum_1h", 0) > 1.5:   pos.append(f"מומנטום {c['momentum_1h']:+.1f}%")
    return pos


# ─── Sections ─────────────────────────────────────────────────────────────────

def _format_buy(i: int, c: dict) -> str:
    rating = c.get("rating", "")
    conf   = c.get("confidence", 0)
    pos    = _positives(c)
    ep, sl = c.get("entry_price", 0), c.get("entry_sl", 0)
    tp1, tp2 = c.get("entry_tp1", 0), c.get("entry_tp2", 0)

    lines = [
        f"🚨 עסקת {rating} — {c['symbol'].replace('USDT','')}",
        f"איכות: {conf:.0f}/100",
        "",
        f"כניסה:     {_fmt_price(ep)}",
        f"סטופ:      {_fmt_price(sl)}",
        f"יעד 1:     {_fmt_price(tp1)}",
        f"יעד 2:     {_fmt_price(tp2)}",
        f"R:R:       {c.get('entry_rr',0):.1f}x",
    ]
    if pos:
        lines += ["", "למה עכשיו?"]
        for p in pos: lines.append(f"  ✅ {p}")
    return "\n".join(lines)


def _format_near_buy(i: int, c: dict) -> str:
    """מועמד קרוב ל-BUY — מה בדיוק חסר."""
    rating  = c.get("rating", "B+")
    missing = _what_is_missing(c)
    blocked = _why_blocked(c)

    lines = [
        f"{_medal(i)} {c['symbol'].replace('USDT','')}   דירוג: {rating}",
        "",
    ]
    if blocked:
        lines.append("לא נשלח BUY בגלל:")
        for b in blocked: lines.append(f"  ❌ {b}")
        lines.append("")
    if missing:
        lines.append("כדי לעבור ל-BUY:")
        for m in missing: lines.append(f"  • {m}")
        lines.append("")
    lines.append("אם התנאים יתקיימו — תקבל התראה.")
    return "\n".join(lines)


def _format_no_signal_with_funnel(stats) -> str:
    """הודעת 'אין עסקה' עם funnel מלא."""
    from tools.scan_diagnostics import format_no_signal_message
    return format_no_signal_message(stats)


# ─── Main Format ──────────────────────────────────────────────────────────────

def _opportunity_index(coins: list[dict]) -> str:
    """מדד הזדמנויות — כמה כוכבים."""
    if not coins:
        return "★☆☆☆☆  אין מה לחפש כרגע"
    near = [c for c in coins if c.get("rating") in ("A+","A","B+")]
    n = len(near)
    if n >= 3: return "★★★★★  הרבה מועמדים קרובים"
    if n == 2: return "★★★★☆  כמה מועמדים מעניינים"
    if n == 1: return "★★★☆☆  מועמד אחד קרוב"
    return "★★☆☆☆  השוק חלש כרגע"


def format_message(coins: list[dict], stats=None, all_coins=None, **kwargs) -> str:
    regime = coins[0].get("regime", "") if coins else ""

    buy_coins  = [c for c in coins if c.get("signal") == "BUY" or c.get("decision") == "BUY"]
    wait_coins = [c for c in coins if c.get("decision") == "WAIT" or c.get("signal") == "PREPARE"]

    # ── יש BUY ──────────────────────────────────────────────────────────────
    if buy_coins:
        lines = [
            "🔥 CRYPTO-BOT ELITE",
            f"📊 מצב שוק: {_regime_line(regime)}",
            "",
        ]
        for i, c in enumerate(buy_coins):
            lines += ["━━━━━━━━━━━━━━━━━━", _format_buy(i, c), ""]
        return "\n".join(lines)

    # ── אין עסקה — diagnostic מלא ────────────────────────────────────────────
    # פונל
    funnel_lines = []
    if stats:
        try:
            from tools.scan_diagnostics import format_full_diagnostic
            all_c = all_coins or coins
            funnel_lines = format_full_diagnostic(stats, all_c).split("\n")
        except Exception as e:
            funnel_lines = [f"נסרקו: {getattr(stats,'scanned',0)}"]

    # מועמד קרוב ביותר
    source = all_coins or coins
    wait_all = [c for c in source if c.get("decision") in ("WAIT",) or c.get("signal") in ("PREPARE","WATCH")]
    near = sorted(
        [c for c in wait_all if c.get("rating") in ("A+","A","B+")],
        key=lambda x: x.get("confidence", x.get("flow_score",0)), reverse=True
    )[:1]

    lines = [
        "🔥 CRYPTO-BOT ELITE",
        f"📊 מצב שוק: {_regime_line(regime)}",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if funnel_lines:
        lines += funnel_lines
    else:
        lines.append(f"נסרקו: {len(coins)} מטבעות")

    lines += ["━━━━━━━━━━━━━━━━━━", "אין עסקה כרגע.", ""]

    if near:
        lines.append("המועמד הקרוב ביותר:")
        lines.append("")
        lines.append(_format_near_buy(0, near[0]))
    
    lines += ["", f"🔥 מדד הזדמנויות: {_opportunity_index(coins)}", "⏳ ממשיכים לסרוק..."]
    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────

def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None, stats=None, all_coins=None) -> bool:
    if filtered:
        display = filtered.get("buy",[]) + filtered.get("prepare",[]) + filtered.get("watch",[])
    else:
        display = coins

    # אם אין כלום — שלח diagnostic
    if not display and stats:
        try:
            from tools.scan_diagnostics import format_no_signal_message
            text = format_no_signal_message(stats)
        except Exception:
            text = format_message([], stats=stats)
    else:
        text = format_message(display, stats=stats, all_coins=coins)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]}, timeout=10)
        r.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False
