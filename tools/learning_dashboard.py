"""
learning_dashboard.py — Realized EV Dashboard with Data Quality & Statistical Validation
"""
import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from utils.logger import get_logger
from scipy import stats

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _mean_ci(data, confidence=0.95):
    """רווח סמך לממוצע"""
    if len(data) == 0:
        return None, None, None
    arr = np.array(data)
    mean = np.mean(arr)
    sem = stats.sem(arr) if len(arr) > 1 else 0
    if sem == 0:
        return mean, mean, mean
    ci = stats.t.interval(confidence, len(arr)-1, loc=mean, scale=sem)
    return mean, ci[0], ci[1]


def _format_ci(ci_tuple):
    if ci_tuple is None:
        return "N/A"
    mean, low, high = ci_tuple
    return f"{mean:.2f}%  (95%CI {low:.2f}-{high:.2f})"


def run_dashboard(verbose=True):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ============================================================
    # 1. שליפת נתונים בסיסיים
    # ============================================================
    rows = cur.execute("""
        SELECT 
            id, symbol, decision, setup, 
            entry_price, tp1, tp2, sl,
            ai_score, rs_1h,
            outcome_status, outcome_checked,
            outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            pnl_pct, pnl_r,
            outcome_mfe, outcome_mae,
            was_executed, execution_timestamp,
            ambiguous_bar, entry_candle_ambiguous,
            rs_bucket, ai_bucket,
            ts
        FROM shadow_trades 
        WHERE outcome_status = 'FINAL' AND outcome_checked = 1
        ORDER BY id
    """).fetchall()

    if not rows:
        log.warning("No FINAL trades found")
        return

    df = pd.DataFrame([dict(r) for r in rows])

    # ============================================================
    # 2. Data Quality Metrics
    # ============================================================
    total = len(df)
    ambiguous_bar_count = df['ambiguous_bar'].sum() if 'ambiguous_bar' in df else 0
    entry_ambiguous_count = df['entry_candle_ambiguous'].sum() if 'entry_candle_ambiguous' in df else 0
    executed_count = df['was_executed'].sum() if 'was_executed' in df else 0
    executed_but_no_time = len(df[(df['was_executed'] == 1) & (df['execution_timestamp'].isna())]) if 'execution_timestamp' in df else 0
    no_execution_data = total - executed_count

    # ============================================================
    # 3. פילוח לפי RS Buckets + CI
    # ============================================================
    rs_buckets = df.groupby('rs_bucket').agg(
        n=('id', 'count'),
        tp1_rate=('outcome_tp1_hit', lambda x: (x.sum() / len(x) * 100) if len(x) > 0 else 0),
        win_rate=('pnl_pct', lambda x: (sum(1 for v in x if v > 0) / len(x) * 100) if len(x) > 0 else 0),
        avg_pnl=('pnl_pct', 'mean'),
        avg_r=('pnl_r', 'mean'),
        pf=('pnl_pct', lambda x: -sum(v for v in x if v < 0) / sum(v for v in x if v > 0) if sum(v for v in x if v > 0) > 0 else 0)
    ).reset_index()

    # הוספת CI ל-AvgPnL
    rs_ci = []
    for bucket in rs_buckets['rs_bucket']:
        data = df[df['rs_bucket'] == bucket]['pnl_pct'].dropna().tolist()
        ci = _mean_ci(data)
        rs_ci.append(ci)
    rs_buckets['ci'] = rs_ci

    # ============================================================
    # 4. פילוח לפי AI Buckets + CI
    # ============================================================
    ai_buckets = df.groupby('ai_bucket').agg(
        n=('id', 'count'),
        tp1_rate=('outcome_tp1_hit', lambda x: (x.sum() / len(x) * 100) if len(x) > 0 else 0),
        win_rate=('pnl_pct', lambda x: (sum(1 for v in x if v > 0) / len(x) * 100) if len(x) > 0 else 0),
        avg_pnl=('pnl_pct', 'mean'),
        avg_r=('pnl_r', 'mean'),
        pf=('pnl_pct', lambda x: -sum(v for v in x if v < 0) / sum(v for v in x if v > 0) if sum(v for v in x if v > 0) > 0 else 0)
    ).reset_index()

    ai_ci = []
    for bucket in ai_buckets['ai_bucket']:
        data = df[df['ai_bucket'] == bucket]['pnl_pct'].dropna().tolist()
        ci = _mean_ci(data)
        ai_ci.append(ci)
    ai_buckets['ci'] = ai_ci

    # ============================================================
    # 5. פילוח לפי Setup Type + CI
    # ============================================================
    setup_buckets = df.groupby('setup').agg(
        n=('id', 'count'),
        tp1_rate=('outcome_tp1_hit', lambda x: (x.sum() / len(x) * 100) if len(x) > 0 else 0),
        win_rate=('pnl_pct', lambda x: (sum(1 for v in x if v > 0) / len(x) * 100) if len(x) > 0 else 0),
        avg_pnl=('pnl_pct', 'mean'),
        avg_r=('pnl_r', 'mean'),
        pf=('pnl_pct', lambda x: -sum(v for v in x if v < 0) / sum(v for v in x if v > 0) if sum(v for v in x if v > 0) > 0 else 0)
    ).reset_index()

    setup_ci = []
    for setup in setup_buckets['setup']:
        data = df[df['setup'] == setup]['pnl_pct'].dropna().tolist()
        ci = _mean_ci(data)
        setup_ci.append(ci)
    setup_buckets['ci'] = setup_ci

    # ============================================================
    # 6. סטטיסטיקה כללית (עם CI)
    # ============================================================
    all_pnl = df['pnl_pct'].dropna().tolist()
    all_mfe = df['outcome_mfe'].dropna().tolist()
    all_mae = df['outcome_mae'].dropna().tolist()
    all_r = df['pnl_r'].dropna().tolist()

    pnl_ci = _mean_ci(all_pnl)
    mfe_ci = _mean_ci(all_mfe)
    mae_ci = _mean_ci(all_mae)
    r_ci = _mean_ci(all_r)

    # ============================================================
    # 7. הדפסה
    # ============================================================
    print("=" * 60)
    print("   LEARNING DASHBOARD (Realized EV — V8.6 with Data Quality)")
    print("=" * 60)

    print(f"\n📊 General Statistics (n={total})")
    print(f"  TP1 Rate: {df['outcome_tp1_hit'].mean()*100:.1f}%")
    print(f"  Avg MFE: {_format_ci(mfe_ci)}")
    print(f"  Avg MAE: {_format_ci(mae_ci)}")
    print(f"  Avg PnL: {_format_ci(pnl_ci)}")
    print(f"  Avg R:    {_format_ci(r_ci)}")
    print(f"  Realized EV: {pnl_ci[0]:.2f}%  |  Net EV (cost 0.2%): {pnl_ci[0]-0.2:.2f}%")
    print(f"  Profit Factor: { -sum(v for v in all_pnl if v < 0) / sum(v for v in all_pnl if v > 0) if sum(v for v in all_pnl if v > 0) > 0 else 0:.2f}")

    print("\n" + "=" * 60)
    print("   DATA QUALITY")
    print("=" * 60)
    print(f"  Total FINAL trades:          {total}")
    print(f"  Ambiguous bars (TP & SL same candle): {ambiguous_bar_count}  ({ambiguous_bar_count/total*100:.1f}%)")
    print(f"  Entry candle ambiguous:      {entry_ambiguous_count}  ({entry_ambiguous_count/total*100:.1f}%)")
    print(f"  Executed manually:            {executed_count}  ({executed_count/total*100:.1f}%)")
    print(f"  Executed but missing timestamp: {executed_but_no_time}  ({executed_but_no_time/total*100:.1f}%)")
    print(f"  No execution data:           {no_execution_data}  ({no_execution_data/total*100:.1f}%)")

    print("\n" + "=" * 60)
    print("   RS Buckets (with 95% CI for Avg PnL)")
    print("=" * 60)
    print(f"{'Bucket':<12} {'n':>4} {'TP1%':>6} {'Win%':>6} {'AvgPnL':>8} {'CI (95%)':>16} {'AvgR':>6} {'PF':>6}")
    print("-" * 70)
    for _, row in rs_buckets.iterrows():
        ci = row['ci']
        ci_str = f"{ci[0]:.2f}%  [{ci[1]:.2f}-{ci[2]:.2f}]" if ci[0] is not None else "N/A"
        print(f"{row['rs_bucket']:<12} {row['n']:>4} {row['tp1_rate']:>6.1f} {row['win_rate']:>6.1f} {row['avg_pnl']:>8.2f} {ci_str:>16} {row['avg_r']:>6.2f} {row['pf']:>6.2f}")

    print("\n" + "=" * 60)
    print("   AI Score Buckets (with 95% CI for Avg PnL)")
    print("=" * 60)
    print(f"{'Bucket':<12} {'n':>4} {'TP1%':>6} {'Win%':>6} {'AvgPnL':>8} {'CI (95%)':>16} {'AvgR':>6} {'PF':>6}")
    print("-" * 70)
    for _, row in ai_buckets.iterrows():
        ci = row['ci']
        ci_str = f"{ci[0]:.2f}%  [{ci[1]:.2f}-{ci[2]:.2f}]" if ci[0] is not None else "N/A"
        print(f"{row['ai_bucket']:<12} {row['n']:>4} {row['tp1_rate']:>6.1f} {row['win_rate']:>6.1f} {row['avg_pnl']:>8.2f} {ci_str:>16} {row['avg_r']:>6.2f} {row['pf']:>6.2f}")

    print("\n" + "=" * 60)
    print("   Setup Type (with 95% CI for Avg PnL)")
    print("=" * 60)
    print(f"{'Setup':<14} {'n':>4} {'TP1%':>6} {'Win%':>6} {'AvgPnL':>8} {'CI (95%)':>16} {'AvgR':>6} {'PF':>6}")
    print("-" * 70)
    for _, row in setup_buckets.iterrows():
        ci = row['ci']
        ci_str = f"{ci[0]:.2f}%  [{ci[1]:.2f}-{ci[2]:.2f}]" if ci[0] is not None else "N/A"
        print(f"{row['setup']:<14} {row['n']:>4} {row['tp1_rate']:>6.1f} {row['win_rate']:>6.1f} {row['avg_pnl']:>8.2f} {ci_str:>16} {row['avg_r']:>6.2f} {row['pf']:>6.2f}")

    # ============================================================
    # 8. מקור העסקאות – ישנות/חדשות (לפי חיתוך 2025-01-01)
    # ============================================================
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    cutoff = pd.Timestamp('2025-01-01', tz='UTC')
    old = df[df['ts'] < cutoff]
    new = df[df['ts'] >= cutoff]
    print("\n" + "=" * 60)
    print("   Source of Trades (cutoff: 2025-01-01)")
    print("=" * 60)
    print(f"  Old trades (pre-2025): {len(old)}  ({len(old)/total*100:.1f}%)")
    print(f"  New trades (2025+):   {len(new)}  ({len(new)/total*100:.1f}%)")
    if len(old) > 0:
        old_ev = old['pnl_pct'].mean()
        old_pf = -old[old['pnl_pct']<0]['pnl_pct'].sum() / old[old['pnl_pct']>0]['pnl_pct'].sum() if old[old['pnl_pct']>0]['pnl_pct'].sum() > 0 else 0
        print(f"    Old EV: {old_ev:.2f}%  |  Old PF: {old_pf:.2f}")
    if len(new) > 0:
        new_ev = new['pnl_pct'].mean()
        new_pf = -new[new['pnl_pct']<0]['pnl_pct'].sum() / new[new['pnl_pct']>0]['pnl_pct'].sum() if new[new['pnl_pct']>0]['pnl_pct'].sum() > 0 else 0
        print(f"    New EV: {new_ev:.2f}%  |  New PF: {new_pf:.2f}")

    # ============================================================
    # 9. השוואת RS>1 – ישנות מול חדשות
    # ============================================================
    print("\n" + "=" * 60)
    print("   RS>1 Performance Split (Old vs New)")
    print("=" * 60)
    rs1_old = old[old['rs_bucket'] == 'RS>1']
    rs1_new = new[new['rs_bucket'] == 'RS>1']
    if len(rs1_old) > 0:
        print(f"  RS>1 old: n={len(rs1_old)}  TP1={rs1_old['outcome_tp1_hit'].mean()*100:.1f}%  EV={rs1_old['pnl_pct'].mean():.2f}%")
    else:
        print("  RS>1 old: no trades")
    if len(rs1_new) > 0:
        print(f"  RS>1 new: n={len(rs1_new)}  TP1={rs1_new['outcome_tp1_hit'].mean()*100:.1f}%  EV={rs1_new['pnl_pct'].mean():.2f}%")
    else:
        print("  RS>1 new: no trades")

    # ============================================================
    # 10. התראת Ambiguous Bars
    # ============================================================
    if ambiguous_bar_count / total > 0.15:
        print("\n" + "!" * 60)
        print("⚠️  WARNING: Ambiguous bars > 15% — consider checking candle resolution / entry logic")
        print("!" * 60)

    if entry_ambiguous_count / total > 0.20:
        print("\n" + "!" * 60)
        print("⚠️  WARNING: Entry candle ambiguous > 20% — consider adjusting entry alignment")
        print("!" * 60)

    conn.close()
    return df


if __name__ == "__main__":
    run_dashboard()
