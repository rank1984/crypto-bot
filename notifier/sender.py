"""
CRYPTO-BOT Elite — Telegram Pro (עברית מלאה)
עונה על: למה, מה חסר, האם כדאי, כמה לקנות, מתי למכור.
"""
import requests
from scanner.position_engine import calc_position, calc_runner_exits, assess_fakeout_risk
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _e(s: str) -> str:
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

def _rare_setup(pre: float, flow: float, score: float, fakeout: str, event_score: float) -> str:
    """מחזיר תגית נדירות."""
    if pre >= 85 and flow >= 80 and score >= 88 and fakeout == "נמוך":
        return "💎 TOP 1% SETUP"
    if pre >= 75 and flow >= 65 and score >= 82 and event_score >= 30:
        return "⭐ Rare Setup"
    if pre >= 65 and flow >= 55:
        return "🔥 High Potential"
    return ""

def _big_move_score(pre: float, flow: float, event: float) -> float:
    """BIG MOVE SCORE = ממוצע משוקלל של pre + flow + event."""
    return round(pre * 0.50 + flow * 0.35 + event * 0.15, 1)

def _runner_exits(entry: float, sl: float, pre: float) -> dict:
    """Runner 60% philosophy."""
    if entry <= 0 or sl >= entry:
        return {}
    risk = (entry - sl) / entry
    tp1  = round(entry * (1 + risk * 1.5), 8)   # 20% — להחזיר סיכון
    if pre >= 80:
        tp2 = round(entry * (1 + risk * 6), 8)   # 20% — +15% בממוצע
        tp3 = round(entry * 1.50, 8)              # 60% runner target
        trail = round(risk * 5 * 100, 1)
    elif pre >= 60:
        tp2 = round(entry * (1 + risk * 4), 8)
        tp3 = round(entry * 1.30, 8)
        trail = round(risk * 4 * 100, 1)
    else:
        tp2 = round(entry * (1 + risk * 3), 8)
        tp3 = round(entry * 1.20, 8)
        trail = round(risk * 3 * 100, 1)

    return {
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "tp1_pct": round((tp1-entry)/entry*100,1),
        "tp2_pct": round((tp2-entry)/entry*100,1),
        "tp3_pct": round((tp3-entry)/entry*100,1),
        "trail":   trail,
        "risk_pct": round(risk*100,2),
        "rr": round((tp1-entry)/(entry-sl),2) if entry>sl else 0,
    }

def _grade(s: float) -> str:
    for t, l in [(90,"A+"),(80,"A"),(70,"A-"),(60,"B+"),(50,"B"),(0,"B-")]:
        if s >= t: return l
    return "C"

def _flow_emoji(f: float) -> str:
    if f >= 80: return "🔥 חזקה מאוד"
    if f >= 60: return "🟢 חזקה"
    if f >= 40: return "🟡 בינונית"
    if f >= 20: return "🟠 חלשה"
    return "🔴 חלשה מאוד"

def _time_window(pre: float, flow: float, setup: str) -> str:
    if pre >= 80 and flow >= 60: return "15–45 דקות"
    if pre >= 60 or flow >= 60:  return "30 דקות – 2 שעות"
    if setup == "BREAKOUT":      return "1–4 שעות"
    return "2–8 שעות"

def _regime_label(r: str) -> str:
    return {"TRENDING_BULL":"🟢 טרנד עולה","ALTSEASON":"🚀 עונת אלטים",
            "RANGE":"🟡 שוק ללא כיוון","RISK_OFF":"🔴 שוק בפחד",
            "TRENDING_BEAR":"⛔ טרנד יורד"}.get(r, "⚪ לא ידוע")

def _medal(i: int) -> str:
    return ["🥇","🥈","🥉","4️⃣","5️⃣"][i] if i < 5 else f"{i+1}\\."

