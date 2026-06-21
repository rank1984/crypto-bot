import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

# ייבוא השכבות והמנועים
from engines.confidence import calc_confidence
from engines.position import calc_position_pct
from engines.signal_ai import get_signal_state
from engines.explanation import get_coin_explanation
from engines.runner import check_runner_status, save_runner

log = get_logger(__name__)

def _e(s: str) -> str:
    """הגנה חזקה על תווים ב-MarkdownV2 כדי למנוע קריסות בבוט"""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = str(s).replace(c, f"\\{c}")
    return s

def _fmt_price(p: float) -> str:
    if p >= 1: return f"{p:.4f}"
    return f"{p:.6f}"

def format_message(coins_data: list[dict], regime: str = "RANGE") -> str:
    # יצירת המבנה שמחזיק את הקטגוריות
    categorized = {"RUNNER": [], "CLOSED": [], "BUY": [], "PREPARE": [], "WATCH": [], "IGNORE": []}
    
    # 1. עיבוד כל מטבע דרך כל השכבות והמנועים
    for c in coins_data:
        sym = c["symbol"]
        price = c.get("price", 0)
        
        # שכבת הזיכרון (Runner)
        runner_data = check_runner_status(sym, price)
        if runner_data and runner_data["status"] == "CLOSED":
            c["close_pnl_pct"] = runner_data["close_pnl_pct"]
            categorized["CLOSED"].append(c)
            continue
            
        is_active_runner = bool(runner_data and runner_data["status"] == "RUNNER")
        
        # חישוב מדדי ביטחון ופוזיציה
        conf = calc_confidence(c.get("final_score", 0), c.get("pre_score", 0), c.get("flow_score", 0), "נמוך", c.get("whale_detected", False))
        pos_pct = calc_position_pct(conf)
        
        # שכבה 1: Decision Layer
        state = get_signal_state(c.get("entry_decision", "NO"), conf, is_active_runner)
        
        c["conf"] = conf
        c["pos_pct"] = pos_pct
        c["state"] = state
        
        # שכבה 2: Explanation Layer (חילוץ נקודות הלחץ והסימנים)
        pos_signals, neg_signals = get_coin_explanation(c)
        c["pos_signals"] = pos_signals
        c["neg_signals"] = neg_signals
        
        # טיפול בטריגר קנייה חדש
        if state == "BUY" and not is_active_runner:
            entry = c.get("entry_price", price)
            risk = entry - c.get("entry_sl", price * 0.95)
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 4.0)
            
            save_runner(sym, entry, c.get("entry_sl", price), tp1, tp2)
            c["tp1"] = tp1
            c["tp2"] = tp2
            c["rr"] = 2.3
            
        elif is_active_runner:
            c["open_pnl_pct"] = runner_data["open_pnl_pct"]
        
        # שיוך לקטגוריה המתאימה (כולל IGNORE אם הוא הגיע ברשימת הסריקה המובילה)
        categorized[state].append(c)

    # קביעת סוג ההודעה: האם יש איתותים קריטיים/אקטיביים?
    is_big_move_alert = len(categorized["BUY"]) > 0 or len(categorized["RUNNER"]) > 0 or len(categorized["CLOSED"]) > 0
    lines = []
    
    if not is_big_move_alert:
        # ─── סריקה רגילה (מאוזנת: החלטה מהירה + עומק הלחץ המצטבר) ───
        lines.append("🔥 *CRYPTO\\-BOT Elite*")
        lines.append(f"📊 מצב שוק: {_e(regime)}\n")
        
        total_candidates = len(categorized["PREPARE"]) + len(categorized["WATCH"]) + len(categorized["IGNORE"])
        if total_candidates == 0:
            lines.append("❌ אין כרגע מועמדים איכותיים")
            lines.append("⏳ ממתינים לסריקה הבאה")
        else:
            lines.append(f"👁 *{total_candidates} מועמדים לפני פריצה*")
            lines.append("━━━━━━━━━━━━\n")
            
            # הצגת המטבעות עם האיזון הנכון (נתוני פיצוץ וצ'ק-ליסט לחץ)
            all_visible_coins = categorized["PREPARE"] + categorized["WATCH"] + categorized["IGNORE"]
            for idx, c in enumerate(all_visible_coins):
                state = c["state"]
                
                # אייקון לפי דחיפות/מצב
                if state == "PREPARE":
                    icon, status_txt, action_txt, time_txt = "🥇", "פריצה מתבשלת", "לעקוב מקרוב (PREPARE)", "30–90 דקות"
                elif state == "WATCH":
                    icon, status_txt, action_txt, time_txt = "👁", "בנייה מוקדמת", "מעקב בלבד (WATCH)", "1–4 שעות"
                else:
                    icon, status_txt, action_txt, time_txt = "👁", "ללא מבנה ברור", "התעלמות (IGNORE)", "—"
                
                lines.append(f"{icon} *{_e(c['symbol'])}*\n")
                lines.append(f"💣 Pre\\-Breakout: `{c.get('pre_score', 0):.0f}`")
                lines.append(f"🌊 Flow: `{c.get('flow_score', 0):.0f}`\n")
                
                lines.append(f"⚡ מצב: {status_txt}")
                lines.append(f"⏳ חלון: {time_txt}\n")
                
                # הצגת שכבת ההסבר (סימני לחץ וכסף)
                for pos in c["pos_signals"]:
                    lines.append(f"✔️ {_e(pos)}")
                for neg in c["neg_signals"]:
                    lines.append(f"❌ {_e(neg)}")
                    
                lines.append(f"\n🎯 פעולה: *{_e(action_txt)}*")
                lines.append("━━━━━━━━━━━━\n")
    else:
        # ─── התראות אקטיביות (קנייה / רץ / סגירה) ───
        lines.append("🚨 *BIG MOVE DETECTED* 🚨\n")
        
        # 1. פוזיציות שנסגרו
        for c in categorized["CLOSED"]:
            pnl = c.get('close_pnl_pct', 0)
            sign = "+" if pnl >= 0 else ""
            icon = "🟢" if pnl > 0 else "🔴"
            lines.append(f"🔴 *CLOSE RUNNER*\n*{_e(c['symbol'])}*\n")
            lines.append("סגירת פוזיציה \\| Trailing Stop הופעל")
            lines.append(f"💰 רווח/הפסד סופי: {icon} `{sign}{pnl}%`\n")
            lines.append("━━━━━━━━━━━━\n")

        # 2. איתותי קנייה חדשים (פירוט מלא של פוזיציה וסיכונים)
        for c in categorized["BUY"]:
            entry = c.get("entry_price", c.get("price", 0))
            sl = c.get("entry_sl", 0)
            
            lines.append(f"🟢 *BUY*\n*{_e(c['symbol'])}*\n")
            lines.append(f"📌 כניסה: `{_fmt_price(entry)}`")
            lines.append(f"🛑 סטופ: `{_fmt_price(sl)}`\n")
            lines.append(f"🎯 יעד 1: `{_fmt_price(c.get('tp1', entry*1.05))}`")
            lines.append(f"🎯 יעד 2: `{_fmt_price(c.get('tp2', entry*1.15))}`\n")
            
            lines.append(f"⚖️ R:R: `{c.get('rr', '2.3')}`")
            lines.append(f"🎯 ביטחון: `{c['conf']:.0f}%`")
            lines.append(f"💰 פוזיציה: `{c['pos_pct']}%` מהתיק\n")
            
            # הוספת ההסבר למה המערכת נכנסת
            lines.append("🧭 סימני פיצוץ:")
            for pos in c["pos_signals"]:
                lines.append(f"  ✔️ {_e(pos)}")
            lines.append("━━━━━━━━━━━━\n")
            
        # 3. טריידים רצים
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
