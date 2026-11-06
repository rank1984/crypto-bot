"""
Emergency DB prune. Keeps last 30 days only.
Run manually when DB > 80MB.
"""
import sqlite3
import os
import sys

DB = os.getenv("DB_PATH", "data/shadow.db")


def main():
    if not os.path.exists(DB):
        print(f"❌ DB not found: {DB}")
        return 1

    size_before = os.path.getsize(DB) / 1024 / 1024
    print(f"="*60)
    print(f"  DB PRUNE — {size_before:.1f} MB")
    print(f"="*60)

    conn = sqlite3.connect(DB)

    # 1. List tables + row counts
    print("\n[1] Table sizes:")
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    for (tbl,) in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:30s}: {n:>8d} rows")
        except Exception as e:
            print(f"  {tbl:30s}: ERROR {e}")

    # 2. Prune shadow_trades: keep 30 days
    print("\n[2] Pruning shadow_trades (keep last 30 days):")
    cur = conn.execute("""
        DELETE FROM shadow_trades
        WHERE ts < datetime('now', '-30 days')
          AND outcome_status != 'PENDING'
          AND outcome_status != 'ACTIVE'
    """)
    print(f"  Deleted {cur.rowcount} old FINAL/INVALID rows")

    # 3. Prune multiday_signals: keep last 7 days only
    print("\n[3] Pruning multiday_signals (keep last 7 days):")
    try:
        cur = conn.execute("""
            DELETE FROM multiday_signals
            WHERE ts < datetime('now', '-7 days')
        """)
        print(f"  Deleted {cur.rowcount} old multiday rows")
    except Exception as e:
        print(f"  Multiday table not found or error: {e}")

    # 4. Drop candle cache if exists (it's rebuildable)
    print("\n[4] Checking for candle cache table:")
    candle_tables = [
        'candles', 'candle_cache', 'klines',
        'candles_5m', 'candles_1h'
    ]
    for tbl in candle_tables:
        try:
            cur = conn.execute(f"DELETE FROM {tbl}")
            print(f"  Cleared {tbl}: {cur.rowcount} rows")
        except sqlite3.OperationalError:
            pass

    conn.commit()

    # 5. WAL checkpoint + VACUUM
    print("\n[5] WAL checkpoint + VACUUM:")
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        print(f"  wal_checkpoint: {e}")
    conn.execute("VACUUM")
    conn.execute("PRAGMA optimize")
    conn.commit()
    conn.close()

    size_after = os.path.getsize(DB) / 1024 / 1024
    print(f"\n{'='*60}")
    print(f"  RESULT: {size_before:.1f} MB → {size_after:.1f} MB")
    print(f"  Savings: {size_before - size_after:.1f} MB")
    print(f"{'='*60}")

    if size_after > 95:
        print("⚠️  Still > 95MB — will fail next push")
        return 2
    elif size_after > 80:
        print("⚠️  > 80MB — tight, monitor closely")
        return 0
    else:
        print("✅ Healthy size")
        return 0


if __name__ == "__main__":
    sys.exit(main())