def _pos_neg(c: dict) -> tuple[list, list]:
    pos, neg = [], []
    comp = c.get("flow_components", {})
    pre  = c.get("pre_components",  {})

    if comp.get("oi", 0) >= 12:          pos.append("OI Expansion — כסף חדש נכנס")
    else:                                 neg.append("OI חלש — אין כסף חדש")
    if comp.get("cvd", 0) >= 10:         pos.append("CVD חיובי — קונים תוקפים")
    if pre.get("compression", 0) >= 7:   pos.append("Compression — שקט לפני סערה")
    else:                                 neg.append("אין Compression")
    if comp.get("rs", 0) >= 15:          pos.append("חוזק מול BTC ו־ETH")
    elif comp.get("rs", 0) >= 7:         pos.append("חוזק מול BTC")
    else:                                 neg.append("חולשה מול BTC")
    if comp.get("whale", 0) >= 7:        pos.append("פעילות לווייתנים")
    else:                                 neg.append("אין פעילות לווייתנים")
    if pre.get("mtf_alignment", 0) >= 10: pos.append("יישור רב־טיימפריים")
    if c.get("entry_decision") == "BUY": pos.append("טריגר כניסה הופעל")
    elif c.get("entry_decision") == "WAIT": neg.append("אין אישור פריצה עדיין")
    else:                                 neg.append("אין טריגר כניסה")
    if c.get("is_sympathy"):             pos.append(f"Sympathy אחרי {c.get('leader','').replace('USDT','')}")
    return pos[:5], neg[:3]


# ─── Main Formatter ───────────────────────────────────────────────────────────

def format_message(top_coins: list[dict], portfolio_usd: float = 1000.0,
                   filtered: dict = None) -> str:
    lines = ["🔥 *CRYPTO\\-BOT Elite*"]

    if top_coins:
        regime = top_coins[0].get("regime","")
        lines.append(f"📊 מצב שוק: {_e(_regime_label(regime))}")
    lines.append("━━━━━━━━━━━━")

    for i, c in enumerate(top_coins):
        sym        = c["symbol"]
        score      = c.get("final_score", 0)
        flow       = c.get("flow_score", 0)
        pre        = c.get("pre_score", 0)
        dec        = c.get("entry_decision","NO")
        setup      = c.get("entry_setup","")
        regime     = c.get("regime","RANGE")
        entry_p    = c.get("entry_price", 0)
        entry_sl   = c.get("entry_sl", 0)
        price      = c.get("price", 0)
        atr        = c.get("atr_14", price * 0.01)
        phase_lbl  = c.get("phase_label", "")
        is_comp    = c.get("is_compressed", False)
        whale      = c.get("whale_detected", False)
        pos_r, neg_r = _pos_neg(c)

        event_score = c.get("event_score", 0)
        catalysts   = c.get("catalysts", [])
        big_move    = _big_move_score(pre, flow, event_score)
        rare        = _rare_setup(pre, flow, score, fakeout_risk, event_score)

        fakeout_risk, fakeout_emoji = assess_fakeout_risk(
            c.get("rvol",1), c.get("vwap_dist",0),
            c.get("rsi_14",50), flow, is_comp,
        )

        # ── כותרת ────────────────────────────────────────────────────────────
        lines.append(f"{_medal(i)} *{_e(sym)}* \\[{_grade(score)}\\]")
        if rare:
            lines.append(f"{_e(rare)}")
        lines.append(f"💣 *BIG MOVE SCORE: `{big_move:.0f}/100`*")
        lines.append(f"🌊 Flow: `{flow:.0f}/100` {_e(_flow_emoji(flow))}")
        lines.append(f"⚡ Pre\\-Breakout: `{pre:.0f}/100`")

        lines.append(f"💰 מחיר: `{_fmt_price(price)}` \\| RVOL: `{c.get('rvol',0):.1f}x` \\| RSI: `{c.get('rsi_14',0):.0f}`")
        lines.append(f"⏱ Mom: 5m `{_fmt_pct(c.get('momentum_5m',0))}` 15m `{_fmt_pct(c.get('momentum_15m',0))}` 1h `{_fmt_pct(c.get('momentum_1h',0))}` \\| BTC RS: `{_fmt_pct(c.get('rs_1h',0))}`")

        # ── החלטה ────────────────────────────────────────────────────────────
        if dec == "BUY" and entry_p > 0:
            pos_info = calc_position(score, pre, flow, regime, portfolio_usd)
            runner   = _runner_exits(entry_p, entry_sl, pre)

            lines.append(f"\n🟢 *פעולה: קנייה*")
            lines.append(f"📌 מחיר כניסה: `{_fmt_price(entry_p)}`")
            lines.append(f"🛑 עצירת הפסד: `{_fmt_price(entry_sl)}` \\(סיכון: `{runner.get('risk_pct','?')}%`\\)")
            lines.append("")
            lines.append(f"🎯 *יעד ראשון \\(20%\\)* — `{_fmt_price(runner.get('tp1',0))}` \\({_e(_fmt_pct(runner.get('tp1_pct',0)))}\\)")
            lines.append("   להחזיר סיכון — הישאר חינם בשוק")
            lines.append(f"🎯 *יעד שני \\(20%\\)* — `{_fmt_price(runner.get('tp2',0))}` \\({_e(_fmt_pct(runner.get('tp2_pct',0)))}\\)")
            lines.append(f"🚀 *Runner \\(60%\\)* — מטרה: `{_fmt_price(runner.get('tp3',0))}` \\({_e(_fmt_pct(runner.get('tp3_pct',0)))}\\)")
            lines.append(f"   Trailing Stop: `{runner.get('trail','?')}%` \\| יעד פתוח: 50%\\-200%\\+")
            lines.append("")
            lines.append(f"💰 גודל: `{pos_info['pct_of_portfolio']*100:.1f}%` מהתיק \\(`${pos_info['usd_amount']:.0f}`\\)")
            lines.append(f"⚖️ R:R: `{runner.get('rr','?')}x` \\| Confidence: `{pos_info['confidence']:.0f}` \\({_e(pos_info['confidence_label'])}\\)")

        elif dec == "WAIT":
            lines.append(f"\n🟡 *מה לעשות עכשיו?*")
            lines.append(f"🟡 להמתין — עדיין אין אישור לפריצה")
            lines.append(f"📈 Setup: {_e(setup)}")
            lines.append(f"⏳ חלון זמן צפוי: {_e(_time_window(pre, flow, setup))}")

        else:
            lines.append(f"\n⚪ *מה לעשות עכשיו?*")
            lines.append("🔴 לא להיכנס כרגע")
            if pre >= 40:
                lines.append("👁 שווה מעקב — בנייה בתהליך")

        # ── סיבות ────────────────────────────────────────────────────────────
        if pos_r:
            lines.append("\n✅ *מה חיובי?*")
            for r in pos_r: lines.append(f"  ✓ {_e(r)}")
        if neg_r:
            lines.append("❌ *מה חסר?*")
            for r in neg_r: lines.append(f"  ✗ {_e(r)}")

        # ── מטא ──────────────────────────────────────────────────────────────
        lines.append(f"\n🐋 פעילות לווייתנים: {'כן ✓' if whale else 'לא'}")
        lines.append(f"⚠️ סיכון לפייקאאוט: {fakeout_emoji} {_e(fakeout_risk)}")

        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────

