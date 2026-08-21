import sqlite3, math, os
from utils.logger import get_logger

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

BASE_WHERE = "outcome_status='FINAL' AND decision='BUY' AND outcome_checked=1"


def _mean_ci(vals, z=1.96):
    n = len(vals)
    if n < 2:
        return None, None
    m = sum(vals) / n
    se = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1)) / math.sqrt(n) if n > 1 else 0
    return m, (m - z * se, m + z * se)


def _segment_stats(cur, group_col, extra_where="", order_by=None):
    """
    מחזיר per-segment: n, TP1 rate, Win rate, Avg PnL, Avg R, EV, Profit Factor
    """
    where = f"{BASE_WHERE} AND pnl_pct IS NOT NULL"
    if extra_where:
        where += f" AND {extra_where}"

    rows = cur.execute(f"""
        SELECT {group_col} as seg, pnl_pct, pnl_r, outcome_tp1_hit
        FROM shadow_trades
        WHERE {where}
    """).fetchall()

    groups = {}
    for r in rows:
        seg = r["seg"] if r["seg"] is not None else "UNKNOWN"
        groups.setdefault(seg, []).append(r)

    results = []
    for seg, items in groups.items():
        n = len(items)
        pnl_vals = [i["pnl_pct"] for i in items]
        r_vals = [i["pnl_r"] for i in items if i["pnl_r"] is not None]
        tp1_rate = sum(i["outcome_tp1_hit"] for i in items) / n if n else 0
        win_rate = sum(1 for p in pnl_vals if p > 0) / n if n else 0
        avg_pnl = sum(pnl_vals) / n if n else 0
        avg_r = sum(r_vals) / len(r_vals) if r_vals else None

        wins = [p for p in pnl_vals if p > 0]
        losses = [abs(p) for p in pnl_vals if p < 0]
        pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else None

        results.append({
            "segment": seg, "n": n, "tp1_rate": tp1_rate, "win_rate": win_rate,
            "avg_pnl": avg_pnl, "avg_r": avg_r, "pf": pf,
        })

    if order_by:
        results.sort(key=lambda x: order_by(x["segment"]))
    return results


def _fmt_segment_line(label, s):
    pf_str = f"{s['pf']:.2f}" if s["pf"] is not None else "N/A"
    r_str = f"{s['avg_r']:.2f}R" if s["avg_r"] is not None else "n/a"
    return (f"  {label:12s}: n={s['n']:3d}  TP1={s['tp1_rate']*100:5.1f}%  "
            f"Win={s['win_rate']*100:5.1f}%  AvgPnL={s['avg_pnl']:6.2f}%  "
            f"AvgR={r_str:>7s}  PF={pf_str}")


