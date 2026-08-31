"""
tools/multiday_dashboard.py
Dashboard for Multi-Day Research signals.
Separate from Intraday dashboard.
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger("multiday_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _mean_ci(values, confidence=0.95):
    if len(values) == 0:
        return 0.0, 0.0, 0.0
    data = np.array(values)
    mean = np.mean(data)
    sem = np.std(data, ddof=1) / np.sqrt(len(data))
    z = 1.96 if len(data) >= 30 else 2.0
    ci = z * sem
    return mean, mean - ci, mean + ci


def run_multiday_dashboard():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT * FROM multiday_signals
        WHERE outcome_type IS NOT NULL AND outcome_type != 'PENDING'
        ORDER BY id
    """).fetchall()

    if not rows:
        log.info("No Multi-Day signals with outcomes found.")
        return None

    df = pd.DataFrame([dict(r) for r in rows])

    n = len(df)
    avg_pnl_24h = df["pnl_24h"].mean()
    avg_pnl_48h = df["pnl_48h"].mean()
    avg_pnl_72h = df["pnl_72h"].mean()
    avg_pnl_7d = df["pnl_7d"].mean()

    # Profit Factor for 24h
    profit = df[df["pnl_24h"] > 0]["pnl_24h"].sum()
    loss = abs(df[df["pnl_24h"] < 0]["pnl_24h"].sum())
    pf_24h = profit / loss if loss > 0 else float('inf')

    output = []
    output.append("=" * 60)
    output.append("   MULTI-DAY RESEARCH DASHBOARD")
    output.append("=" * 60)
    output.append(f"Signals: {n}")
    output.append(f"24h Avg PnL: {avg_pnl_24h:.2f}%  | 48h: {avg_pnl_48h:.2f}%  | 72h: {avg_pnl_72h:.2f}%  | 7d: {avg_pnl_7d:.2f}%")
    output.append(f"24h Profit Factor: {pf_24h:.2f}")
    output.append("")

    # By Setup
    output.append("--- By Setup ---")
    for setup, group in df.groupby("setup_type"):
        if group.empty:
            continue
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        output.append(f"  {setup:<10}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%")

    output.append("")

    # By Stage
    output.append("--- By Stage ---")
    for stage, group in df.groupby("stage"):
        if group.empty:
            continue
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        output.append(f"  {stage:<10}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%")

    output.append("")

    # Exhaustion buckets
    output.append("--- By Exhaustion Score (low/high) ---")
    df["exhaustion_bucket"] = pd.cut(df["exhaustion_score"], bins=[0, 30, 60, 100], labels=["LOW", "MEDIUM", "HIGH"])
    for bucket, group in df.groupby("exhaustion_bucket"):
        if group.empty:
            continue
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        output.append(f"  {bucket}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%")

    output.append("")

    # Outcome types
    output.append("--- Outcome Types ---")
    for outcome, group in df.groupby("outcome_type"):
        n_g = len(group)
        output.append(f"  {outcome}: {n_g}")

    output.append("")
    output.append("=" * 60)

    dashboard_text = "\n".join(output)
    log.info(dashboard_text)
    conn.close()
    return dashboard_text


if __name__ == "__main__":
    run_multiday_dashboard()