def send_telegram(top_coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing to stdout")
        print(format_message(top_coins, portfolio_usd, filtered))
        return False

    # אם אין מטבעות — שלח הודעת "אין סיגנל"
    if not top_coins:
        text = "🔥 *CRYPTO\\-BOT Elite*\n\n❌ אין כרגע Setup איכותי\\.\n\n⏳ סבלנות\\."
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":  None,
            }, timeout=10)
            log.info("Telegram: no signal message sent")
        except Exception as e:
            log.error(f"Telegram failed: {e}")
        return False

    text = format_message(top_coins, portfolio_usd, filtered)
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":  None,
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        try:
            plain = "CRYPTO-BOT Elite\n\n"
            for i, c in enumerate(top_coins):
                dec = c.get("entry_decision","NO")
                icon = {"BUY":"🟢","WAIT":"🟡","NO":"🔴"}.get(dec,"⚪")
                plain += f"{i+1}. {c['symbol']} | ציון:{c.get('final_score',0):.0f} | Pre:{c.get('pre_score',0):.0f} | Flow:{c.get('flow_score',0):.0f}\n{icon} {dec}"
                if dec == "BUY":
                    plain += f" | כניסה: {_fmt_price(c.get('entry_price',0))}"
                plain += "\n\n"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
        except Exception:
            pass
        return False
