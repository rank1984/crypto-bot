"""
CRYPTO-BOT Elite — Advanced Winner Replay & Analysis Engine
מאתר את נקודת הפריצה האמיתית (Breakout Anchor) וחוזר אחורה בזמן.
"""
import time
import os
import csv
import requests
import pandas as pd
from datetime import datetime

from scanner.ranking import scan_coin
from scanner.market_data import get_candles
from utils.config import KUCOIN_BASE

INTERVALS_HOURS = [12, 6, 3, 1]
REPORT_FILE = "tools/replay_report.csv"

def fetch_top_24h_gainers(limit: int = 3) -> list:
    print("📡 מושך את המנצחים הגדולים של ה-24 שעות האחרונות מ-KuCoin...")
    try:
        resp = requests.get(f"{KUCOIN_BASE}/api/v1/market/allTickers")
        resp.raise_for_status()
        tickers = resp.json().get("data", {}).get("ticker", [])
        usdt_tickers = [t for t in tickers if t["symbol"].endswith("-USDT")]
        sorted_tickers = sorted(usdt_tickers, key=lambda x: float(x.get("changeRate", 0)), reverse=True)
        
        winners = []
        for t in sorted_tickers[:limit]:
            winners.append({
                "symbol": t["symbol"].replace("-USDT", "USDT"),
                "change_24h": float(t["changeRate"]) * 100
            })
        return winners
    except Exception as e:
        print(f"❌ שגיאה במשיכת המובילים: {e}")
        return []

def find_breakout_anchor(symbol: str) -> int:
    """
    מוצא את חותמת הזמן (Timestamp) שבה התחיל המהלך האמיתי במטבע.
    סורק את 48 השעות האחרונות ומוצא את הנר (1H) עם הזינוק החד ביותר.
    """
    df = get_candles(symbol, "1hour", limit=48)
    if df is None or df.empty:
        return int(time.time())
    
    # חישוב אחוז השינוי של כל נר
    df["pct_change"] = (df["close"] - df["open"]) / df["open"] * 100
    
    # מציאת האינדקס של הנר עם העלייה הגדולה ביותר
    max_idx = df["pct_change"].idxmax()
    
    # נקודת ההתחלה היא זמן הפתיחה של הנר המפלצתי הזה
    start_time_ms = df.iloc[max_idx]["open_time"].timestamp()
    
    anchor_dt = datetime.fromtimestamp(start_time_ms)
    print(f"🎯 נקודת פריצה (Anchor) אותרה ב: {anchor_dt.strftime('%Y-%m-%d %H:%00')}")
    
    return int(start_time_ms)

