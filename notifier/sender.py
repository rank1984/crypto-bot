import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

def _fmt_price(p: float) -> str:
    if not p: return "—"
    if p >= 100: return f"{p:.2f}"
    if p >= 1: return f"{p:.4f}"
    if p >= 0.001: return f"{p:.5f}"
    return f"{p:.8f}"

def _build_top_coin_message(c: dict) -> str:
    sym = c.get('symbol', '').replace('USDT', '')
    ai = c.get('ai_score', 0)
    prob = c.get('probability', 0)
    rank = c.get('rank', '1')
    rank_total = c.get('rank_total', '?')
    eta = c.get('eta', 'לא ידוע')
    risk = c.get('risk', 'MEDIUM').upper()
    
    status_raw = c.get('status', 'EARLY')
    status = "PRE_BREAKOUT" if ai >= 80 else ("BUILDING" if ai >= 70 else "WATCH")
    
    price_val = c.get('price', 0.0)
    trigger_val = c.get('trigger_price', price_val * 1.005)
    
    price = _fmt_price(price_val)
    trigger = _fmt_price(trigger_val)
    stop = _fmt_price(c.get('stop_loss', price_val * 0.97))
    target = _fmt_price(c.get('target_1', price_val * 1.05))

    # חישוב מרחק לטריגר
    if price_val > 0 and trigger_val > 0:
        dist_pct = ((trigger_val - price_val) / price_val) * 100
        dist_str = f"{dist_pct:+.2f}%"
    else:
        dist_str = "—"

    # נתוני OI
    oi_change = c.get('oi_change', 0.0)
    oi_source = c.get('oi_source', 'לא ידוע')
    oi_sign = "+" if oi_change > 0 else ""
    oi_str = f"{oi_sign}{oi_change:.1f}% ({oi_source})"

    lines = [
        f"🥇 **{sym}**",
        "",
        f"🤖 **AI Score:** {ai}/100",
        f"🎯 **Probability:** {prob}%",
        f"🏆 **Rank:** {rank} / {rank_total}",
        f"⏱ **ETA:** {eta}",
        f"⚠️ **Risk:** {risk}",
        f"**Status:** 🟡 {status}",
        "",
        f"**מחיר:** {price}",
        f"**טריגר:** {trigger}",
        f"📏 **מרחק לטריגר:** {dist_str}",
        f"📊 **OI:** {oi_str}",
        f"**סטופ:** {stop}",
        f"**יעד ראשון:** {target}",
        "",
        "**סטטוס תנאים:**"
    ]
    
    # סיבות חיוביות
    for pos in c.get('pos_reasons', []):
        lines.append(f"✅ {pos}")
        
    # סיבות שליליות / חוסרים (עם סינון סתירות)
    neg_reasons = c.get('neg_reasons', [])
    real_negatives = [n for n in neg_reasons if "התקיימו" not in n]
    
    if not real_negatives:
        lines.append("✅ כל התנאים ההכרחיים התקיימו")
    else:
        for neg in real_negatives:
            # מנקה כפילויות של המילה "חסר" אם היא כבר הגיע מהמנוע
            clean_neg = neg.replace('חסר:', '').replace('חסר ', '').strip()
            lines.append(f"❌ חסר: {clean_neg}")
            
    return "\n".join(lines)

def _build_leaderboard(coins: list[dict]) -> str:
    lines = ["📊 **Top AI Ranking**", ""]
    lines.append("`מטבע    AI   הסתברות  ETA     Rank`")
    lines.append("`---------------------------------------`")
    
    for c in coins[:10]:
        sym = c.get('symbol', '').replace('USDT', '')[:6].ljust(8)
        ai = str(c.get('ai_score', int(c.get('confidence', 0)))).ljust(4)
        prob = f"{c.get('probability', ai)}%".ljust(9)
        eta = str(c.get('eta', 'היום')).replace(' דקות', ' דק')[:7].ljust(8)
        rank_str = f"{c.get('rank', '?')}/{c.get('rank_total', '?')}"
        
        lines.append(f"`{sym} {ai} {prob} {eta} {rank_str}`")
        
    return "\n".join(lines)

def _build_ai_recommendation(top_coin: dict) -> str:
    if not top_coin:
        return ""
        
    sym = top_coin.get('symbol', '').replace('USDT', '')
    prob = top_coin.get('probability', 0)
    
    lines = ["🤖 **AI Recommendation**", ""]
    lines.append("אין פריצה מאושרת (BUY NOW) ברגע זה.")
    lines.append(f"אבל **{sym}** הוא המועמד המוביל והקרוב ביותר.")
    lines.append(f"הסתברות לפריצה בחלון הזמן הקרוב: **{prob}%**")
    lines.append("מומלץ להוסיף ל-TradingView לעקוב אחר טריגר.")
    
    return "\n".join(lines)

def format_message(coins: list[dict], **kwargs) -> str:
    if not coins:
        return "🔥 **CRYPTO-BOT ELITE**\n\nהשוק שקט. אין הזדמנויות חזקות כרגע בסריקה."

    top_coin = coins[0]
    
    parts = [
        _build_top_coin_message(top_coin),
        "━━━━━━━━━━━━━━━━━━",
        _build_leaderboard(coins),
        "━━━━━━━━━━━━━━━━━━",
        _build_ai_recommendation(top_coin)
    ]
    
    return "\n\n".join(parts)

def send_telegram(coins: list[dict], portfolio_usd: float = 1000.0, filtered: dict = None, **kwargs) -> bool:
    """
    שולח את דוח ה-v6 לטלגרם. 
    שימוש ב-**kwargs מאפשר לקבל בבטחה ארגומנטים ישנים כמו stats או all_coins מבלי לקרוס.
    """
    display_coins = coins if coins else kwargs.get("all_coins", [])
    
    if not display_coins:
        log.warning("No coins available for telegram message.")
        return False
        
    text = format_message(display_coins)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096],
            "parse_mode": "Markdown"
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False

def send_simple_message(text: str) -> bool:
    """שולח הודעה פשוטה (טקסט חופשי) לטלגרם."""
    if not text or not text.strip():
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096]
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        return False
