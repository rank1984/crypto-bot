"""
tools/learning_dashboard.py
Dashboard for realized EV, MFE/MAE, segmentation by RS/AI buckets.
No external dependencies beyond pandas/numpy.
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime
from utils.logger import get_logger

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _mean_ci(values, confidence=0.95):
    """חישוב רווח סמך באמצעות numpy (מחליף את scipy.stats.t)."""
    if len(values) == 0:
        return 0.0, 0.0, 0.0
    data = np.array(values)
    mean = np.mean(data)
    sem = np.std(data, ddof=1) / np.sqrt(len(data))
    # t-critical value approximated for large n (z-score)
    # for n < 30, approximate with t-distribution using fixed z=2.0 (conservative)
    if len(data) >= 30:
        z = 1.96  # 95% CI
    else:
        z = 2.0  # more conservative for small samples
    ci = z * sem
    return mean, mean - ci, mean + ci


def run_dashboard():
    """הדפסת דשבורד מלא עם Data Quality section."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # שליפת כל העסקאות עם סטטוס FINAL
    rows = cur.execute("""
        SELECT 
            id, symbol, setup, entry_price, tp1, tp2, sl,
            outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            outcome_mfe, outcome_mae, outcome_max_up_pct, outcome_max_down_pct,
            pnl_pct, pnl_r, mfe_r, mae_r,
            outcome_status, outcome_checked,
            rs_bucket, ai_bucket,
            ambiguous_bar, entry_candle_ambiguous,
            was_executed, execution_timestamp,
            ts, last_update_time
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND outcome_checked = 1
        ORDER BY id
    """).fetchall()

    if not rows:
        log.info("No FINAL trades found.")
        return None

    df = pd.DataFrame([dict(r) for r in rows])

    # ============================================================
    # 1. Overview
    # ============================================================
    n = len(df)
    tp1_rate = df["outcome_tp1_hit"].mean() * 100
    win_rate = (df["pnl_pct"] > 0).mean() * 100
    avg_pnl = df["pnl_pct"].mean()
    avg_mfe = df["outcome_mfe"].mean()
    avg_mae = df["outcome_mae"].mean()
    avg_r = df["pnl_r"].mean()

    # Confidence intervals for Avg PnL
    pnl_mean, pnl_low, pnl_high = _mean_ci(df["pnl_pct"].values)
    mfe_mean, mfe_low, mfe_high = _mean_ci(df["outcome_mfe"].values)
    mae_mean, mae_low, mae_high = _mean_ci(df["outcome_mae"].values)

    # Profit Factor
    total_profit = df[df["pnl_pct"] > 0]["pnl_pct"].sum()
    total_loss = abs(df[df["pnl_pct"] < 0]["pnl_pct"].sum())
    pf = total_profit / total_loss if total_loss > 0 else float('inf')

    # Net EV after cost (0.2% per trade)
    net_ev = avg_pnl - 0.2

    # ============================================================
    # 2. RS Buckets Segmentation
    # ============================================================
    def segment_stats(df, col, label):
        stats = []
        for bucket, group in df.groupby(col):
            if group.empty:
                continue
            n_b = len(group)
            tp1_b = (group["outcome_tp1_hit"].mean() * 100)
            win_b = (group["pnl_pct"] > 0).mean() * 100
            pnl_b = group["pnl_pct"].mean()
            r_b = group["pnl_r"].mean()
            profit = group[group["pnl_pct"] > 0]["pnl_pct"].sum()
            loss = abs(group[group["pnl_pct"] < 0]["pnl_pct"].sum())
            pf_b = profit / loss if loss > 0 else float('inf')
            # CI for this bucket
            mean_b, low_b, high_b = _mean_ci(group["pnl_pct"].values)
            stats.append({
                "bucket": bucket if bucket else "UNKNOWN",
                "n": n_b,
                "tp1": tp1_b,
                "win": win_b,
                "pnl": pnl_b,
                "pnl_low": low_b,
                "pnl_high": high_b,
                "r": r_b,
                "pf": pf_b
            })
        # sort by n descending
        stats = sorted(stats, key=lambda x: x["n"], reverse=True)
        return stats

    rs_stats = segment_stats(df, "rs_bucket", "RS")
    ai_stats = segment_stats(df, "ai_bucket", "AI")

    # ============================================================
    # 3. Setup Type Segmentation
    # ============================================================
    setup_stats = segment_stats(df, "setup", "Setup")

    # ============================================================
    # 4. Data Quality Section
    # ============================================================
    ambiguous_bars = df["ambiguous_bar"].sum()
    entry_ambiguous = df["entry_candle_ambiguous"].sum()
    executed = df["was_executed"].sum()
    no_execution = n - executed
    executed_missing_fill = df[df["was_executed"] == 1]["actual_fill_price"].isnull().sum() if "actual_fill_price" in df.columns else 0

    # ============================================================
    # 5. Human vs Model (if executed data exists)
    # ============================================================
    human_ev = None
    if executed > 0:
        human_trades = df[df["was_executed"] == 1]
        human_ev = human_trades["pnl_pct"].mean() if not human_trades.empty else None

    # ============================================================
    # Print Dashboard
    # ============================================================
    output = []
    output.append("=" * 60)
    output.append("   LEARNING DASHBOARD (Realized EV — Simulated Partial Exits)")
    output.append("=" * 60)
    output.append(f"Trades: {n}  TP1 Rate: {tp1_rate:.1f}%")
    output.append(f"Avg MFE: {avg_mfe:.1f}%  (95%CI {mfe_low:.1f}-{mfe_high:.1f})")
    output.append(f"Avg MAE: {avg_mae:.1f}%  (95%CI {mae_low:.1f}-{mae_high:.1f})")
    output.append(f"Avg PnL: {avg_pnl:.2f}%  (95%CI {pnl_low:.2f}-{pnl_high:.2f})")
    output.append(f"Avg R: {avg_r:.2f}R")
    output.append(f"Realized EV: {avg_pnl:.2f}%  |  Net EV (cost 0.2%): {net_ev:.2f}%")
    output.append(f"Profit Factor: {pf:.2f}")
    output.append("")

    output.append("RS Buckets:")
    for s in rs_stats:
        output.append(f"  {s['bucket']:<10}: n={s['n']:3d}  TP1={s['tp1']:5.1f}%  Win={s['win']:5.1f}%  "
                      f"AvgPnL={s['pnl']:6.2f}%  (±{s['pnl_high']-s['pnl_low']:.2f})  AvgR={s['r']:5.2f}R  PF={s['pf']:.2f}")

    output.append("")
    output.append("AI Score Buckets:")
    for s in ai_stats:
        output.append(f"  {s['bucket']:<10}: n={s['n']:3d}  TP1={s['tp1']:5.1f}%  Win={s['win']:5.1f}%  "
                      f"AvgPnL={s['pnl']:6.2f}%  (±{s['pnl_high']-s['pnl_low']:.2f})  AvgR={s['r']:5.2f}R  PF={s['pf']:.2f}")

    output.append("")
    output.append("Setup Type:")
    for s in setup_stats:
        output.append(f"  {s['bucket']:<12}: n={s['n']:3d}  TP1={s['tp1']:5.1f}%  Win={s['win']:5.1f}%  "
                      f"AvgPnL={s['pnl']:6.2f}%  (±{s['pnl_high']-s['pnl_low']:.2f})  AvgR={s['r']:5.2f}R  PF={s['pf']:.2f}")

    output.append("")
    output.append("Data Quality:")
    output.append(f"  Ambiguous bars (TP & SL same candle): {ambiguous_bars}/{n} ({ambiguous_bars/n*100:.1f}%)")
    output.append(f"  Entry candle ambiguous (mid-candle entry): {entry_ambiguous}/{n} ({entry_ambiguous/n*100:.1f}%)")
    output.append(f"  Marked executed but missing fill price: {executed_missing_fill}/{n}")
    output.append(f"  No execution data at all: {no_execution}/{n} ({no_execution/n*100:.1f}%)")

    output.append("")
    output.append("Model EV vs Human Execution:")
    output.append(f"  Model EV (all signals):      {avg_pnl:.2f}%  (n={n})")
    if human_ev is not None:
        output.append(f"  Human EV (executed trades):   {human_ev:.2f}%  (n={executed})")
    else:
        output.append("  Human EV: no executed trades tracked yet (waiting on /buy /done data)")
    output.append(f"  Skipped signals:              {no_execution}/{n}")
    output.append("=" * 60)

    dashboard_text = "\n".join(output)
    log.info(dashboard_text)
    conn.close()
    return dashboard_text


if __name__ == "__main__":
    run_dashboard()