"""
CRYPTO-BOT Elite — Main Orchestrator (Robust Version)

מנהל את זרימת העבודה מקצה לקצה:
    1. טעינת היקום וזיהוי משטר השוק (עם זיהוי פונקציות אוטומטי)
    2. סריקה, דירוג והערכת כניסה לכל מטבע
    3. שמירה מלאה של כל הנתונים (כולל פסילות) ל-DB לטובת למידה
    4. שליחת סיגנלים חמים או סיכום שוק ממוקד לטלגרם
"""
import argparse
import sys
import pandas as pd
from datetime import datetime

from utils.logger import get_logger
from engines.flow_engine import calc_flow_score
from engines.entry_engine import evaluate_entry
from engines.pre_explosion import calc_pre_explosion

# ייבוא המודולים עצמם באופן מלא כדי למנוע שגיאות ImportError על שמות פונקציות
import scanner.universe
import scanner.regime
import scanner.ranking
import storage.sqlite_db
import utils.telegram

log = get_logger(__name__)


def _get_smart_function(module, possible_names: list):
    """מוצאת באופן דינמי את הפונקציה הנכונה מתוך המודול כדי למנוע קריסת אימפורט"""
    for name in possible_names:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"Could not find any of {possible_names} in module {module.__name__}")


def run_pipeline(debug_mode: bool = False):
    log.info(f"Starting scan pipeline | Mode: {'DEBUG (Low Thresholds)' if debug_mode else 'PRODUCTION'}")
    
    # חילוץ פונקציות חכם - מתאים את עצמו לשמות שבקוד שלך
    try:
        get_universe_func = _get_smart_function(scanner.universe, ['get_coingecko_universe', 'get_universe', 'load_universe', 'build_universe'])
        detect_regime_func = _get_smart_function(scanner.regime, ['detect_market_regime', 'get_market_regime', 'detect_regime'])
        scan_coin_func = _get_smart_function(scanner.ranking, ['scan_coin', 'score_coin', 'process_coin'])
        save_results_func = _get_smart_function(storage.sqlite_db, ['save_scan_results', 'save_results', 'log_results'])
        
        send_alert_func = _get_smart_function(utils.telegram, ['send_telegram_alert', 'send_alert'])
        send_summary_func = _get_smart_function(utils.telegram, ['send_telegram_summary', 'send_summary', 'send_report'])
    except AttributeError as e:
        log.error(f"Initialization Error: {e}")
        sys.exit(1)

    # 1. טעינת יקום המטבעות
    symbols = get_universe_func()
    if not symbols:
        log.error("Failed to fetch universe symbols. Exiting.")
        return
    
    # 2. זיהוי משטר שוק וקביעת רף
    btc_mom_1h = -0.1   
    btc_mom_5m = -0.05
    regime = detect_regime_func() 
    
    min_score_threshold = 40.0 if debug_mode else 60.0
    log.info(f"Market Regime: {regime} | Active Score Threshold: {min_score_threshold}")

    all_scanned_data = []
    buy_signals = []
    
    # 3. לולאת הסריקה הראשית
    for idx, sym in enumerate(symbols, 1):
        try:
            coin_data, df_5m = scan_coin_func(sym)
            if coin_data is None or df_5m is None:
                continue
                
            # חישוב רכיבי ה-Flow
            flow_res = calc_flow_score(sym, df_5m, rs_btc_1h=coin_data.get("rs_1h", 0))
            
            # שילוב לציון פיצוץ חזוי (Pre-Explosion)
            pre_exp = calc_pre_explosion(
                flow_score=flow_res["flow_score"],
                final_score=coin_data.get("score", 0),
                breakout_score=coin_data.get("breakout_score", 0),
                is_compressed=flow_res["is_compressed"],
                whale_detected=flow_res["whale_detected"],
                cvd_trend=flow_res["cvd_trend"],
                oi_change=flow_res["oi_change"],
                rs_btc_1h=coin_data.get("rs_1h", 0),
                momentum_15m=coin_data.get("momentum_15m", 0),
                vol_accel=flow_res["vol_accel"]
            )
            
            # בדיקת סיגנל כניסה
            entry_signal = evaluate_entry(coin_data, df_5m, btc_mom_1h, btc_mom_5m)
            
            record = {
                "symbol": sym,
                "timestamp": datetime.now().isoformat(),
                "flow_score": flow_res["flow_score"],
                "pre_explosion_score": pre_exp["score"],
                "phase": pre_exp["phase"],
                "decision": entry_signal.decision,
                "reason": entry_signal.reason if entry_signal.reason else "Passed Filters",
                "setup_type": entry_signal.setup_type,
                "entry_price": entry_signal.entry,
                "sl": entry_signal.sl,
                "tp1": entry_signal.tp1
            }
            all_scanned_data.append(record)
            
            if entry_signal.decision == "BUY" and pre_exp["score"] >= min_score_threshold:
                buy_signals.append(record)
                
        except Exception as e:
            log.debug(f"Error processing {sym}: {e}")
            continue

    # ─── עדיפות 1: שמירה מלאה של כל הממצאים לתוך ה-DB ───
    if all_scanned_data:
        df_log = pd.DataFrame(all_scanned_data)
        save_results_func(df_log)  
        log.info(f"Saved {len(all_scanned_data)} coin metrics to SQLite database for continuous learning.")

    # ─── ניתוח תוצאות והחלטת הפצה (עדיפות 2 ועדיפות 3) ───
    if buy_signals:
        log.info(f"Found {len(buy_signals)} valid BUY signals! Dispatching immediate alerts...")
        for signal in buy_signals:
            send_alert_func(signal)
    else:
        log.info("No coins passed the execution thresholds for a BUY signal.")
        
        # ─── עדיפות 2: יצירת הודעת סיכום חכמה (Top 3) לטלגרם במקום שתיקה ───
        if all_scanned_data:
            df_potential = pd.DataFrame(all_scanned_data)
            top_misses = df_potential.sort_values(by="pre_explosion_score", ascending=False).head(3).to_dict(orient="records")
            
            log.info("Sending 'Near Misses' summary report to Telegram to prevent dark spots.")
            send_summary_func(top_misses, regime=regime)
        else:
            log.warning("No scanned data available to generate a summary report.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CRYPTO-BOT Execution Pipeline")
    parser.add_argument("--once", action="store_true", help="Run the scanner exactly once")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode with lowered score thresholds")
    
    args = parser.parse_args()
    
    run_pipeline(debug_mode=args.debug)
