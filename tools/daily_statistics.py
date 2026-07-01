"""יומי — סטטיסטיקות ביצועים."""
import os, sqlite3
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger
log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/history.db")

def _conn(): return sqlite3.connect(DB_PATH)

def daily_report() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    try:
        with _conn() as c:
            scanned = c.execute(
                "SELECT COUNT(*) FROM signals WHERE ts >= ?", (yesterday,)
            ).fetchone()[0]
            buy = c.execute(
                "SELECT COUNT(*) FROM signals WHERE entry_decision='BUY' AND ts >= ?", (yesterday,)
            ).fetchone()[0]
            trades = c.execute(
                "SELECT COUNT(*), AVG(pnl_pct), SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) "
                "FROM trades WHERE open_ts >= ?", (yesterday,)
            ).fetchone()
    except Exception as e:
        return f"שגיאה: {e}"

    n_trades, avg_pnl, wins = trades
    n_trades = n_trades or 0
    win_rate = (wins or 0) / n_trades * 100 if n_trades > 0 else 0

    return "\n".join([
        f"📊 DAILY STATS — {today}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"נסרקו:       {scanned}",
        f"BUY signals: {buy}",
        f"טריידים:     {n_trades}",
        f"Win Rate:    {win_rate:.0f}%",
        f"Avg PnL:     {avg_pnl or 0:+.1f}%",
    ])

if __name__ == "__main__":
    print(daily_report())
