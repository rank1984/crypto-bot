"""
CRYPTO-BOT Elite — Winner & Failure Replay Engine
כלי מחקר להרצת מטבעות לאחור בזמן ובדיקת דיוק הציון.
"""
import time
import requests
from scanner.market_data import get_all_timeframes
# כאן אנחנו מייבאים את פונקציות החישוב שלך (שנה את השמות אם הם שונים אצלך)
from scanner.scoring import calculate_final_score 
from utils.config import KUCOIN_BASE
from utils.logger import get_logger

log = get_logger(__name__)

# הגדרת חלונות הזמן לאחור (בשעות)
INTERVALS_HOURS = [12, 6, 3, 1]

def fetch_top_24h_gainers(limit: int = 3) -> list:
    """
    מושך מ-KuCoin את המטבעות שעשו את העלייה הגבוהה ביותר ב-24 השעות האחרונות.
    """
    try:
        resp = requests.get(f"{KUCOIN_BASE}/api/v1/market/allTickers")
        resp.raise_for_status()
        tickers = resp.json().get("data", {}).get("ticker", [])
        
        # סינון רק של זוגות USDT ויציבים
        usdt_tickers = [t for t in tickers if t["symbol"].endswith("-USDT")]
        
        # מיון לפי אחוז שינוי (changeRate) מהגבוה לנמוך
        sorted_tickers = sorted(usdt_tickers, key=lambda x: float(x.get("changeRate", 0)), reverse=True)
        
        winners = []
        for t in sorted_tickers[:limit]:
            clean_sym = t["symbol"].replace("-USDT", "USDT")
            winners.append({
                "symbol": clean_sym,
                "change_24h": float(t["changeRate"]) * 100
            })
        return winners
    except Exception as e:
        log.error(f"Failed to fetch top gainers: {e}")
        return []

def run_replay_for_coin(symbol: str):
    """
    מריץ סימולציית עבר עבור מטבע בודד בנקודות זמן שונות
    """
    current_time = int(time.time())
    print(f"\n🔎 מתחיל תחקיר עבור המטבע: {symbol}")
    print(f"=========================================")
    
    # טבלת תוצאות מעוצבת למסך
    print(f"{'זמן בדיקה':<15} | {'מחיר סגירה':<12} | {'ציון סופי (Score)':<18}")
    print("-" * 55)
    
    for hours_ago in INTERVALS_HOURS:
        # חישוב ה-Timestamp המדויק לעבר
        past_timestamp = current_time - (hours_ago * 60 * 60)
        
        # משיכת נתוני המקרו והמיקרו בדיוק כפי שהיו באותו רגע בעבר
        historical_dfs = get_all_timeframes(symbol, end_time=past_timestamp)
        
        if not historical_dfs or "1hour" not in historical_dfs:
            print(f"T-{hours_ago:<2}h ago      | מידע חסר ב-API")
            continue
            
        # חילוץ המחיר האחרון שהיה ידוע באותה נקודת זמן
        past_price = historical_dfs["1hour"]["close"].iloc[-1]
        
        # 🧠 הרצת המידע ההיסטורי בתוך מנוע החישוב שלך
        # הפונקציה הזו צריכה לקבל את ה-dfs של העבר ולחשב ציון כאילו זה לייב
        try:
            scores = calculate_final_score(historical_dfs)
            final_score = scores.get("final_score", 0)
            status = "🟢 WATCH" if final_score >= 80 else "⚪ IGNORE"
        except Exception as e:
            final_score = 0
            status = f"🔴 שגיאת חישוב"

        print(f"T-{hours_ago:<2} שעות אחורה | {past_price:<12.4f} | {final_score:<5.0f} ({status})")

def main():
    print("🏆 מנוע WINNER REPLAY מתחיל לפעול...")
    
    # 1. מציאת המנצחים הגדולים של היום
    winners = fetch_top_24h_gainers(limit=3)
    if not winners:
        print("לא נמצאו מטבעות מובילים לסריקה.")
        return
        
    print(f"נמצאו {len(winners)} מנצחים גדולים ב-24 השעות האחרונות.")
    
    # 2. הרצת מכונת הזמן על כל אחד מהם
    for coin in winners:
        print(f"\n🚀 {coin['symbol']} עשה +{coin['change_24h']:.1f}% היום!")
        run_replay_for_coin(coin["symbol"])

if __name__ == "__main__":
    main()
