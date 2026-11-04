"""
Fix corrupted trades (price glitches / outliers).
Safe — marks INVALID, doesn't delete.
"""
import sqlite3
import os

DB = os.getenv("DB_PATH", "data/shadow.db")

# Thresholds
MAX_PNL_PCT = 50.0
MAX_ABS_R = 10.0
MAX_DURATION_MIN = 60 * 24 * 7  # 7 days


def _fmt(val, fmt):
    """Safely format — None → 'None'."""
    if val is None:
        return "None"
    try:
        return fmt.format(val)
    except (TypeError, ValueError):
        return str(val)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("="*70)
    print("  SCANNING FOR OUTLIERS")
    print("="*70)

    # Query 1: numeric outliers
    numeric = conn.execute("""
        SELECT id, symbol, ts, entry_price, exit_price,
               pnl_pct, pnl_r, duration_minutes, exit_reason,
               outcome_tp1_hit, outcome_sl_hit
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND (
            (pnl_pct IS NOT NULL AND ABS(pnl_pct) > ?)
            OR (pnl_r IS NOT NULL AND ABS(pnl_r) > ?)
            OR (duration_minutes IS NOT NULL AND duration_minutes > ?)
          )
    """, (MAX_PNL_PCT, MAX_ABS_R, MAX_DURATION_MIN)).fetchall()

    # Query 2: dirty FINAL — exit_price=0 AND no exit_reason (corrupted)
    dirty = conn.execute("""
        SELECT id, symbol, ts, entry_price, exit_price,
               pnl_pct, pnl_r, duration_minutes, exit_reason,
               outcome_tp1_hit, outcome_sl_hit
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND (exit_price IS NULL OR exit_price = 0)
          AND (exit_reason IS NULL OR exit_reason = '')
          AND pnl_pct IS NOT NULL
          AND ABS(pnl_pct) > 5
    """).fetchall()

    # Merge unique by id
    seen = set()
    outliers = []
    for r in numeric + dirty:
        if r['id'] not in seen:
            seen.add(r['id'])
            outliers.append(r)

    print(f"\nFound {len(outliers)} outliers:")
    print()
    for r in outliers:
        print(f"  id={r['id']} {r['symbol']:12s} "
              f"pnl={_fmt(r['pnl_pct'], '{:>8.2f}'):>10s}% "
              f"R={_fmt(r['pnl_r'], '{:>8.2f}'):>10s} "
              f"dur={_fmt(r['duration_minutes'], '{:d}'):>8s}m")
        print(f"    entry={_fmt(r['entry_price'], '{:.6f}')} "
              f"exit={_fmt(r['exit_price'], '{:.6f}')} "
              f"reason={_fmt(r['exit_reason'], '{}')}")

    if not outliers:
        print("\n✅ No outliers found")
        return

    # Mark INVALID
    print(f"\n" + "="*70)
    print(f"  MARKING {len(outliers)} AS INVALID")
    print(f"="*70)

    for r in outliers:
        conn.execute("""
            UPDATE shadow_trades
            SET outcome_status = 'INVALID',
                exit_reason = 'OUTLIER_' || COALESCE(exit_reason, 'CORRUPTED'),
                pnl_pct = NULL,
                pnl_r = NULL,
                mfe_r = NULL,
                mae_r = NULL,
                status = 'INVALID ⚠️'
            WHERE id = ?
        """, (r['id'],))
        print(f"  ✓ id={r['id']} {r['symbol']} marked INVALID")

    conn.commit()

    # VACUUM
    print(f"\n" + "="*70)
    print(f"  VACUUM (reclaim space)")
    print(f"="*70)
    size_before = os.path.getsize(DB) / 1024 / 1024
    print(f"  Size before: {size_before:.1f} MB")
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    size_after = os.path.getsize(DB) / 1024 / 1024
    print(f"  Size after:  {size_after:.1f} MB")
    print(f"\n✅ Done\n")


if __name__ == "__main__":
    main()
