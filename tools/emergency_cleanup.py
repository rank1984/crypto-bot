"""
One-time cleanup: reset non-BUY rows that incorrectly have outcome_status.
Safe — only touches rows where decision != 'BUY'.
"""
import sqlite3
import os

DB = os.getenv("DB_PATH", "data/shadow.db")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("="*70)
    print("  BEFORE")
    print("="*70)
    for r in conn.execute("""
        SELECT decision, outcome_status, COUNT(*) as n
        FROM shadow_trades
        GROUP BY decision, outcome_status
        ORDER BY 1, 2
    """):
        print(f"  {str(r['decision']):12s} | {str(r['outcome_status']):16s} | {r['n']:6d}")

    print("\n" + "="*70)
    print("  CLEANUP: non-BUY with outcome_status != NULL → NULL")
    print("="*70)
    cur = conn.execute("""
        UPDATE shadow_trades
        SET outcome_status = NULL,
            status = '-',
            outcome_checked = 0
        WHERE decision != 'BUY'
          AND outcome_status IS NOT NULL
    """)
    print(f"  Rows updated: {cur.rowcount}")

    conn.commit()

    print("\n" + "="*70)
    print("  AFTER")
    print("="*70)
    for r in conn.execute("""
        SELECT decision, outcome_status, COUNT(*) as n
        FROM shadow_trades
        GROUP BY decision, outcome_status
        ORDER BY 1, 2
    """):
        print(f"  {str(r['decision']):12s} | {str(r['outcome_status']):16s} | {r['n']:6d}")

    conn.close()
    print("\n✅ Cleanup complete\n")


if __name__ == "__main__":
    main()