def log_to_csv(data: dict):
    """שומר את תוצאות הסריקה לקובץ CSV לאימון עתידי"""
    file_exists = os.path.isfile(REPORT_FILE)
    headers = ["symbol", "hours_before", "price", "final_score", "flow_score", 
               "pre_score", "probability", "confidence", "signal", "missing_reasons"]
    
    # יצירת התיקייה אם היא לא קיימת
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    
    with open(REPORT_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

def run_replay_for_coin(symbol: str, summary_stats: dict):
    anchor_time = find_breakout_anchor(symbol)
    
    print(f"\n🔎 תחקיר לאחור עבור: {symbol}")
    print("=" * 115)
    print(f"{'Time':<6} | {'Price':<8} | {'Score':<6} | {'Flow':<5} | {'Pre':<4} | {'Prob':<4} | {'Conf':<4} | {'Signal':<10} | {'Missing'}")
    print("-" * 115)
    
    highest_signal = "MISSED"
    
    for hours_ago in INTERVALS_HOURS:
        past_timestamp = anchor_time - (hours_ago * 60 * 60)
        
        try:
            r = scan_coin(symbol, end_time=past_timestamp)
            if r is None:
                print(f"T-{hours_ago:<4}h | {'-':<8} | {'-':<6} | {'-':<5} | {'-':<4} | {'-':<4} | {'-':<4} | {'FILTERED':<10} | Hard Filter / Low RVOL")
                continue
                
            price = r.get("price", 0.0)
            score = r.get("final_score", 0.0)
            flow = r.get("flow_score", 0.0)
            pre = r.get("pre_score", 0.0)
            
            # שדות עתידיים שהגדרת, עם ברירת מחדל 0 אם עדיין לא הוטמעו ב-ranking
            prob = r.get("probability", 0.0)
            conf = r.get("confidence", 0.0)
            
            decision = r.get("entry_decision", "NONE")
            signal = "WATCH" if score >= 75 else "IGNORE"
            if decision in ["BUY", "PREPARE"]:
                signal = decision

            # עדכון מירבי של הסיגנל לסטטיסטיקה (BUY מנצח PREPARE שמנצח WATCH)
            if signal == "BUY": highest_signal = "BUY"
            elif signal == "PREPARE" and highest_signal != "BUY": highest_signal = "PREPARE"
            elif signal == "WATCH" and highest_signal not in ["BUY", "PREPARE"]: highest_signal = "WATCH"

            # 🧠 מנוע "למה לא נכנסנו?" (Missing)
            missing = []
            if flow < 70: missing.append("Flow")
            if pre < 60: missing.append("PreScore")
            if not r.get("is_compressed", False): missing.append("Compression")
            if r.get("oi_change", 0) <= 0: missing.append("OI")
            
            # נבדוק אם יש CVD_Trend, ואם הוא לא Bullish נוסיף אותו
            cvd = str(r.get("cvd_trend", ""))
            if "bullish" not in cvd.lower() and float(r.get("cvd_trend", 0.0)) <= 0:
                missing.append("CVD")
                
            missing_str = ", ".join(missing) if missing and signal != "BUY" else ""

            # הדפסה מעוצבת בדיוק לפי דרישתך
            print(f"T-{hours_ago:<4}h | {price:<8.4f} | {score:<6.1f} | {flow:<5.1f} | {pre:<4.1f} | {prob:<4.1f} | {conf:<4.1f} | {signal:<10} | {missing_str}")
            
            # שמירה ל-CSV
            log_to_csv({
                "symbol": symbol, "hours_before": hours_ago, "price": price, 
                "final_score": score, "flow_score": flow, "pre_score": pre,
                "probability": prob, "confidence": conf, "signal": signal,
                "missing_reasons": missing_str
            })
            
        except Exception as e:
            print(f"T-{hours_ago:<4}h | שגיאת מערכת: {e}")
            
    summary_stats[highest_signal] += 1

def main():
    print("🏆 WINNER REPLAY ENGINE ACTIVATED")
    winners = fetch_top_24h_gainers(limit=4)
    if not winners:
        return
        
    summary_stats = {"BUY": 0, "PREPARE": 0, "WATCH": 0, "MISSED": 0}
        
    for coin in winners:
        print(f"\n🚀 {coin['symbol']} (+{coin['change_24h']:.1f}%)")
        run_replay_for_coin(coin["symbol"], summary_stats)
        
    # הדפסת סיכום (Winner Summary)
    total = len(winners)
    detected = summary_stats["BUY"] + summary_stats["PREPARE"] + summary_stats["WATCH"]
    detection_rate = (detected / total) * 100 if total > 0 else 0

    print("\n==============================")
    print("       WINNER SUMMARY         ")
    print("==============================")
    print(f"Total Winners:  {total}")
    print(f"BUY:            {summary_stats['BUY']}")
    print(f"PREPARE:        {summary_stats['PREPARE']}")
    print(f"WATCH:          {summary_stats['WATCH']}")
    print(f"MISSED:         {summary_stats['MISSED']}")
    print("-" * 30)
    print(f"Detection Rate: {detection_rate:.0f}%")
    print("==============================\n")
    print(f"✅ Data saved to: {REPORT_FILE}")

if __name__ == "__main__":
    main()
