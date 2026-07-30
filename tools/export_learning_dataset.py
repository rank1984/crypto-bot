"""
CRYPTO-BOT Elite — Learning Dashboard v4 (Net EV, CI, Profit Factor)
"""
import sqlite3, math, os
from utils.logger import get_logger

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def _mean_ci(vals, z=1.96):
    n = len(vals)
    if n < 2: return None, None
    m = sum(vals)/n
    se = math.sqrt(sum((x-m)**2 for x in vals)/(n-1))/math.sqrt(n) if n>1 else 0
    return m, (m - z*se, m + z*se)

def run_dashboard():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # בסיסי
    total = cur.execute("SELECT COUNT(*) as cnt FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY'").fetchone()["cnt"]
    if total < 5:
        log.info(f"Dashboard: need >5 trades, have {total}")
        return ""

    tp1_rate = cur.execute("SELECT AVG(outcome_tp1_hit) FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY'").fetchone()[0]
    mfe_vals = [r[0] for r in cur.execute("SELECT outcome_mfe FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_mfe IS NOT NULL")]
    mae_vals = [r[0] for r in cur.execute("SELECT outcome_mae FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_mae IS NOT NULL")]
    pnl_vals = [r[0] for r in cur.execute("SELECT pnl_pct FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND pnl_pct IS NOT NULL")]

    avg_mfe, ci_mfe = _mean_ci(mfe_vals)
    avg_mae, ci_mae = _mean_ci(mae_vals)
    avg_pnl, ci_pnl = _mean_ci(pnl_vals)

    # Net EV (with cost model)
    COST = 0.2  # slippage+commission 0.2%
    gross_ev = tp1_rate * (avg_mfe or 0) - (1 - tp1_rate) * abs(avg_mae or 0)
    net_ev = gross_ev - COST

    # Profit Factor
    wins = [x for x in pnl_vals if x > 0]
    losses = [abs(x) for x in pnl_vals if x < 0]
    pf = sum(wins)/sum(losses) if sum(losses) > 0 else float('inf')

    # RS ranges
    rs_ranges = cur.execute("""
        SELECT CASE WHEN rs_1h<0 THEN '<0' WHEN rs_1h<0.5 THEN '0-0.5' WHEN rs_1h<1 THEN '0.5-1' ELSE '>1' END as rng,
               COUNT(*), AVG(outcome_tp1_hit)
        FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY'
        GROUP BY rng ORDER BY MIN(rs_1h)
    """).fetchall()

    lines = ["=" * 45, "   LEARNING DASHBOARD (Net EV)", "=" * 45]
    lines.append(f"Trades: {total}  TP1 Rate: {tp1_rate*100:.1f}%")
    if avg_mfe: lines.append(f"Avg MFE: {avg_mfe:.1f}%  (95%CI {ci_mfe[0]:.1f}-{ci_mfe[1]:.1f})")
    if avg_mae: lines.append(f"Avg MAE: {avg_mae:.1f}%  (95%CI {ci_mae[0]:.1f}-{ci_mae[1]:.1f})")
    if avg_pnl: lines.append(f"Avg PnL: {avg_pnl:.2f}%  (95%CI {ci_pnl[0]:.2f}-{ci_pnl[1]:.2f})")
    lines.append(f"Gross EV: {gross_ev:.2f}%  |  Net EV (cost {COST}%): {net_ev:.2f}%")
    lines.append(f"Profit Factor: {pf:.2f}")
    lines.append("RS ranges:")
    for r in rs_ranges:
        lines.append(f"  {r[0]:8s}: n={r[1]:3d}  TP1={r[2]*100:.0f}%")
    lines.append("=" * 45)

    report = "\n".join(lines)
    log.info(report)
    return report
