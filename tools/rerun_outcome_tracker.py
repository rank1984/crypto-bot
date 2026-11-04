"""
Force re-run outcome_tracker on ALL FINAL BUY trades missing exit_reason.
Safe: only resets BUY FINAL rows with NULL/empty exit_reason.
"""
import sqlite3
import os
import sys

DB = os.getenv("DB_PATH", "data/shadow.db")


def main():
    if not os.path.exists(DB):
        print(f"❌ DB not found: {DB}")
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("="*70)
    print("  BEFORE")
    print("="*70)

    for r in conn.execute("""
        SELECT
          SUM(CASE WHEN exit_reason IS NULL OR exit_reason = '' THEN 1 ELSE 0 END) as missing,
          SUM(CASE WHEN exit_reason IS NOT NULL AND exit_reason != '' THEN 1 ELSE 0 END) as with_reason,
          COUNT(*) as total
        FROM shadow_trades
        WHERE decision='BUY' AND outcome_status='FINAL'
    """):
        print(f"  FINAL BUY total:    {r['total']}")
        print(f"  missing exit_reason: {r['missing']}")
        print(f"  with exit_reason:    {r['with_reason']}")

    # Find trades to reset
    rows = conn.execute("""
        SELECT id, symbol, ts FROM shadow_trades
        WHERE decision='BUY'
          AND outcome_status='FINAL'
          AND (exit_reason IS NULL OR exit_reason = '')
        ORDER BY id DESC
    """).fetchall()

    print(f"\n  → To reset: {len(rows)}")

    if not rows:
        print("\n✅ All FINAL BUY have exit_reason. Nothing to do.")
        conn.close()
        return 0

    # Confirmation prompt (skippable via --yes)
    auto_yes = "--yes" in sys.argv
    if not auto_yes:
        print("\n" + "="*70)
        print("  ABOUT TO RESET {} ROWS TO ACTIVE".format(len(rows)))
        print("="*70)
        print("  The outcome_tracker will then RE-PROCESS them.")
        print("  This may MARK many as INVALID (if data is corrupted).")
        print("  Only BUY+FINAL+NULL-exit_reason rows are touched.")
        print()
        answer = input("  Continue? [y/N]: ").strip().lower()
        if answer != "y":
            print("  Aborted.")
            conn.close()
            return 0

    # Reset in chunks
    ids = [r["id"] for r in rows]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i+500]
        placeholders = ",".join("?" * len(chunk))
        conn.execute(f"""
            UPDATE shadow_trades
            SET outcome_status = 'ACTIVE',
                outcome_checked = 0
            WHERE id IN ({placeholders})
        """, chunk)
        print(f"  reset chunk {i//500 + 1}: {len(chunk)} rows")

    conn.commit()

    print("\n" + "="*70)
    print("  AFTER")
    print("="*70)
    for r in conn.execute("""
        SELECT outcome_status, COUNT(*) as n
        FROM shadow_trades
        WHERE decision='BUY'
        GROUP BY outcome_status
    """):
        print(f"  BUY | {str(r['outcome_status']):12s} | {r['n']}")

    conn.close()

    print("\n" + "="*70)
    print("  ✅ RESET COMPLETE")
    print("="*70)
    print("\n  Next step: run outcome_tracker")
    print("    python -c 'from tools.outcome_tracker import update_outcomes; update_outcomes()'")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())