"""
Inspect Multi-Day signals for the STOP_HIT pattern.
Read-only.
"""
import sqlite3
import os

DB = os.getenv("DB_PATH", "data/shadow.db")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Find multiday table
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%multiday%'"
    )]
    print(f"Multiday tables found: {tables}\n")

    for tbl in tables:
        print(f"{'='*70}\n  {tbl}\n{'='*70}")
        r = conn.execute(f"SELECT COUNT(*) as n FROM {tbl}").fetchone()
        print(f"  Total rows: {r['n']}")

    # Show sample STOP_HIT if table exists
    if 'multiday_signals' in tables:
        print(f"\n{'='*70}\n  SAMPLE 5 STOP_HIT\n{'='*70}")
        try:
            rows = conn.execute("""
                SELECT * FROM multiday_signals
                WHERE outcome_24h = 'STOP_HIT'
                LIMIT 5
            """).fetchall()
            for r in rows:
                for k in r.keys():
                    print(f"    {k:25s} = {r[k]}")
                print()
        except Exception as e:
            print(f"  Error: {e}")

        # Distribution
        print(f"{'='*70}\n  OUTCOME DISTRIBUTION\n{'='*70}")
        try:
            for r in conn.execute("""
                SELECT outcome_24h, COUNT(*) as n
                FROM multiday_signals
                GROUP BY outcome_24h
                ORDER BY n DESC
            """):
                print(f"  {str(r['outcome_24h']):20s}: {r['n']}")
        except Exception as e:
            print(f"  Error: {e}")

    conn.close()


if __name__ == "__main__":
    main()
