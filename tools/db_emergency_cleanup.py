"""
Emergency DB cleanup. Finds what's taking space and prunes it.
"""
import sqlite3
import os
import sys


DB = os.getenv("DB_PATH", "data/shadow.db")


def fmt_size(b):
    return f"{b/1024/1024:.2f} MB"


def table_sizes(conn):
    """Return [(table, rows, bytes), ...] using dbstat if available."""
    sizes = {}
    try:
        for name, pages in conn.execute(
            "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"
        ):
            sizes[name] = pages
    except sqlite3.OperationalError:
        # dbstat not available — fallback to row counts
        for (tbl,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                sizes[tbl] = n  # count, not bytes
            except Exception:
                pass
    return sizes


def main():
    if not os.path.exists(DB):
        print(f"❌ DB not found: {DB}")
        return 1

    # Check main file + WAL
    size_main = os.path.getsize(DB)
    wal_path = DB + "-wal"
    shm_path = DB + "-shm"
    size_wal = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    size_shm = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0
    total = size_main + size_wal + size_shm

    print("="*70)
    print("  DB EMERGENCY CLEANUP")
    print("="*70)
    print(f"\n[1] File sizes:")
    print(f"  shadow.db:      {fmt_size(size_main)}")
    print(f"  shadow.db-wal:  {fmt_size(size_wal)}  {'← BIG!' if size_wal > 5_000_000 else ''}")
    print(f"  shadow.db-shm:  {fmt_size(size_shm)}")
    print(f"  TOTAL:          {fmt_size(total)}")

    # Open and inspect
    conn = sqlite3.connect(DB)

    # Table sizes
    print(f"\n[2] Table sizes (dbstat):")
    sizes = table_sizes(conn)
    sorted_sizes = sorted(sizes.items(), key=lambda x: x[1], reverse=True)
    for tbl, sz in sorted_sizes[:15]:
        if sz > 1024 * 1024:  # only show tables > 1MB
            print(f"  {tbl:30s} {fmt_size(sz)}")
        elif sz > 1_000_000:  # fallback for row counts
            print(f"  {tbl:30s} {sz} rows")

    # Show row counts for critical tables
    print(f"\n[3] Row counts:")
    for (tbl,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:30s} {n:>8d}")
        except Exception as e:
            print(f"  {tbl:30s} ERROR: {e}")

    # Prune everything aggressive
    print(f"\n[4] Aggressive prune:")

    # shadow_trades: keep only PENDING, ACTIVE, and last 7 days FINAL
    cur = conn.execute("""
        DELETE FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND ts < datetime('now', '-7 days')
    """)
    print(f"  shadow_trades: deleted {cur.rowcount} FINAL > 7 days")

    cur = conn.execute("""
        DELETE FROM shadow_trades
        WHERE outcome_status = 'INVALID'
    """)
    print(f"  shadow_trades: deleted {cur.rowcount} INVALID")

    # All other tables: clear them entirely (they're rebuildable)
    tables_to_clear = [
        'candles', 'candle_cache', 'klines', 'candles_5m', 'candles_1h',
        'scans', 'candidates', 'setups', 'performance',
        'multiday_signals', 'multiday_outcomes',
        'replay_snapshots',
    ]
    for tbl in tables_to_clear:
        try:
            cur = conn.execute(f"DELETE FROM {tbl}")
            if cur.rowcount > 0:
                print(f"  {tbl}: cleared {cur.rowcount} rows")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()

    # WAL checkpoint — separate connection
    print(f"\n[5] WAL checkpoint:")
    conn = sqlite3.connect(DB)
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"  WAL checkpoint result: {result}")
    except Exception as e:
        print(f"  WAL checkpoint error: {e}")
    conn.close()

    # Delete WAL files if still exist
    for f in [wal_path, shm_path]:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"  Deleted {f}")
            except Exception as e:
                print(f"  Could not delete {f}: {e}")

    # VACUUM
    print(f"\n[6] VACUUM:")
    size_before = os.path.getsize(DB)
    print(f"  Before: {fmt_size(size_before)}")

    conn = sqlite3.connect(DB)
    try:
        conn.execute("VACUUM")
        conn.close()
    except Exception as e:
        print(f"  VACUUM error: {e}")
        try:
            conn.close()
        except Exception:
            pass

    size_after = os.path.getsize(DB)
    print(f"  After:  {fmt_size(size_after)}")
    print(f"  Saved:  {fmt_size(size_before - size_after)}")

    # Final check
    print(f"\n[7] Result:")
    final_wal = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    final_total = size_after + final_wal
    print(f"  Final DB size: {fmt_size(final_total)}")

    if final_total > 95 * 1024 * 1024:
        print(f"  ❌ STILL TOO BIG — push will fail")
        return 2
    elif final_total > 80 * 1024 * 1024:
        print(f"  ⚠️  Tight — monitor closely")
        return 0
    else:
        print(f"  ✅ Healthy — push will succeed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
