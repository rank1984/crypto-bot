"""
Read-only diagnostic for shadow.db.
Prints to stdout — no modifications.
"""
import sqlite3
import os

DB = os.getenv("DB_PATH", "data/shadow.db")


def section(title):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def main():
    if not os.path.exists(DB):
        print(f"❌ DB not found: {DB}")
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    section("1. DB STATUS BREAKDOWN")
    print(f"  {'decision':12s} | {'outcome_status':16s} | count")
    print(f"  {'-'*12} | {'-'*16} | -----")
    for r in conn.execute("""
        SELECT decision, outcome_status, COUNT(*) as n
        FROM shadow_trades
        GROUP BY decision, outcome_status
        ORDER BY decision, outcome_status
    """):
        print(f"  {str(r['decision']):12s} | {str(r['outcome_status']):16s} | {r['n']:6d}")

    section("2. TOTAL")
    r = conn.execute("SELECT COUNT(*) as n FROM shadow_trades").fetchone()
    print(f"  Total rows: {r['n']}")

    section("3. LAST 10 FINAL BUY")
    for r in conn.execute("""
        SELECT id, symbol, ts, entry_price, sl,
               ROUND((entry_price-sl)/entry_price*100, 3) as stop_pct,
               pnl_pct, pnl_r, exit_reason, duration_minutes
        FROM shadow_trades
        WHERE outcome_status='FINAL' AND decision='BUY'
        ORDER BY id DESC LIMIT 10
    """):
        print(f"  id={r['id']:5d} {r['symbol']:12s} "
              f"stop={r['stop_pct']:6.2f}% pnl={r['pnl_pct']:7.2f}% "
              f"R={r['pnl_r']} reason={str(r['exit_reason']):15s} "
              f"dur={r['duration_minutes']}m")

    section("4. COMPUSDT id=1187 — stop vs pnl mismatch check")
    r = conn.execute("""
        SELECT id, symbol, entry_price, sl, tp1, tp2,
               ROUND((entry_price-sl)/entry_price*100, 4) as stop_pct,
               pnl_pct, pnl_r, exit_reason, first_outcome_type, trigger_source
        FROM shadow_trades WHERE id=1187
    """).fetchone()
    if r:
        for k in r.keys():
            print(f"  {k:20s} = {r[k]}")
        print()
        if r['stop_pct'] and r['stop_pct'] >= 0.79:
            print(f"  ✅ stop_pct={r['stop_pct']}% ≥ 0.8% — MIN_STOP enforced. Problem in simulator.")
        elif r['stop_pct']:
            print(f"  ⚠️  stop_pct={r['stop_pct']}% < 0.8% — MIN_STOP NOT enforced!")
    else:
        print("  NOT FOUND")

    section("5. STOP ENFORCEMENT (last 50 FINAL BUY)")
    r = conn.execute("""
        SELECT
          COUNT(*) as n,
          SUM(CASE WHEN (entry_price-sl)/entry_price*100 < 0.8 THEN 1 ELSE 0 END) as below_min
        FROM shadow_trades
        WHERE outcome_status='FINAL' AND decision='BUY'
          AND id > (SELECT MAX(id)-50 FROM shadow_trades)
          AND entry_price > 0 AND sl > 0
    """).fetchone()
    print(f"  n={r['n']}, below_0.8%={r['below_min']}")
    if r['below_min'] and r['below_min'] > 0:
        print(f"  ⚠️  {r['below_min']}/{r['n']} trades have stop < 0.8% — NOT enforced")
    else:
        print(f"  ✅ All stops ≥ 0.8%")

    section("6. OPEN BUY (PENDING/ACTIVE)")
    r = conn.execute("""
        SELECT COUNT(*) as n
        FROM shadow_trades
        WHERE decision='BUY' AND outcome_status IN ('PENDING','ACTIVE')
    """).fetchone()
    print(f"  Open BUY: {r['n']}")

    section("7. EXIT REASON DISTRIBUTION (BUY FINAL)")
    for r in conn.execute("""
        SELECT exit_reason, COUNT(*) as n
        FROM shadow_trades
        WHERE outcome_status='FINAL' AND decision='BUY'
        GROUP BY exit_reason
        ORDER BY n DESC
    """):
        print(f"  {str(r['exit_reason']):20s} : {r['n']}")

    section("8. SETUP DISTRIBUTION (BUY FINAL)")
    for r in conn.execute("""
        SELECT setup, COUNT(*) as n,
               ROUND(AVG(pnl_r), 3) as avg_r,
               SUM(CASE WHEN outcome_tp1_hit=1 THEN 1 ELSE 0 END)*100.0/COUNT(*) as tp1_pct
        FROM shadow_trades
        WHERE outcome_status='FINAL' AND decision='BUY'
        GROUP BY setup
    """):
        print(f"  {str(r['setup']):20s} n={r['n']:4d} avgR={r['avg_r']} tp1={r['tp1_pct']:.1f}%")

    section("9. LAST 5 SCANS (BUY rows only)")
    for r in conn.execute("""
        SELECT DATE(ts) as d, COUNT(*) as n
        FROM shadow_trades
        WHERE decision='BUY'
        GROUP BY DATE(ts)
        ORDER BY d DESC
        LIMIT 5
    """):
        print(f"  {r['d']}: {r['n']} BUY signals")

    conn.close()
    print("\n✅ Audit complete\n")


if __name__ == "__main__":
    main()
