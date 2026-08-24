"""
tools/learning_dashboard_extended.py
מורחב להצגת Data Quality, CI לכל bucket, ונתוני ambiguous/execution.
"""
import os
import sqlite3
import pandas as pd
from datetime import datetime
from utils.logger import get_logger
from tools.learning_dashboard import _mean_ci  # נשתמש בפונקציה הקיימת

log = get_logger("learning_dashboard_extended")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def run_extended_dashboard():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT 
            symbol, decision, setup, entry_price, tp1, tp2, sl,
            outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            outcome_mfe, outcome_mae, pnl_pct, pnl_r,
            rs_bucket, ai_bucket, 
            ambiguous_bar, entry_candle_ambiguous,
            was_executed, execution_timestamp, actual_fill_price,
            outcome_status, outcome_checked
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
    """, conn)
    conn.close()

    if df.empty:
        print("No FINAL trades found.")
        return

    n = len(df)
    print("=" * 60)
    print("LEARNING DASHBOARD EXTENDED (Data Quality & Buckets)")
    print("=" * 60)
    print(f"Total FINAL trades: {n}")

    # --- Data Quality ---
    ambiguous_bar_count = df['ambiguous_bar'].sum()
    entry_ambiguous_count = df['entry_candle_ambiguous'].sum()
    executed_count = df['was_executed'].sum()
    executed_with_fill = df[df['was_executed'] == 1]['actual_fill_price'].notna().sum()
    no_execution = n - executed_count

    print("\n--- DATA QUALITY ---")
    print(f"Ambiguous bars (TP & SL same candle): {ambiguous_bar_count} / {n} ({ambiguous_bar_count/n*100:.1f}%)")
    print(f"Entry candle ambiguous (entry inside candle): {entry_ambiguous_count} / {n} ({entry_ambiguous_count/n*100:.1f}%)")
    print(f"Marked executed: {executed_count} / {n} ({executed_count/n*100:.1f}%)")
    print(f"  - with actual fill price: {executed_with_fill} / {executed_count if executed_count > 0 else 1}")
    print(f"No execution data at all: {no_execution} / {n} ({no_execution/n*100:.1f}%)")

    # --- Buckets ---
    for bucket_col, label in [('rs_bucket', 'RS Buckets'), ('ai_bucket', 'AI Score Buckets')]:
        print(f"\n--- {label} (with 95% CI for AvgPnL) ---")
        groups = df.groupby(bucket_col)
        for bucket, group in groups:
            count = len(group)
            tp1_rate = group['outcome_tp1_hit'].mean() * 100
            win_rate = (group['pnl_pct'] > 0).mean() * 100
            avg_pnl = group['pnl_pct'].mean()
            avg_r = group['pnl_r'].mean()
            pf = (group[group['pnl_pct'] > 0]['pnl_pct'].sum() / 
                  abs(group[group['pnl_pct'] < 0]['pnl_pct'].sum()) if (group['pnl_pct'] < 0).any() else float('inf'))
            ci_low, ci_high = _mean_ci(group['pnl_pct'])
            print(f"  {bucket:12s}: n={count:3d}  TP1={tp1_rate:5.1f}%  Win={win_rate:5.1f}%  "
                  f"AvgPnL={avg_pnl:6.2f}%  (±{ (ci_high - ci_low)/2:.2f}%)  AvgR={avg_r:5.2f}R  PF={pf:6.2f}")

    # --- Setup Type ---
    print("\n--- Setup Type ---")
    groups = df.groupby('setup')
    for setup, group in groups:
        count = len(group)
        tp1_rate = group['outcome_tp1_hit'].mean() * 100
        win_rate = (group['pnl_pct'] > 0).mean() * 100
        avg_pnl = group['pnl_pct'].mean()
        avg_r = group['pnl_r'].mean()
        pf = (group[group['pnl_pct'] > 0]['pnl_pct'].sum() / 
              abs(group[group['pnl_pct'] < 0]['pnl_pct'].sum()) if (group['pnl_pct'] < 0).any() else float('inf'))
        print(f"  {setup:12s}: n={count:3d}  TP1={tp1_rate:5.1f}%  Win={win_rate:5.1f}%  "
              f"AvgPnL={avg_pnl:6.2f}%  AvgR={avg_r:5.2f}R  PF={pf:6.2f}")

    # --- Overall ---
    print("\n--- OVERALL ---")
    tp1_rate = df['outcome_tp1_hit'].mean() * 100
    win_rate = (df['pnl_pct'] > 0).mean() * 100
    avg_pnl = df['pnl_pct'].mean()
    avg_r = df['pnl_r'].mean()
    avg_mfe = df['outcome_mfe'].mean()
    avg_mae = df['outcome_mae'].mean()
    pf = (df[df['pnl_pct'] > 0]['pnl_pct'].sum() / 
          abs(df[df['pnl_pct'] < 0]['pnl_pct'].sum()) if (df['pnl_pct'] < 0).any() else float('inf'))
    ci_low, ci_high = _mean_ci(df['pnl_pct'])
    print(f"  Trades: {n}")
    print(f"  TP1 Rate: {tp1_rate:.1f}%")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Avg PnL: {avg_pnl:.2f}%  (95% CI: {ci_low:.2f}% - {ci_high:.2f}%)")
    print(f"  Avg R: {avg_r:.2f}R")
    print(f"  Avg MFE: {avg_mfe:.2f}%")
    print(f"  Avg MAE: {avg_mae:.2f}%")
    print(f"  Profit Factor: {pf:.2f}")

if __name__ == "__main__":
    run_extended_dashboard()
