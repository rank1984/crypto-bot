בשמחה. הנה הקוד המלא והמעודכן עבור `/home/claude/crypto-bot/notifier/sender.py` בגרסה 5 הנקייה.

החלף את כל תוכן הקובץ בקוד הבא. הוא עונה בדיוק על 3 השאלות, מציג אחוזי מוכנות אינטואיטיביים, מבודד את הסיבה המרכזית ומשמיט את כל רעשי הדיבוג (Heatmap, Loss Rate, EV).

```python
"""
CRYPTO-BOT Elite — Telegram Renderer v5
עונה על 3 שאלות בלבד:
1. יש עסקה עכשיו?
2. אם אין — על מה לעקוב?
3. מה בדיוק חססר?

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
    return ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i] if i < 5 else f"{i+1}."

def _regime_line(r: str) -> str:
    return {
        "TRENDING_BULL": "🟢 שוק עולה — כניסות מותרות",
        "ALTSEASON":     "🚀 עונת אלטים — אגרסיביים",
        "RANGE":         "🟡 שוק מדשדש — רק עסקאות חזקות",
        "RISK_OFF":      "🔴 שוק בפחד — זהירות מירבית",
        "TRENDING_BEAR": "⛔ שוק יורד — לא קונים",
    }.get(r, "📊 מצב השוק")

def _ready_pct(c: dict) -> int:
    """אחוז מוכנות 0-99 לפי מה שיש ואין באסטרטגיה."""
    score = 0
    if c.get("flow_score", 0) >= 55:     score += 25
    elif c.get("flow_score", 0) >= 40:   score += 12
    
    if c.get("oi_change", 0) > 2:        score += 20
    elif c.get("oi_change", 0) > 0:      score += 8
    
    if c.get("is_compressed"):           score += 15
    if c.get("rs_1h", 0) > 0:            score += 15
    
    if c.get("rvol", 0) >= 1.5:          score += 15
    elif c.get("rvol", 0) >= 0.8:        score += 7
    
    if c.get("whale_detected"):          score += 5
    if c.get("vol_explosion"):           score += 5
    
    return min(99, score)

def _ready_emoji(pct: int) -> str:
    if pct >= 85: return "🟢"
    if pct >= 65: return "🟡"
    return "🔴"

def _what_missing(c: dict) -> list[str]:
    """מה בדיוק חסר — מקסימום 3 דברים עיקריים."""
    m = []
    if c.get("oi_change", 0) <= 0:
        m.append("OI עולה")
    if c.get("rvol", 0) < 1.5:
        m.append(f"RVOL מעל 1.5 (יש {c.get('rvol', 0):.1f}x)")
    if not c.get("is_compressed"):
        m.append("Compression (דחיסת מחיר)")
    if c.get("rs_1h", 0) <= 0:
        m.append("חוזק יחסי מול BTC")
    if c.get("flow_score", 0) < 55:
        m.append(f"Flow מעל 55 (יש {c.get('flow_score', 0):.0f})")
    if c.get("entry_decision", "NO") != "BUY" and c.get("decision", "NO") != "BUY":
        m.append("אישור פריצה / טריגר כניסה")
    return m[:3]

def _why_no_signal(stats) -> str:
    """סיבה אחת ברורה ותמציתית למה אין סיגנל מהדיאגנוסטיקה."""
    if stats is None:
        return "אין כרגע מטבע שעומד בכל תנאי הסף של האסטרטגיה."
    try:
        # בודק אם יש מתודה שמחלצת את צוואר הבקבוק הראשי
        if hasattr(stats, "main_bottleneck"):
            bn, _ = stats.main_bottleneck()
            return {
                "RVOL נמוך":    "אין מספיק נפח מסחר בשוק (RVOL נמוך).",
                "Flow חלש":     "אין כניסת כסף משמעותית (Flow שלילי/חלש).",
                "Hard Filters": "המטבעות שנבדקו חרגו מגבולות הקיצון (RSI/VWAP).",
                "Score נמוך":   "האיכות הכללית של המועמדים נמוכה מדי לסיכון כסף.",
            }.get(bn, "אין מטבע שעומד בכל התנאים.")
    except Exception:
        pass
    return "אין כרגע מטבע שעומד בכל התנאים בשוק."

# ─── Format Sub-Sections ──────────────────────────────────────────────────────

def _format_buy(c: dict) -> str:
    ep  = c.get("entry_price", 0)
    sl  = c.get("entry_sl", 0)
    tp1 = c.get("entry_tp1", 0)
    tp2 = c.get("entry_tp2", 0)
    rr  = c.get("entry_rr", 0)
    
    pos = []
    if c.get("vol_explosion"):     pos.append("💥 פיצוץ נפח")
    if c.get("flow_score", 0) >= 60: pos.append("Flow חזק מאוד")
    if c.get("oi_change", 0) > 2:  pos.append(f"OI בזינוק של {c['oi_change']:+.1f}%")
    if c.get("is_compressed"):     pos.append("Compression מושלם")
    if c.get("rs_1h", 0) > 0.5:    pos.append(f"חוזק מובהק מ-BTC ({c['rs_1h']:+.1f}%)")
    if c.get("whale_detected"):    pos.append("פעילות לווייתנים חריגה")
    
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
    if pos:
        lines += ["", "למה עכשיו?"]
        for p in pos:
            lines.append(f"  ✅ {p}")
    return "\n".join(lines)

def _format_candidate(i: int, c: dict) -> str:
    sym     = c["symbol"].replace("USDT","")
    ready   = _ready_pct(c)
    emoji   = _ready_emoji(ready)
    missing = _what_missing(c)
    
    lines = [
        f"{_medal(i)} {sym}",
        f"{emoji} מוכן: {ready}%"
    ]
    if missing:
        lines.append("חסר:")
        for m in missing:
            lines.append(f"  • {m}")
    return "\n".join(lines)

# ─── Main Format Message ──────────────────────────────────────────────────────

def format_message(coins: list[dict], stats=None, all_coins=None, **kwargs) -> str:
    source = all_coins or coins
    regime = source[0].get("regime", "") if source else ""
    
    # סינון עסקאות BUY אקטיביות
    buy_coins = [c for c in source if c.get("decision") == "BUY" or c.get("signal") == "BUY"]
    
    # סינון ומיון מועמדים ל-Watchlist (עד 5 מובילים שלא ב-BUY)
    candidates = sorted(
        [c for c in source if c.get("decision") != "BUY" and c.get("signal") != "BUY"],
        key=lambda x: _ready_pct(x), 
        reverse=True
    )[:5]
    
    lines = [
        "🔥 CRYPTO-BOT ELITE",
        f"{_regime_line(regime)}",
    ]
    
    # ── תרחיש א': יש עסקאות חמות בזמן אמת ──────────────────────────────────────
    if buy_coins:
        lines += ["", "━━━━━━━━━━━━━━━━━━"]
        for c in buy_coins:
            lines.append(_format_buy(c))
            lines.append("━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
        
    # ── תרחיש ב': אין עסקאות, מציגים את ה-Watchlist ודיאגנוסטיקה ───────────────
    lines += ["", "❌ אין עסקאת BUY כרגע."]
    
    # חלון מעקב ל-5 המובילים
    if candidates:
        lines += ["", "━━━━━━━━━━━━━━━━━━", "👀 תעקוב אחרי:", ""]
        for i, c in enumerate(candidates):
            lines.append(_format_candidate(i, c))
            lines.append("")
            
    lines += ["━━━━━━━━━━━━━━━━━━", "📈 תמונת השוק", ""]
    
    # סטטיסטיקת סריקה בסיסית ונקייה
    if stats:
        n = getattr(stats, "scanned", len(source))
        rv_ok = n - getattr(stats, "no_data", 0) - getattr(stats, "rvol_fail", 0)
        lines.append(f"נסרקו: {n} מטבעות")
        lines.append(f"עברו סינון נפח ראשוני: {max(0, rv_ok)}")
        lines.append("עסקאות BUY אקטיביות: 0")
    else:
        lines.append(f"נסרקו: {len(source)} מטבעות")
        lines.append("עסקאות BUY אקטיביות: 0")
        
    # תשובה ברורה לשאלה: למה אין עסקה?
    reason = _why_no_signal(stats)
    lines += ["", "למה אין עסקה?", f"➡️ {reason}"]
    
    if candidates:
        lines += [
            "",
            "ברגע שאחד מהם ישלים את התנאי החסר —",
            "תישלח התראת BUY מיידית.",
        ]
        
    lines.append("\n⏳ ממשיכים לסרוק...")
    return "\n".join(lines)

# ─── Send Telegram Message ────────────────────────────────────────────────────

def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0,
                  filtered: dict = None, stats=None, all_coins=None) -> bool:
    source = all_coins or coins
    
    if filtered:
        display = filtered.get("buy", []) + filtered.get("prepare", []) + filtered.get("watch", [])
    else:
        display = coins
        
    text = format_message(display, stats=stats, all_coins=source)
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        # פולבק לטרמינל לטובת בדיקות מקומיות
        print("\n--- [TELEGRAM DRY RUN] ---")
        print(text)
        print("--------------------------\n")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    text[:4096],
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram notification sent successfully.")
        return True
    except Exception as e:
        log.error(f"Telegram failed to send message: {e}")
        return False

```
