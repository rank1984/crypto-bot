"""
CRYPTO-BOT Elite — Exit Simulator
Single Source of Truth for Exit Logic.
Mirrors the exact state machine of scanner/trade_manager.py
"""
import pandas as pd
from datetime import datetime
from utils.logger import get_logger

log = get_logger("exit_simulator")

try:
    # אם תרצה בעתיד לייבא את ה-ATR המקורי בדיוק כמו ב-TradeManager:
    from scanner.exit_engine import update_trailing_stop_atr
except ImportError:
    update_trailing_stop_atr = None


def simulate_trade_path(df, entry_price, sl, tp1, tp2, entry_ts, timeout_hours=48):
    """
    מדמה בדיוק את שלבי ה-TradeManager:
    ACTIVE -> TP1_HIT -> BREAKEVEN -> TP2_HIT -> RUNNER -> EXIT
    
    מחזיר: 
    (pnl_pct, exit_events, ambiguous_bar, entry_candle_ambiguous, mfe_pct, mae_pct)
    """
    position = 1.0
    current_sl = sl
    state = "ACTIVE"
    
    tp1_done = False
    tp2_done = False
    
    realized_pnl_weighted = 0.0
    highest_since_entry = entry_price
    lowest_since_entry = entry_price
    
    ambiguous_bar = 0
    entry_candle_ambiguous = 0
    exit_events = []
    
    # נוודא ש-df מסודר ויש לנו חלון ריצה לחישובים דמויי TradeManager
    df = df.sort_values("time").reset_index(drop=True)
    
    for idx, bar in df.iterrows():
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        bar_time = bar["time"]
        
        # עדכון MFE / MAE *רק* כל עוד אנחנו בפוזיציה
        if high > highest_since_entry:
            highest_since_entry = high
        if low < lowest_since_entry:
            lowest_since_entry = low
            
        # בדיקת Entry Candle Ambiguity
        # אם שעת הנר פלוס 5 דקות כוללת את שעת הכניסה - זהו נר הכניסה
        if idx == 0 and bar_time <= entry_ts < bar_time + pd.Timedelta(minutes=5):
            entry_candle_ambiguous = 1
            
        hit_sl_now = current_sl > 0 and low <= current_sl
        hit_tp1_now = (not tp1_done) and tp1 > 0 and high >= tp1
        hit_tp2_now = tp1_done and (not tp2_done) and tp2 > 0 and high >= tp2

        # Ambiguous resolution: Conservative approach (SL always triggers first)
        if hit_sl_now and (hit_tp1_now or hit_tp2_now):
            ambiguous_bar = 1
            hit_tp1_now = False
            hit_tp2_now = False

        # --- SL EVENT ---
        if hit_sl_now:
            sl_pct = (current_sl - entry_price) / entry_price * 100
            realized_pnl_weighted += sl_pct * position
            exit_events.append(("SL", sl_pct, position, bar_time))
            position = 0.0
            state = "CLOSED"
            break
            
        # --- TP1 EVENT ---
        if hit_tp1_now:
            tp1_pct = (tp1 - entry_price) / entry_price * 100
            realized_pnl_weighted += tp1_pct * 0.2
            exit_events.append(("TP1", tp1_pct, 0.2, bar_time))
            position -= 0.2
            tp1_done = True
            current_sl = entry_price  # Breakeven
            state = "BREAKEVEN"
            
        # --- TP2 EVENT ---
        if hit_tp2_now:
            tp2_pct = (tp2 - entry_price) / entry_price * 100
            realized_pnl_weighted += tp2_pct * 0.2
            exit_events.append(("TP2", tp2_pct, 0.2, bar_time))
            position -= 0.2
            tp2_done = True
            state = "RUNNER"
            
        # --- TRAILING STOP LOGIC ---
        # שחזור ההיגיון המקורב או חיבור למנוע ה-ATR
        current_pnl_pct = (close - entry_price) / entry_price * 100
        atr_multiplier = 3.0
        
        if state in ("TP2_HIT", "RUNNER"):
            atr_multiplier = 1.5
        elif state == "BREAKEVEN":
            atr_multiplier = 1.8
        elif tp1_done:
            atr_multiplier = 2.5
        elif current_pnl_pct >= 20:
            atr_multiplier = 1.5
        elif current_pnl_pct >= 10:
            atr_multiplier = 2.0
            
        # חישוב חלון לאחור אם יש מספיק נרות עבור update_trailing_stop_atr
        if update_trailing_stop_atr and idx >= 15:
            df_5m_window = df.iloc[max(0, idx-15) : idx+1]
            new_sl = update_trailing_stop_atr(df_5m_window, current_sl, atr_multiplier)
            if new_sl and new_sl > current_sl:
                current_sl = new_sl
        elif state == "RUNNER":
            # Fallback במקרה ואין ATR (כפי שהיה ב-Outcome Tracker הקודם)
            trail_level = highest_since_entry * (1 - (atr_multiplier * 0.01)) # המרה גסה
            current_sl = max(current_sl, trail_level)

        # --- TIMEOUT CHECK ---
        hours_elapsed = (bar_time - entry_ts).total_seconds() / 3600
        if hours_elapsed >= timeout_hours:
            timeout_pct = (close - entry_price) / entry_price * 100
            realized_pnl_weighted += timeout_pct * position
            exit_events.append(("TIMEOUT", timeout_pct, position, bar_time))
            position = 0.0
            state = "CLOSED"
            break

    # יציאה בסוף הנתונים אם עדיין נשאר משהו פתוח
    else:
        if position > 0:
            last_close = float(df["close"].iloc[-1])
            timeout_pct = (last_close - entry_price) / entry_price * 100
            realized_pnl_weighted += timeout_pct * position
            exit_events.append(("END_OF_DATA", timeout_pct, position, df.iloc[-1]["time"]))

    mfe_pct = (highest_since_entry - entry_price) / entry_price * 100
    mae_pct = (lowest_since_entry - entry_price) / entry_price * 100

    return round(realized_pnl_weighted, 3), exit_events, ambiguous_bar, entry_candle_ambiguous, mfe_pct, mae_pct
