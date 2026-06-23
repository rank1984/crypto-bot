"""
CRYPTO-BOT Elite — Main Orchestrator (Native Version)

מנהל את זרימת העבודה בהתבסס על המודולים הקיימים בשרת:
    1. סריקת היקום
    2. דירוג לפי מנוע ה-Ranking הקיים
    3. שמירה לדאטהבייס לטובת למידה עתידית
    4. שליחת התראות או סיכום Top 3 (Near Misses) לטלגרם
"""
import argparse
import sys
import pandas as pd
from datetime import datetime

from utils.logger import get_logger

# ייבוא בטוח של המודולים שכבר קיימים אצלך בפרויקט
import scanner.universe
import scanner.regime
import scanner.ranking
import storage.sqlite_db

# מנגנון ייבוא חכם לטלגרם (למקרה שהתיקייה נקראת telegram ולא utils)
try:
    import utils.telegram as telegram_module
except ModuleNotFoundError:
    try:
        import telegram.sender as telegram_module
    except ModuleNotFoundError:
        telegram_module = None

log = get_logger(__name__)

def _get_smart_function(module, possible_names: list):
    """מוצאת באופן דינמי את הפונקציה הנכונה כדי למנוע קריסות"""
    if module is None: 
        return None
    for name in possible_names:
        if hasattr(module, name):
            return getattr(module, name)
    return None

def run_pipeline(debug_mode: bool = False):
    log.info(f"Starting scan pipeline | Mode: {'DEBUG (Low Thresholds)' if debug_mode else 'PRODUCTION'}")
    
    # חילוץ פונקציות חכם מהקבצים שלך
    get_universe_func = _get_smart_function(scanner.universe, ['get_coingecko_universe', 'get_universe'])
    detect_regime_func = _get_smart_function(scanner.regime, ['detect_market_regime', 'get_market_regime', 'detect_regime'])
    scan_coin_func = _get_smart_function(scanner.ranking, ['scan_coin', 'score_coin', 'process_coin'])
    save_results_func = _get_smart_function(storage.sqlite_db, ['save_scan_results', 'save_results', 'log_results', 'insert_coin'])
    
    send_alert_func = _get_smart_function(telegram_module, ['send_telegram_alert', 'send_alert', 'send_message'])
    send_summary_func = _get_smart_function(telegram_module, ['send_telegram_summary', 'send_summary', 'send_message'])

    if not get_universe_func or not scan_coin_func:
        log.error("CRITICAL ERROR: Could not find core functions in your scanner module.")
        sys.exit(1)

    symbols = get_universe_func()
    if not symbols:
        log.error("Universe is empty. Exiting.")
        return

    # זיהוי שוק
    regime = detect_regime_func() if detect_regime_func else "UNKNOWN"
    min_score_threshold = 40.0 if debug_mode else 60.0
    log.info(f"Market Regime: {regime} | Threshold: {min_score_threshold}")

    all_scanned_data = []
    buy_signals = []

    # סריקת המטבעות עם המנוע הקיים שלך
    for sym in symbols:
        try:
            result = scan_coin_func(sym)
            
            # תמיכה במבני נתונים שונים שמנוע הסריקה שלך עלול להחזיר
            if isinstance(result, tuple) and len(result) >= 1:
                coin_data = result[0]
            else:
                coin_data = result

            if not coin_data or not isinstance(coin_data, dict):
                continue

            score = coin_data.get("score", 0)
            
            record = {
                "symbol": sym,
                "timestamp": datetime.now().isoformat(),
                "score": score,
                "price": coin_data.get("price", 0),
                "volume": coin_data.get("volume", 0)
            }
            all_scanned_data.append(record)

            if score >= min_score_threshold:
                buy_signals.append(record)

        except Exception as e:
            log.debug(f"Error processing {sym}: {e}")
            continue

    # שמירה ל-DB של כל הממצאים
    if all_scanned_data and save_results_func:
        try:
            df_log = pd.DataFrame(all_scanned_data)
            save_results_func(df_log)
            log.info(f"Saved {len(all_scanned_data)} coins to SQLite DB for learning.")
        except Exception as e:
            log.error(f"Failed to save to DB: {e}")

    # טיפול בהתראות טלגרם
    if buy_signals:
        log.info(f"Found {len(buy_signals)} BUY signals! Dispatching alerts...")
        if send_alert_func:
            for signal in buy_signals:
                send_alert_func(signal)
    else:
        log.info("No coins passed the threshold.")
        # סיכום "Near Misses" (Top 3)
        if all_scanned_data and send_summary_func:
            df_potential = pd.DataFrame(all_scanned_data)
            top_misses = df_potential.sort_values(by="score", ascending=False).head(3).to_dict(orient="records")
            log.info("Sending 'Near Misses' summary to Telegram.")
            send_summary_func(top_misses)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CRYPTO-BOT Execution Pipeline")
    parser.add_argument("--once", action="store_true", help="Run the scanner exactly once")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode with lowered thresholds")
    args = parser.parse_args()
    
    run_pipeline(debug_mode=args.debug)
