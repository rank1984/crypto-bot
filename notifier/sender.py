"""
### CRYPTO-BOT Elite — Telegram Renderer V3 ###
פילוסופיה: איתור עסקאות בעלות הסתברות גבוהה לרווח של 10%-25%,
תוך שמירה על יחס סיכון/סיכוי קשוח (R:R >= 3:1) המשתלם גם לאחר עמלות ומיסוי בישראל.
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
    return ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i] if i < 5 else f"{i+1}."


def _regime_line(r: str) -> tuple[str, str]:
    """שלב 2 — התאמת פילטרים ומסרים לפי מצב השוק הנוכחי"""
    m = {
        "BULL": ("Bull (שוק עולה) 🟢", "תנאי סף מרוככים, מחפשים עסקאות מומנטום חזקות"),
        "TRENDING_BULL": ("Bull (שוק עולה) 🟢", "תנאי סף מרוככים, מחפשים עסקאות מומנטום חזקות"),
        "ALTSEASON": ("Altseason (עונת אלטים) 🚀", "שוק אגרסיבי — סורקים הזדמנויות בנזילות גבוהה"),
        "RANGE": ("Range (שוק מדשדש) 🟡", "תנאי סף קשוחים, עסקאות איכותיות ומבוססות קומפרשן בלבד"),
        "BEAR": ("Bear (שוק יורד) 🔴", "מצב הגנה — המערכת מסננת באגרסיביות / מחוץ לשוק"),
        "TRENDING_BEAR": ("Bear (שוק יורד) 🔴", "מצב הגנה — המערכת מסננת באגרסיביות / מחוץ לשוק"),
        "RISK_OFF": ("Risk-Off (שוק בפחד) ⛔", "סיכון גבוה — ממתינים לאישור או כניסת כסף חכם אמיתי"),
    }
    return m.get(r.upper(), ("📊 שוק משתנה", "ממתינים לכיוון ברור"))


def _probability_engine(flow: float, pre: float, oi: float,
                        compressed: bool, whale: bool, rs: float) -> tuple[str, int]:
    """
    שלב 10 — Probability Engine
    מחשב ציון מורכב ומחזיר דירוג אותיות (A+, A, B, C) יחד עם אחוז הסתברות מוערך.
    """
    score = (
        flow * 0.35 +
        pre * 0.25 +
        min(oi * 5, 15) +
        (15 if compressed else 0) +
        (5 if whale else 0) +
        (5 if rs > 0 else 0)
    )
    final_score = min(99, max(1, round(score)))

    if final_score >= 90:
        return "A+ (90%) — העסקאות הטובות ביותר", final_score
    elif final_score >= 80:
        return "A (80%) — טובות מאוד", final_score
    elif final_score >= 70:
        return "B (70%) — שווה מעקב", final_score
    else:
        return "C (<70%) — להתעלם", final_score


def _positives(c: dict) -> list[str]:
    """שלב 3, 4, 5, 6 — זיהוי היתרונות הטכנולוגיים שנשברו למעלה"""
    pos = []
    if c.get("vol_explosion") or c.get("vol_acceleration"):
        pos.append("Flow & Volume חזק (פיצוץ נפח)")
    elif c.get("flow_score", 0) >= 60:
        pos.append("Flow מתחזק (כניסת כסף חכם)")
        
    if c.get("oi_change", 0) > 2:
        pos.append("OI עולה (פוזיציות חדשות נפתחות)")
    if c.get("is_compressed") or c.get("squeeze_detected"):
        pos.append("Compression (פריצת קומפרשן/Squeeze)")
    if c.get("rs_1h", 0) > 0:
        pos.append("RS חיובי מול BTC")
    if c.get("whale_detected") or c.get("whale_activity"):
        pos.append("Whale Activity (פעילות לווייתנים)")
    if c.get("sector_bonus"):
        pos.append(f"Sector Rotation (בונוס סקטור: {c.get('sector','')})")
    if c.get("has_catalyst"):
        pos.append("Catalyst Engine (קיים אירוע פונדמנטלי קרוב)")
    return pos


def _negatives(c: dict) -> list[str]:
    """מזהה מה חסר לעסקה מושלמת כדי להציג בסטטוס WATCH / WAIT"""
    neg = []
    if c.get("oi_change", 0) <= 0:
        neg.append("OI")
    if not c.get("is_compressed") and not c.get("squeeze_detected"):
        neg.append("Compression")
    if c.get("rs_1h", 0) <= 0:
        neg.append("RS מול BTC")
    if c.get("flow_score", 0) < 60:
        neg.append("Flow חזק")
    return neg


def _format_buy(medal_str: str, c: dict, grade_str: str) -> str:
    """שלב 14 — פורמט הודעת קנייה ממוקדת ומקצועית"""
    pos = _positives(c)
    ep = c.get("entry_price", 0)
    sl = c.get("entry_sl", 0)
    tp1 = c.get("entry_tp1", 0)
    
    # חישוב רווח צפוי ריאלי באחוזים לפי יעד ראשון
    expected_gain = c.get("expected_gain", 0)
    if expected_gain == 0 and ep > 0 and tp1 > 0:
        expected_gain = ((tp1 - ep) / ep) * 100

    lines = [
        "🟢 BUY",
        f"מטבע: {medal_str} {c['symbol'].replace('USDT','')}",
        f"דירוג: {grade_str}",
        "",
        "למה?"
    ]
    
    if pos:
        for p in pos:
            lines.append(f"  ✅ {p}")
    else:
        lines.append("  ✅ עומד בתנאי ה-Quality Gate של האסטרטגיה")

    lines += [
        "",
        f"כניסה: {_fmt_price(ep)}",
        f"סטופ:  {_fmt_price(sl)}",
        f"יעד:   {_fmt_price(tp1)}",
        f"R:R:   {c.get('entry_rr', 3.0):.1f}x",
        "",
        f"🎯 רווח צפוי: +{expected_gain:.1f}%",
        f"⏱ זמן משוער: {c.get('estimated_time', '12-48 שעות')}",
    ]
    return "\n".join(lines)


def _format_wait(medal_str: str, c: dict, grade_str: str) -> str:
    """שלב 14 — פורמט הודעת המתנה ברורה ללא עומס קוגניטיבי"""
    neg = _negatives(c)
    sym = c['symbol'].replace('USDT','')
    
    lines = [
        "🟡 WATCH / WAIT",
        f"מטבע: {medal_str} {sym}",
        f"דירוג פוטנציאלי: {grade_str.split('—')[0].strip()}",
        "",
        "מה עדיין חסר?"
    ]
    
    if neg:
        missing_triggers = " + ".join(neg)
        lines.append(f"  ❌ {missing_triggers}")
    else:
        lines.append("  ❌ אישור נפח סופי / כניסת כסף חכם")
        
    lines.append("\nאל תקנה עדיין. המתזר לאישור פריצה.")
    return "\n".join(lines)


def format_message(coins: list[dict], **kwargs) -> str:
    if not coins:
        return (
            "🔥 CRYPTO-BOT Elite\n\n"
            "❌ אין כרגע עסקאות איכותיות העומדות בתנאי ה-Quality Gate.\n\n"
            "⏳ המערכת ממשיכה לסרוק 400+ מטבעות ב-Dynamic Universe..."
        )

    # חילוץ וקביעת מצב שוק
    regime = coins[0].get("regime", "RANGE")
    r_title, r_tip = _regime_line(regime)

    lines = [
        "🔥 CRYPTO-BOT Elite",
        f"מצב שוק: {r_title}",
        f"💡 {r_tip}",
        "━━━━━━━━━━━━━━"
    ]

    buy_coins = [c for c in coins if c.get("signal") == "BUY"]
    # פריטים במצב PREPARE או WATCH יאוחדו למנגנון ה-WATCH / WAIT החדש
    wait_coins = [c for c in coins if c.get("signal") in ["PREPARE", "WATCH"]]

    # רינדור אותות קנייה קשיחים (BUY)
    for i, c in enumerate(buy_coins):
        grade_str, _ = _probability_engine(
            c.get("flow_score", 0), c.get("pre_score", 0), c.get("oi_change", 0),
            c.get("is_compressed", False) or c.get("squeeze_detected", False),
            c.get("whale_detected", False) or c.get("whale_activity", False),
            c.get("rs_1h", 0)
        )
        lines.append(_format_buy(_medal(i), c, grade_str))
        lines.append("━━━━━━━━━━━━━━")

    # רינדור אותות המתנה (WATCH / WAIT)
    idx = len(buy_coins)
    for c in wait_coins:
        grade_str, score = _probability_engine(
            c.get("flow_score", 0), c.get("pre_score", 0), c.get("oi_change", 0),
            c.get("is_compressed", False) or c.get("squeeze_detected", False),
            c.get("whale_detected", False) or c.get("whale_activity", False),
            c.get("rs_1h", 0)
        )
        # מסננים עסקאות חלשות לחלוטין (דירוג C) כדי לא להעמיס על העיניים בטלגרם
        if score >= 70:
            lines.append(_format_wait(_medal(idx), c, grade_str))
            lines.append("━━━━━━━━━━━━━━")
            idx += 1

    return "\n".join(lines).strip("━━━━━━━━━━━━━━\n ")


def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None) -> bool:
    if filtered:
        display = filtered.get("buy", []) + filtered.get("prepare", []) + filtered.get("watch", [])
    else:
        display = coins

    text = format_message(display)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n--- TELEGRAM SIMULATION OUTPUT ---")
        print(text)
        print("---------------------------------\n")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096],
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram notification delivered successfully.")
        return True
    except Exception as e:
        log.error(f"Telegram communication failed: {e}")
        return False
