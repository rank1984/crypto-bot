"""
CRYPTO-BOT Elite — Export Clean Learning Dataset (BUY FINAL with full features)
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
            id, ts, symbol, decision, setup,
            entry_price, trigger_price, tp1, tp2, sl,
            ai_score, flow_score, pre_score, oi_change, rs_1h,
            is_compressed, probability, market_health, news_score,
            btc_regime, funding,
            outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            outcome_mfe, outcome_mae, pnl_pct, pnl_r, mfe_r, mae_r,
            exit_reason, exit_price, duration_minutes,
            shadow_rs, shadow_tags
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND decision = 'BUY'
          AND outcome_checked = 1
          AND pnl_pct IS NOT NULL
        ORDER BY id ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        log.warning("No checked BUY FINAL trades with PnL found.")
        return

    df["target_tp1"] = df["outcome_tp1_hit"].astype(int)
    df["target_win"] = (df["pnl_pct"] > 0).astype(int)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)

    log.info(f"ML Dataset exported to {OUTPUT_CSV} ({len(df)} BUY FINAL samples)")