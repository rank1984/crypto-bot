"""
tools/edge_audit.py
Full Edge Audit on shadow_trades – determines if the AI Score has predictive power.

Outputs:
- Performance by AI Score bucket
- Performance by Setup Type
- Performance by Regime
- Performance by Trigger Distance bucket
- AI × Regime cross-tab
- Win rate, TP1 rate, SL rate, Avg R, PF, MFE, MAE per bucket
- Monte Carlo-free CIs (normal approximation)
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger("edge_audit")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _ci95(values):
    """Return (mean, low, high) for 95% CI using normal approximation."""
    if len(values) < 2:
        return (np.mean(values) if values else 0.0, 0.0, 0.0)
    arr = np.array(values)
    mean = float(np.mean(arr))
    sem = float(np.std(arr, ddof=1) / np.sqrt(len(arr)))
    return (mean, mean - 1.96 * sem, mean + 1.96 * sem)


def _bucket_ai(x):
    if pd.isna(x): return "UNKNOWN"
    if x < 20: return "AI_0_20"
    if x < 40: return "AI_20_40"
    if x < 60: return "AI_40_60"
    if x < 80: return "AI_60_80"
    return "AI_80_100"


def _bucket_trigger(x):
    if pd.isna(x): return "UNKNOWN"
    x = abs(float(x))
    if x < 0.05: return "0_0.05%"
    if x < 0.10: return "0.05_0.10%"
    if x < 0.25: return "0.10_0.25%"
    if x < 0.50: return "0.25_0.50%"
    return ">=0.50%"


def _stats(group: pd.DataFrame, label: str) -> dict:
    """Compute all performance metrics for a group of trades."""
    n = len(group)
    if n == 0:
        return None

    pnl = group["pnl_pct"].dropna().values
    pnl_r = group["pnl_r"].dropna().values if "pnl_r" in group.columns else np.array([])
    mfe = group["outcome_mfe"].dropna().values if "outcome_mfe" in group.columns else np.array([])
    mae = group["outcome_mae"].dropna().values if "outcome_mae" in group.columns else np.array([])

    if len(pnl) == 0:
        return None

    # Win rate (PnL > 0)
    win_rate = (pnl > 0).mean() * 100

    # TP1 hit rate
    tp1_hit = group["outcome_tp1_hit"].mean() * 100 if "outcome_tp1_hit" in group.columns else 0
    sl_hit = group["outcome_sl_hit"].mean() * 100 if "outcome_sl_hit" in group.columns else 0
    tp2_hit = group["outcome_tp2_hit"].mean() * 100 if "outcome_tp2_hit" in group.columns else 0

    # Avg PnL & CI
    mean_pnl, low_pnl, high_pnl = _ci95(pnl)

    # Avg R
    avg_r = float(np.mean(pnl_r)) if len(pnl_r) > 0 else 0.0

    # Profit Factor
    total_profit = pnl[pnl > 0].sum()
    total_loss = abs(pnl[pnl < 0].sum())
    pf = total_profit / total_loss if total_loss > 0 else float('inf')

    # MFE / MAE
    avg_mfe = float(np.mean(mfe)) if len(mfe) > 0 else 0.0
    avg_mae = float(np.mean(mae)) if len(mae) > 0 else 0.0

    return {
        "label": label,
        "n": n,
        "tp1_pct": round(tp1_hit, 1),
        "tp2_pct": round(tp2_hit, 1),
        "sl_pct": round(sl_hit, 1),
        "win_pct": round(win_rate, 1),
        "avg_pnl": round(mean_pnl, 2),
        "ci_low": round(low_pnl, 2),
        "ci_high": round(high_pnl, 2),
        "avg_r": round(avg_r, 3),
        "pf": round(pf, 2) if pf != float('inf') else "∞",
        "mfe": round(avg_mfe, 2),
        "mae": round(avg_mae, 2),
    }


def _print_table(title: str, rows: list):
    if not rows:
        print(f"\n{title}: No data")
        return
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    header = f"{'Bucket':<20} {'N':>5} {'TP1%':>6} {'TP2%':>6} {'SL%':>6} {'Win%':>6} {'AvgPnL':>8} {'95%CI':>15} {'AvgR':>7} {'PF':>6} {'MFE':>6} {'MAE':>6}"
    print(header)
    print("-" * 100)
    for r in rows:
        ci = f"[{r['ci_low']:+.2f},{r['ci_high']:+.2f}]"
        pf_str = f"{r['pf']}" if r['pf'] == "∞" else f"{r['pf']:.2f}"
        print(
            f"{r['label']:<20} {r['n']:>5} {r['tp1_pct']:>6.1f} {r['tp2_pct']:>6.1f} "
            f"{r['sl_pct']:>6.1f} {r['win_pct']:>6.1f} {r['avg_pnl']:>+8.2f} {ci:>15} "
            f"{r['avg_r']:>+7.3f} {pf_str:>6} {r['mfe']:>6.2f} {r['mae']:>6.2f}"
        )


def run_edge_audit():
    print("\n" + "="*100)
    print("  CRYPTO-BOT EDGE AUDIT – shadow_trades")
    print("="*100)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch all FINAL trades
    rows = cur.execute("""
        SELECT
            id, symbol, decision, setup, ai_score, flow_score, pre_score,
            probability, rs_1h, oi_change, is_compressed,
            btc_regime, market_health, news_score,
            entry_price, tp1, tp2, sl, trigger_price,
            outcome_status, outcome_checked,
            outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            outcome_mfe, outcome_mae, pnl_pct, pnl_r, mfe_r, mae_r,
            first_outcome_type, pnl_pct_method,
            rs_bucket, ai_bucket, ambiguous_bar
        FROM shadow_trades
        WHERE decision='BUY'
          AND outcome_status='FINAL'
          AND outcome_checked=1
        ORDER BY id
    """).fetchall()
    conn.close()

    if not rows:
        print("\n❌ No FINAL trades found.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    n_total = len(df)

    print(f"\n📊 Total FINAL trades: {n_total}")
    print(f"   Time range: {df.index[0]} → {df.index[-1]} (rows)")

    # ── Overall stats ────────────────────────────────────────────────
    overall = _stats(df, "ALL")
    _print_table("OVERALL PERFORMANCE", [overall])

    # ── Prepare buckets ──────────────────────────────────────────────
    df["ai_bucket"] = df["ai_score"].apply(_bucket_ai)
    df["setup_bucket"] = df["setup"].fillna("UNKNOWN")

    # Trigger distance
    df["trigger_dist_pct"] = np.nan
    mask = (df["trigger_price"] > 0) & (df["entry_price"] > 0)
    df.loc[mask, "trigger_dist_pct"] = (
        (df.loc[mask, "trigger_price"] - df.loc[mask, "entry_price"])
        / df.loc[mask, "entry_price"] * 100
    )
    df["trigger_bucket"] = df["trigger_dist_pct"].apply(_bucket_trigger)

    # ── By AI Bucket ─────────────────────────────────────────────────
    ai_rows = []
    for bucket in ["AI_0_20", "AI_20_40", "AI_40_60", "AI_60_80", "AI_80_100", "UNKNOWN"]:
        g = df[df["ai_bucket"] == bucket]
        if len(g) > 0:
            s = _stats(g, bucket)
            if s: ai_rows.append(s)
    _print_table("BY AI SCORE BUCKET", ai_rows)

    # ── By Setup Type ────────────────────────────────────────────────
    setup_rows = []
    for setup in sorted(df["setup_bucket"].unique()):
        g = df[df["setup_bucket"] == setup]
        if len(g) > 0:
            s = _stats(g, setup)
            if s: setup_rows.append(s)
    _print_table("BY SETUP TYPE", setup_rows)

    # ── By Regime ────────────────────────────────────────────────────
    regime_rows = []
    for regime in sorted(df["btc_regime"].fillna("UNKNOWN").unique()):
        g = df[df["btc_regime"].fillna("UNKNOWN") == regime]
        if len(g) > 0:
            s = _stats(g, regime)
            if s: regime_rows.append(s)
    _print_table("BY BTC REGIME", regime_rows)

    # ── By Trigger Distance ─────────────────────────────────────────
    trigger_rows = []
    for bucket in ["0_0.05%", "0.05_0.10%", "0.10_0.25%", "0.25_0.50%", ">=0.50%", "UNKNOWN"]:
        g = df[df["trigger_bucket"] == bucket]
        if len(g) > 0:
            s = _stats(g, bucket)
            if s: trigger_rows.append(s)
    _print_table("BY TRIGGER DISTANCE (ATR)", trigger_rows)

    # ── AI × Regime Cross-tab ────────────────────────────────────────
    print(f"\n{'='*100}")
    print("  AI BUCKET × BTC REGIME CROSS-TAB (Avg R)")
    print(f"{'='*100}")
    cross = df.pivot_table(
        index="ai_bucket", columns="btc_regime",
        values="pnl_r", aggfunc="mean"
    )
    print(cross.round(3).to_string())

    # ── Monotonicity Test ────────────────────────────────────────────
    print(f"\n{'='*100}")
    print("  MONOTONICITY TEST – does higher AI Score → higher Avg R?")
    print(f"{'='*100}")
    monotonic_data = []
    for bucket in ["AI_0_20", "AI_20_40", "AI_40_60", "AI_60_80", "AI_80_100"]:
        g = df[df["ai_bucket"] == bucket]
        if len(g) >= 5:
            avg_r = float(g["pnl_r"].dropna().mean())
            monotonic_data.append((bucket, len(g), avg_r))

    if len(monotonic_data) >= 3:
        print(f"{'Bucket':<12} {'N':>5} {'AvgR':>8} {'Monotonic?':>12}")
        print("-" * 45)
        prev_r = None
        for bucket, n, avg_r in monotonic_data:
            monotonic = "—"
            if prev_r is not None:
                if avg_r > prev_r:
                    monotonic = "✅ UP"
                elif avg_r < prev_r:
                    monotonic = "❌ DOWN"
                else:
                    monotonic = "= FLAT"
            print(f"{bucket:<12} {n:>5} {avg_r:>+8.3f} {monotonic:>12}")
            prev_r = avg_r

        print(f"\n📌 Summary:")
        if all(monotonic_data[i][2] <= monotonic_data[i+1][2] for i in range(len(monotonic_data)-1)):
            print("   ✅ MONOTONIC – AI Score has predictive power")
        else:
            print("   ❌ NOT MONOTONIC – AI Score does not cleanly predict performance")
    else:
        print("   ⚠️ Not enough buckets with N≥5 to test monotonicity")

    # ── Probability Sanity Check ─────────────────────────────────────
    print(f"\n{'='*100}")
    print("  PROBABILITY SANITY CHECK (correlation with actual outcome)")
    print(f"{'='*100}")
    valid = df.dropna(subset=["probability", "pnl_r"])
    if len(valid) >= 20:
        corr_pnl = valid["probability"].corr(valid["pnl_r"])
        corr_win = valid["probability"].corr((valid["pnl_pct"] > 0).astype(int))
        print(f"   Correlation(Probability, PnL_R):  {corr_pnl:+.3f}")
        print(f"   Correlation(Probability, Win):     {corr_win:+.3f}")
        if abs(corr_pnl) < 0.05:
            print("   ⚠️ Probability has NO correlation with outcome")
        elif corr_pnl > 0.10:
            print("   ✅ Probability has positive correlation with outcome")
        else:
            print("   ⚠️ Weak or unclear relationship")

    # ── Data Quality ─────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print("  DATA QUALITY")
    print(f"{'='*100}")
    ambiguous = df["ambiguous_bar"].sum() if "ambiguous_bar" in df.columns else 0
    print(f"   Ambiguous bars: {ambiguous} / {n_total} ({ambiguous/n_total*100:.1f}%)")

    if "first_outcome_type" in df.columns:
        outcome_counts = df["first_outcome_type"].value_counts()
        print(f"\n   First outcome types:")
        for outcome, count in outcome_counts.items():
            print(f"     {outcome}: {count} ({count/n_total*100:.1f}%)")

    if "pnl_pct_method" in df.columns:
        print(f"\n   PnL methods:")
        for method, count in df["pnl_pct_method"].value_counts().items():
            print(f"     {method}: {count}")

    print("\n" + "="*100)
    print("  END OF AUDIT")
    print("="*100 + "\n")


if __name__ == "__main__":
    run_edge_audit()