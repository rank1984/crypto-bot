"""
CRYPTO-BOT Elite — Learning Dashboard v5 (Net EV, CI, Profit Factor)
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

    total = cur.execute("SELECT COUNT(*) as cnt FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1").fetchone()["cnt"]
    if total < 5:
        log.info(f"Dashboard: need >5 checked FINAL trades, have {total}")
        return ""

    tp1_rate = cur.execute("SELECT AVG(outcome_tp1_hit) FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1").fetchone()[0]

    mfe_vals = [r[0] for r in cur.execute("SELECT outcome_mfe FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1 AND outcome_mfe IS NOT NULL")]
    mae_vals = [r[0] for r in cur.execute("SELECT outcome_mae FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1 AND outcome_mae IS NOT NULL")]
    pnl_vals = [r[0] for r in cur.execute("SELECT pnl_pct FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1 AND pnl_pct IS NOT NULL")]

    avg_mfe, ci_mfe = _mean_ci(mfe_vals)
    avg_mae, ci_mae = _mean_ci(mae_vals)
    avg_pnl, ci_pnl = _mean_ci(pnl_vals)

    # Net EV
    COST = 0.2
    gross_ev = avg_pnl or 0          # EV אמיתי מבוסס PnL
    net_ev = gross_ev - COST

    # Profit Factor
    wins = [x for x in pnl_vals if x > 0]
    losses = [abs(x) for x in pnl_vals if x < 0]

    if not wins and not losses:
        pf = None
    elif sum(losses) == 0:
        pf = None
    else:
        pf = sum(wins) / sum(losses)

    # RS ranges
    rs_ranges = cur.execute("""
        SELECT CASE WHEN rs_1h<0 THEN '<0' WHEN rs_1h<0.5 THEN '0-0.5' WHEN rs_1h<1 THEN '0.5-1' ELSE '>1' END as rng,
               COUNT(*), AVG(outcome_tp1_hit)
        FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1
        GROUP BY rng ORDER BY MIN(rs_1h)
    """).fetchall()

    lines = ["=" * 45, "   LEARNING DASHBOARD (Net EV)", "=" * 45]
    lines.append(f"Trades: {total}  TP1 Rate: {tp1_rate*100:.1f}%")
    if avg_mfe is not None: lines.append(f"Avg MFE: {avg_mfe:.1f}%  (95%CI {ci_mfe[0]:.1f}-{ci_mfe[1]:.1f})")
    if avg_mae is not None: lines.append(f"Avg MAE: {avg_mae:.1f}%  (95%CI {ci_mae[0]:.1f}-{ci_mae[1]:.1f})")
    if avg_pnl is not None: lines.append(f"Avg PnL: {avg_pnl:.2f}%  (95%CI {ci_pnl[0]:.2f}-{ci_pnl[1]:.2f})")
    lines.append(f"Gross EV: {gross_ev:.2f}%  |  Net EV (cost {COST}%): {net_ev:.2f}%")
    if pf is None:
        lines.append("Profit Factor: N/A")
    else:
        lines.append(f"Profit Factor: {pf:.2f}")

    lines.append("RS ranges:")
    for r in rs_ranges:
        lines.append(f"  {r[0]:8s}: n={r[1]:3d}  TP1={r[2]*100:.0f}%")
    lines.append("=" * 45)

    report = "\n".join(lines)
    log.info(report)
    return report