def run_dashboard():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    total = cur.execute(f"SELECT COUNT(*) as cnt FROM shadow_trades WHERE {BASE_WHERE}").fetchone()["cnt"]

    if total < 5:
        log.info(f"Dashboard: need >5 checked FINAL trades, have {total}")
        return ""

    tp1_rate = cur.execute(f"SELECT AVG(outcome_tp1_hit) FROM shadow_trades WHERE {BASE_WHERE}").fetchone()[0]

    mfe_vals = [r[0] for r in cur.execute(f"SELECT outcome_mfe FROM shadow_trades WHERE {BASE_WHERE} AND outcome_mfe IS NOT NULL")]
    mae_vals = [r[0] for r in cur.execute(f"SELECT outcome_mae FROM shadow_trades WHERE {BASE_WHERE} AND outcome_mae IS NOT NULL")]
    pnl_vals = [r[0] for r in cur.execute(f"SELECT pnl_pct FROM shadow_trades WHERE {BASE_WHERE} AND pnl_pct IS NOT NULL")]
    r_vals = [r[0] for r in cur.execute(f"SELECT pnl_r FROM shadow_trades WHERE {BASE_WHERE} AND pnl_r IS NOT NULL")]

    avg_mfe, ci_mfe = _mean_ci(mfe_vals)
    avg_mae, ci_mae = _mean_ci(mae_vals)
    avg_pnl, ci_pnl = _mean_ci(pnl_vals)
    avg_r = sum(r_vals) / len(r_vals) if r_vals else None

    COST = 0.2
    realized_ev = avg_pnl or 0.0
    net_ev = realized_ev - COST

    wins = [x for x in pnl_vals if x > 0]
    losses = [abs(x) for x in pnl_vals if x < 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else None

    # 🆕 Ambiguous bar warning
    ambiguous_count = cur.execute(f"SELECT COUNT(*) FROM shadow_trades WHERE {BASE_WHERE} AND ambiguous_bar=1").fetchone()[0]

    lines = ["=" * 60, "   LEARNING DASHBOARD (Realized EV — Simulated Partial Exits)", "=" * 60]
    lines.append(f"Trades: {total}  TP1 Rate: {tp1_rate*100:.1f}%")
    if avg_mfe is not None: lines.append(f"Avg MFE: {avg_mfe:.1f}%  (95%CI {ci_mfe[0]:.1f}-{ci_mfe[1]:.1f})")
    if avg_mae is not None: lines.append(f"Avg MAE: {avg_mae:.1f}%  (95%CI {ci_mae[0]:.1f}-{ci_mae[1]:.1f})")
    if avg_pnl is not None: lines.append(f"Avg PnL: {avg_pnl:.2f}%  (95%CI {ci_pnl[0]:.2f}-{ci_pnl[1]:.2f})")
    if avg_r is not None: lines.append(f"Avg R: {avg_r:.2f}R")
    lines.append(f"Realized EV: {realized_ev:.2f}%  |  Net EV (cost {COST}%): {net_ev:.2f}%")
    lines.append(f"Profit Factor: {pf:.2f}" if pf is not None else "Profit Factor: N/A")
    if ambiguous_count:
        lines.append(f"⚠️  Ambiguous bars (TP&SL same candle, SL assumed first): {ambiguous_count}/{total}")

    # 🆕 RS Bucket — עכשיו עם EV/PF/Win מלא, לא רק TP1
    rs_order = {"RS<0": 0, "RS_0_0.5": 1, "RS_0.5_1": 2, "RS>1": 3}
    lines.append("\nRS Buckets:")
    for s in _segment_stats(cur, "rs_bucket", order_by=lambda x: rs_order.get(x, 99)):
        lines.append(_fmt_segment_line(s["segment"], s))

    # 🆕 AI Bucket
    ai_order = {"AI_0_20": 0, "AI_20_40": 1, "AI_40_60": 2, "AI_60_80": 3, "AI_80_100": 4}
    lines.append("\nAI Score Buckets:")
    for s in _segment_stats(cur, "ai_bucket", order_by=lambda x: ai_order.get(x, 99)):
        lines.append(_fmt_segment_line(s["segment"], s))

    # 🆕 Setup
    lines.append("\nSetup Type:")
    for s in _segment_stats(cur, "setup", order_by=lambda x: x):
        lines.append(_fmt_segment_line(s["segment"], s))

    # 🆕 Model EV vs Human EV (executed בפועל בלבד)
    executed_pnl = [r[0] for r in cur.execute(
        f"SELECT pnl_pct FROM shadow_trades WHERE {BASE_WHERE} AND pnl_pct IS NOT NULL AND was_executed=1"
    )]
    slippage_vals = [r[0] for r in cur.execute(
        f"SELECT entry_slippage_pct FROM shadow_trades WHERE {BASE_WHERE} AND was_executed=1 AND entry_slippage_pct IS NOT NULL"
    )]
    delay_vals = [r[0] for r in cur.execute(
        f"SELECT execution_delay_sec FROM shadow_trades WHERE {BASE_WHERE} AND was_executed=1 AND execution_delay_sec IS NOT NULL"
    )]
    skipped = cur.execute(f"SELECT COUNT(*) FROM shadow_trades WHERE {BASE_WHERE} AND was_executed=0").fetchone()[0]

    lines.append("\nModel EV vs Human Execution:")
    lines.append(f"  Model EV (all signals):      {realized_ev:.2f}%  (n={total})")
    if executed_pnl:
        human_ev = sum(executed_pnl) / len(executed_pnl)
        lines.append(f"  Human EV (executed only):    {human_ev:.2f}%  (n={len(executed_pnl)})")
    else:
        lines.append("  Human EV: no executed trades tracked yet (waiting on /buy /done data)")
    if slippage_vals:
        avg_slip = sum(slippage_vals) / len(slippage_vals)
        lines.append(f"  Avg Entry Slippage:           {avg_slip:+.3f}%")
    if delay_vals:
        avg_delay = sum(delay_vals) / len(delay_vals)
        lines.append(f"  Avg Execution Delay:          {avg_delay:.0f} sec")
    lines.append(f"  Skipped signals:              {skipped}/{total}")

    lines.append("=" * 60)

    report = "\n".join(lines)
    log.info(report)
    return report
