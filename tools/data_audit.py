"""
CRYPTO-BOT Elite – Data Audit v2
"""
import sqlite3, os
from datetime import datetime
from utils.logger import get_logger

log = get_logger("data_audit")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def _stat(cur, field):
    """מחזיר (total, null_count, zero_count, valid_count) עבור BUY FINAL."""
    base = "FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY'"
    total = cur.execute(f"SELECT COUNT(*) {base}").fetchone()[0]
    nulls = cur.execute(f"SELECT COUNT(*) {base} AND ({field} IS NULL)").fetchone()[0]
    zeros = cur.execute(f"SELECT COUNT(*) {base} AND ({field} IS NOT NULL AND {field}=0)").fetchone()[0]
    valid = total - nulls - zeros
    return total, nulls, zeros, valid

def run_audit():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    total = cur.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
    final = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE outcome_status='FINAL'").fetchone()[0]
    pending = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE outcome_status='PENDING'").fetchone()[0]
    active = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE outcome_status='ACTIVE'").fetchone()[0]
    buy_final = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE decision='BUY' AND outcome_status='FINAL'").fetchone()[0]

    fields = [
        "pnl_pct", "outcome_mfe", "outcome_mae", "exit_reason",
        "duration_minutes", "funding", "is_compressed", "oi_change",
        "probability", "rs_1h", "flow_score", "market_health", "btc_regime"
    ]

    report = f"""
=== DATA AUDIT ===
Total Trades: {total}
FINAL: {final}
PENDING: {pending}
ACTIVE: {active}
BUY FINAL: {buy_final}

Field Completeness (BUY FINAL):
{'Field':<20s} {'Total':>6s} {'NULL':>6s} {'ZERO':>6s} {'VALID':>6s}
{'-'*44}
"""
    for f in fields:
        t, n, z, v = _stat(cur, f)
        report += f"{f:<20s} {t:6d} {n:6d} {z:6d} {v:6d}\n"

    # Regime & Setup
    regimes = cur.execute("SELECT btc_regime, COUNT(*) FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' GROUP BY btc_regime").fetchall()
    setups = cur.execute("SELECT setup, COUNT(*) FROM shadow_trades WHERE outcome_status='FINAL' AND decision='BUY' GROUP BY setup").fetchall()

    report += "\nRegime Distribution (BUY FINAL):\n"
    for r in regimes:
        report += f"  {r['btc_regime']:<15s}: {r[1]}\n"

    report += "\nSetup Distribution (BUY FINAL):\n"
    for s in setups:
        report += f"  {s['setup']:<15s}: {s[1]}\n"

    conn.close()
    log.info(report)
    return report
