"""
CRYPTO-BOT Elite — Export Clean Learning Dataset (BUY Signals Only, Full Features)
"""
import os
import sqlite3
import pandas as pd
from utils.logger import get_logger

log = get_logger("dataset_exporter")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
OUTPUT_CSV = "data/learning_dataset.csv"


def export_ml_dataset():
    if not os.path.exists(DB_PATH):
        log.error(f"Database file {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    
    query = """
        SELECT 
            id,
            ts,
            symbol,
            decision,
            setup,
            entry_price,
            trigger_price,
            tp1,
            tp2,
            sl,
            ai_score,
            flow_score,
            pre_score,
            oi_change,
            rs_1h,
            CASE WHEN UPPER(is_compressed) = 'TRUE' THEN 1 ELSE 0 END as is_compressed,
            probability,
            market_health,
            news_score,
            btc_regime,
            funding,
            outcome_trigger_hit,
            outcome_tp1_hit,
            outcome_tp2_hit,
            outcome_sl_hit,
            COALESCE(outcome_mfe, 0) as outcome_mfe,
            COALESCE(outcome_mae, 0) as outcome_mae,
            time_to_trigger_min,
            time_to_tp1_min,
            time_to_sl_min,
            COALESCE(pnl_pct, 0) as pnl_pct,
            COALESCE(max_profit_pct, 0) as max_profit_pct,
            COALESCE(max_drawdown_pct, 0) as max_drawdown_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND UPPER(decision) = 'BUY'
        ORDER BY id ASC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        log.warning("No FINAL 'BUY' trades found for exporting ML dataset.")
        return

    # Target: 1 if TP1 hit and SL not hit, else 0
    df["target"] = ((df["outcome_tp1_hit"] == 1) & (df["outcome_sl_hit"] == 0)).astype(int)

    # Feature engineering (interactions)
    df["rs_x_flow"] = df["rs_1h"] * df["flow_score"]
    df["compressed_x_oi"] = df["is_compressed"] * df["oi_change"]
    df["prob_x_flow"] = df["probability"] * df["flow_score"]

    # Hour extraction
    df["hour"] = pd.to_datetime(df["ts"]).dt.hour

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    log.info(f"ML Dataset successfully exported to {OUTPUT_CSV} ({len(df)} 'BUY' samples)")


if __name__ == "__main__":
    export_ml_dataset()
