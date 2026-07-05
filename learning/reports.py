"""
CRYPTO-BOT Elite — Performance Reports

מפיק דוחות מהנתונים שנאספו.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from learning.database import _conn, init_db
from utils.logger import get_logger

log = get_logger(__name__)


def weekly_report() -> str:
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    with _conn() as c:
        # סטטיסטיקות כלליות
        total_scans = c.execute(
            "SELECT COUNT(*) FROM scans WHERE ts >= ?", (cutoff,)
        ).fetchone()[0]

        total_cands = c.execute(
            "SELECT COUNT(*) FROM candidates WHERE ts >= ?", (cutoff,)
        ).fetchone()[0]

        outcomes = c.execute("""
            SELECT COUNT(*) as n,
                   AVG(ret_1h) as avg_ret,
                   SUM(CASE WHEN ret_1h > 0 THEN 1 ELSE 0 END) as wins
            FROM outcomes o
            JOIN candidates ca ON ca.id = o.candidate_id
            WHERE ca.ts >= ? AND o.ret_1h IS NOT NULL
        """, (cutoff,)).fetchone()

        # ביצועים לפי setup
        perf = c.execute("""
            SELECT setup_name, trades, wins, avg_win, avg_loss, expectancy, profit_factor
            FROM performance
            ORDER BY expectancy DESC
        """).fetchall()

        # הכשלונות הנפוצים
        failures = c.execute("""
            SELECT stage, COUNT(*) as cnt
            FROM failures
            WHERE scan_id IN (SELECT scan_id FROM scans WHERE ts >= ?)
            GROUP BY stage ORDER BY cnt DESC LIMIT 5
        """, (cutoff,)).fetchall()

    n_outcomes = outcomes["n"] or 0
    avg_ret    = outcomes["avg_ret"] or 0
    wins       = outcomes["wins"] or 0
    win_rate   = wins / n_outcomes * 100 if n_outcomes > 0 else 0

    lines = [
        "📊 WEEKLY REPORT",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"סריקות:    {total_scans}",
        f"מועמדים:   {total_cands}",
        f"עם outcomes: {n_outcomes}",
        f"Win Rate:  {win_rate:.0f}%",
        f"Avg Return: {avg_ret:+.1f}%",
    ]

    if perf:
        lines += ["", "ביצועים לפי Setup:"]
        for p in perf:
            pf_str = f"PF={p['profit_factor']:.1f}" if p['profit_factor'] else ""
            lines.append(
                f"  {p['setup_name']:<14} "
                f"n={p['trades']} "
                f"WR={p['wins']/p['trades']*100:.0f}% "
                f"EV={p['expectancy']:+.1f}% {pf_str}"
            )

    if failures:
        lines += ["", "סיבות פסילה עיקריות:"]
        for f in failures:
            lines.append(f"  {f['stage']}: {f['cnt']}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(weekly_report())
