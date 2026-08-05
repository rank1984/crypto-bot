"""
CRYPTO-BOT Elite — Expectancy Dashboard (by Setup)
"""
import sqlite3
import os
from utils.logger import get_logger

log = get_logger("expectancy_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def run_dashboard() -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── כל הנתונים הרלוונטיים ────────────────────────────────────────────────
    rows = cur.execute("""
        SELECT 
            setup,
            COUNT(*) AS trades,
            AVG(outcome_tp1_hit) AS tp1_rate,
            AVG(CASE WHEN outcome_tp1_hit = 1 THEN pnl_pct END) AS avg_win,
            AVG(CASE WHEN outcome_tp1_hit = 0 THEN pnl_pct END) AS avg_loss,
            SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) AS gross_profit,
            ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)) AS gross_loss,
            AVG(outcome_mfe) AS avg_mfe,
            AVG(outcome_mae) AS avg_mae,
            AVG(max_drawdown_pct) AS avg_drawdown,
            AVG(duration_minutes) AS avg_duration
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND decision = 'BUY'
          AND setup IS NOT NULL
        GROUP BY setup
        HAVING COUNT(*) >= 5
        ORDER BY tp1_rate DESC
    """).fetchall()

    conn.close()

    if not rows:
        log.info("Expectancy Dashboard: not enough data (need ≥5 trades per setup)")
        return ""

    lines = []
    lines.append("┌─────────────┬────────┬───────┬───────┬─────────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
    lines.append("│ Setup       │ Trades │ TP1%  │  EV%  │ ProfitF │ Avg Win% │ Avg Loss%│ Avg MFE% │ Avg MAE% │ Avg DD%  │")
    lines.append("├─────────────┼────────┼───────┼───────┼─────────┼──────────┼──────────┼──────────┼──────────┼──────────┤")

    for r in rows:
        tp1 = r["tp1_rate"] or 0
        avg_win = r["avg_win"] or 0
        avg_loss = abs(r["avg_loss"] or 0)
        ev = round((tp1 * avg_win) - ((1 - tp1) * avg_loss), 2)

        gross_profit = r["gross_profit"] or 0
        gross_loss = r["gross_loss"] or 0
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

        lines.append(
            f"│ {r['setup']:<11} │ {r['trades']:6d} │ {tp1*100:4.0f}% │ {ev:5.1f}% │ "
            f"{pf:7.2f} │ {avg_win:8.2f}% │ {avg_loss:8.2f}% │ "
            f"{r['avg_mfe'] or 0:8.2f}% │ {r['avg_mae'] or 0:8.2f}% │ "
            f"{r['avg_drawdown'] or 0:8.2f}% │"
        )

    lines.append("└─────────────┴────────┴───────┴───────┴─────────┴──────────┴──────────┴──────────┴──────────┴──────────┘")

    report = "\n".join(lines)
    log.info("Expectancy Dashboard:\n" + report)
    return report
