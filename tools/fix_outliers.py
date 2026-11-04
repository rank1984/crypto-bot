"""
Fix corrupted trades (price glitches / outliers).
Safe — marks INVALID, doesn't delete.
"""
import sqlite3
import os

DB = os.getenv("DB_PATH", "data/shadow.db")

# Thresholds for suspect trades
MAX_PNL_PCT = 50.0
MAX_ABS_R = 10.0
MAX_DURATION_MIN = 60 * 24 * 7  # 7 days


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("="*70)
    print("  SCANNING FOR OUTLIERS")
    print("="*70)

    outliers = conn.execute("""
        SELECT id, symbol, ts, entry_price, exit_price,
               pnl_pct, pnl_r, duration_minutes, exit_reason
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND (
            ABS(pnl_pct) > ?
            OR ABS(pnl_r) > ?
            OR duration_minutes > ?
          )
    """, (MAX_PNL_PCT, MAX_ABS_R, MAX_DURATION_MIN)).fetchall()

    print(f"\nFound {len(outliers)} outliers:")
    for r in outliers:
        print(f"  id={r['id']} {r['symbol']:12s} "
              f"pnl={r['pnl_pct']:>8.2f}% R={r['pnl_r']:>10.2f} "
              f"dur={r['duration_minutes']}m")
        print(f"    entry={r['entry_price']} exit={r['exit_price']} "
              f"reason={r['exit_reason']}")

    if not outliers:
        print("\n✅ No outliers found")
        return

    # Mark them as INVALID (preserve the row, exclude from stats)
    print(f"\n" + "="*70)
    print(f"  MARKING {len(outliers)} AS INVALID")
    print(f"="*70)

    for r in outliers:
        conn.execute("""
            UPDATE shadow_trades
            SET outcome_status = 'INVALID',
                exit_reason = 'OUTLIER_' || COALESCE(exit_reason, 'UNKNOWN'),
                pnl_pct = NULL,
                pnl_r = NULL,
                mfe_r = NULL,
                mae_r = NULL,
                status = 'INVALID ⚠️'
            WHERE id = ?
        """, (r['id'],))
        print(f"  ✓ id={r['id']} {r['symbol']} marked INVALID")

    conn.commit()

    # VACUUM to reclaim space
    print(f"\n" + "="*70)
    print(f"  VACUUM (reclaim space)")
    print(f"="*70)
    print(f"  Size before: {os.path.getsize(DB) / 1024 / 1024:.1f} MB")
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    print(f"  Size after:  {os.path.getsize(DB) / 1024 / 1024:.1f} MB")
    print(f"\n✅ Done\n")


if __name__ == "__main__":
    main()
