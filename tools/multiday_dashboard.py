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
    """Calculate mean and 95% confidence interval."""
    if len(values) == 0:
        return 0.0, 0.0, 0.0
    data = np.array(values)
    mean = np.mean(data)
    sem = np.std(data, ddof=1) / np.sqrt(len(data))
    # Use t-distribution approximation
    z = 1.96 if len(data) >= 30 else 2.0  # conservative for small samples
    ci = z * sem
    return mean, mean - ci, mean + ci


def run_multiday_dashboard():
    """Generate and print Multi-Day research dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch all signals with outcomes (non-null outcome_type)
    rows = cur.execute("""
        SELECT * FROM multiday_signals
        WHERE outcome_type IS NOT NULL AND outcome_type != 'PENDING'
        ORDER BY id
    """).fetchall()

    if not rows:
        log.info("No Multi-Day signals with outcomes found.")
        conn.close()
        return None

    df = pd.DataFrame([dict(r) for r in rows])
    conn.close()

    n = len(df)

    # Basic metrics for each horizon
    horizons = {
        "24h": {"mfe": "mfe_24h", "mae": "mae_24h", "pnl": "pnl_24h"},
        "48h": {"mfe": "mfe_48h", "mae": "mae_48h", "pnl": "pnl_48h"},
        "72h": {"mfe": "mfe_72h", "mae": "mae_72h", "pnl": "pnl_72h"},
        "7d": {"mfe": "mfe_7d", "mae": "mae_7d", "pnl": "pnl_7d"},
    }

    output = []
    output.append("=" * 60)
    output.append("   MULTI-DAY RESEARCH DASHBOARD")
    output.append("=" * 60)
    output.append(f"Total signals with outcomes: {n}")
    output.append("")

    for name, cols in horizons.items():
        if cols["pnl"] not in df.columns:
            continue
        pnl_vals = df[cols["pnl"]].dropna().values
        if len(pnl_vals) == 0:
            continue
        mean_pnl, low_pnl, high_pnl = _mean_ci(pnl_vals)
        win_rate = (pnl_vals > 0).mean() * 100
        output.append(f"--- {name} ---")
        output.append(f"  Avg PnL: {mean_pnl:.2f}%  (95% CI: {low_pnl:.2f}% – {high_pnl:.2f}%)")
        output.append(f"  Win Rate: {win_rate:.1f}%")
        # Profit Factor
        profit = pnl_vals[pnl_vals > 0].sum()
        loss = abs(pnl_vals[pnl_vals < 0].sum())
        pf = profit / loss if loss > 0 else float('inf')
        output.append(f"  Profit Factor: {pf:.2f}")
        # MFE / MAE
        if cols["mfe"] in df.columns and cols["mae"] in df.columns:
            mfe_vals = df[cols["mfe"]].dropna().values
            mae_vals = df[cols["mae"]].dropna().values
            if len(mfe_vals) > 0:
                avg_mfe = np.mean(mfe_vals)
                avg_mae = np.mean(mae_vals)
                output.append(f"  Avg MFE: {avg_mfe:.2f}%  |  Avg MAE: {avg_mae:.2f}%")
        output.append("")

    # Segmentation by Setup
    output.append("--- By Setup Type ---")
    for setup, group in df.groupby("setup_type"):
        if group.empty:
            continue
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        win_24 = (group["pnl_24h"] > 0).mean() * 100
        output.append(f"  {setup:<10}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%  Win={win_24:5.1f}%")

    output.append("")

    # Segmentation by Stage
    output.append("--- By Stage ---")
    for stage, group in df.groupby("stage"):
        if group.empty:
            continue
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        win_24 = (group["pnl_24h"] > 0).mean() * 100
        output.append(f"  {stage:<10}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%  Win={win_24:5.1f}%")

    output.append("")

    # By Exhaustion bucket
    if "exhaustion_score" in df.columns:
        df["exhaustion_bucket"] = pd.cut(
            df["exhaustion_score"],
            bins=[0, 30, 60, 100],
            labels=["LOW", "MEDIUM", "HIGH"]
        )
        output.append("--- By Exhaustion Score ---")
        for bucket, group in df.groupby("exhaustion_bucket"):
            if group.empty:
                continue
            n_g = len(group)
            pnl_24 = group["pnl_24h"].mean()
            win_24 = (group["pnl_24h"] > 0).mean() * 100
            output.append(f"  {bucket:<6}: n={n_g:3d}  PnL 24h={pnl_24:6.2f}%  Win={win_24:5.1f}%")

        output.append("")

    # Outcome types
    output.append("--- Outcome Types ---")
    for outcome, group in df.groupby("outcome_type"):
        n_g = len(group)
        pnl_24 = group["pnl_24h"].mean()
        output.append(f"  {outcome}: n={n_g:3d}  Avg PnL 24h={pnl_24:6.2f}%")

    output.append("")
    output.append("=" * 60)

    dashboard_text = "\n".join(output)
    log.info(dashboard_text)
    return dashboard_text


if __name__ == "__main__":
    run_multiday_dashboard()
