import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

# ייבוא המנועים החדשים
from engines.confidence import calc_confidence
from engines.position import calc_position_pct
from engines.signal_ai import get_signal_state
from engines.runner import check_runner_status, save_runner

log = get_logger(__name__)

def _e(s: str) -> str:
    """הגנה חזקה על תווים ב-MarkdownV2"""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = str(s).replace(c, f"\\{c}")
    return s

def _fmt_price(p: float) -> str:
    if p >= 1: return f"{p:.4f}"
    return f"{p:.6f}"

def format_message(coins_data: list[dict], regime: str = "RANGE") -> str:
    categorized = {"RUNNER": [], "CLOSED": [], "BUY": [], "PREPARE": [], "WATCH": []}
    
    # 1. עיבוד כל מטבע דרך ה-Engines
    for c in coins_data:
        sym = c["symbol"]
        price = c.get("price", 0)
        
        # בדיקה האם יש טרייד פתוח (Runner) או האם הוא בדיוק נסגר
        runner_data = check_runner_status(sym, price)
        
        # טיפול ביציאה מפוזיציה
        if runner_data and runner_data["status"] == "CLOSED":
            c["close_pnl_pct"] = runner_data["close_pnl_pct"]
            categorized["CLOSED"].append(c)
            continue # סיימנו עם המטבע הזה לסבב הנוכחי
            
        is_active_runner = bool(runner_data and runner_data["status"] == "RUNNER")
        
        # חישוב מנועים
        conf = calc_confidence(c.get("final_score", 0), c.get("pre_score", 0), c.get("flow_score", 0), "נמוך", c.get("whale_detected", False))
        pos_pct = calc_position_pct(conf)
        state = get_signal_state(c.get("entry_decision", "NO"), conf, is_active_runner)
        
        c["conf"] = conf
        c["pos_pct"] = pos_pct
        
        # שמירה חדשה ל-Runner אם קיבלנו BUY
        if state == "BUY" and not is_active_runner:
            entry = c.get("entry_price", price)
            risk = entry - c.get("entry_sl", price * 0.95)
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 4.0)
            
            save_runner(sym, entry, c.get("entry_sl", price), tp1, tp2)
            
            c["tp1"] = tp1
            c["tp2"] = tp2
            c["rr"] = 2.3 # נתון להמחשה
            
        elif is_active_runner:
            c["open_pnl_pct"] = runner_data["open_pnl_pct"]
        
        if state != "IGNORE":
            categorized[state].append(c)

    # יש לנו "מהלך גדול" גם אם נסגר טרייד וצריך לדווח עליו
    is_big_move = len(categorized["BUY"]) > 0 or len(categorized["RUNNER"]) > 0 or len(categorized["CLOSED"]) > 0
    lines = []
    
    if not is_big_move:
        # ─── סריקה רגילה ───
        lines.append("🔥 *CRYPTO\\-BOT Elite*")
        lines.append(f"📊 מצב שוק: {_e(regime)}\n")
        
        if not categorized["PREPARE"] and not categorized["WATCH"]:
            lines.append("❌ אין כרגע מועמדים איכותיים")
            lines.append("⏳ ממתינים לסריקה הבאה")
        else:
            total = len(categorized['PREPARE']) + len(categorized['WATCH'])
            lines.append(f"👁 *{total} מטבעות במעקב*\n")
            
            for i, c in enumerate(categorized["PREPARE"]):
                lines.append(f"{_e('🥇' if i==0 else '🥈')} *{_e(c['symbol'])}*")
                lines.append("פריצה מתבשלת \\| ⏳ 30–90 דקות\n")
                
            for i, c in enumerate(categorized["WATCH"]):
                lines.append(f"👁 *{_e(c['symbol'])}*")
                lines.append("בנייה מוקדמת \\| ⏳ 1–4 שעות\n")
    else:
        # ─── התראות אקטיביות (קנייה / רץ / סגירה) ───
        lines.append("🚨 *SYSTEM ALERT* 🚨\n")
        
        # סגירות פוזיציה תחילה
        for c in categorized["CLOSED"]:
            pnl = c.get('close_pnl_pct', 0)
            sign = "+" if pnl >= 0 else ""
            icon = "🟢" if pnl > 0 else "🔴"
            
            lines.append(f"🔴 *CLOSE RUNNER*\n*{_e(c['symbol'])}*\n")
            lines.append("סגירת פוזיציה \\| Trailing Stop הופעל")
            lines.append(f"💰 רווח/הפסד סופי: {icon} `{sign}{pnl}%`\n")
            lines.append("━━━━━━━━━━━━\n")

        # קניות חדשות
        for c in categorized["BUY"]:
            entry = c.get("entry_price", c.get("price", 0))
            sl = c.get("entry_sl", 0)
            
            lines.append(f"🟢 *BUY*\n*{_e(c['symbol'])}*\n")
            lines.append(f"📌 כניסה: `{_fmt_price(entry)}`")
            lines.append(f"🛑 סטופ: `{_fmt_price(sl)}`\n")
            lines.append(f"🎯 יעד 1: `{_fmt_price(c.get('tp1', entry*1.05))}`")
            lines.append(f"🎯 יעד 2: `{_fmt_price(c.get('tp2', entry*1.15))}`\n")
            
            lines.append(f"⚖️ R:R: `{c.get('rr', '2.0')}`")
            lines.append(f"🎯 ביטחון: `{c['conf']:.0f}%`")
            lines.append(f"💰 פוזיציה: `{c['pos_pct']}%` מהתיק\n")
            lines.append("━━━━━━━━━━━━\n")
            
        # טריידים פתוחים שרצים ברווח
        for c in categorized["RUNNER"]:
            pnl = c.get('open_pnl_pct', 0)
            sign = "+" if pnl >= 0 else ""
            
            lines.append(f"🚀 *RUNNER*\n*{_e(c['symbol'])}*\n")
            lines.append(f"📈 רווח פתוח: `{sign}{pnl}%`")
            lines.append("החזק את הרץ \\| Trailing Stop פעיל\n")
            lines.append("━━━━━━━━━━━━\n")
            
    return "\n".join(lines).strip()

def send_telegram(coins_data: list[dict], regime: str = "RANGE"):
    if not coins_data:
        return
        
    text = format_message(coins_data, regime)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": text, 
            "parse_mode": "MarkdownV2"
        }, timeout=10)
        resp.raise_for_status()
        log.info("Telegram notification sent.")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
