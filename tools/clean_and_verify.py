"""
CRYPTO-BOT Elite — Clean & Verify
ניקוי כפילויות + בדיקת תקינות נתונים + דוח סטטיסטי.
שימוש:
    PYTHONPATH=. python tools/clean_and_verify.py            # רק ניתוח
    PYTHONPATH=. python tools/clean_and_verify.py --clean    # ניתוח + ניקוי
"""
import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def count_duplicates(conn):
    """מציאת כפילויות: אותו symbol+entry_price+ts מופיע יותר מפעם אחת."""
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT symbol, entry_price, ts, COUNT(*) as cnt
        FROM shadow_trades
        GROUP BY symbol, entry_price, ts
        HAVING COUNT(*) > 1
    """).fetchall()
    total_dup = sum(r["cnt"] - 1 for r in rows)
    return rows, total_dup

def clean_duplicates(conn):
    """מחיקת כל הכפילויות תוך שמירת השורה הראשונה (הכי מוקדמת) מכל קבוצה."""
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM shadow_trades
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM shadow_trades
            GROUP BY symbol, entry_price, ts
        )
    """)
    conn.commit()
    return cur.rowcount

def data_quality(conn):
    """בודק כמה עסקאות FINAL עם שדות חיוניים."""
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM shadow_trades WHERE decision='BUY' AND outcome_status='FINAL' AND outcome_checked=1").fetchone()[0]
    if total == 0:
        return {"total_final": 0, "with_pnl": 0, "with_mfe": 0, "with_mae": 0, "with_ai": 0, "with_prob": 0, "with_compression": 0, "with_funding": 0}

    def count_nonzero(field):
        return cur.execute(f"SELECT COUNT(*) FROM shadow_trades WHERE decision='BUY' AND outcome_status='FINAL' AND outcome_checked=1 AND {field} IS NOT NULL AND {field} != 0").fetchone()[0]

    return {
        "total_final": total,
        "with_pnl": count_nonzero("pnl_pct"),
        "with_mfe": count_nonzero("outcome_mfe"),
        "with_mae": count_nonzero("outcome_mae"),
        "with_ai": count_nonzero("ai_score"),
        "with_prob": count_nonzero("probability"),
        "with_compression": count_nonzero("is_compressed"),
        "with_funding": count_nonzero("funding"),
    }

def core_stats(conn):
    """סטטיסטיקות בסיסיות על הנתונים הנקיים."""
    cur = conn.cursor()
    stats = cur.execute("""
        SELECT
            COUNT(*) AS trades,
            AVG(pnl_pct) AS avg_pnl,
            AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END) AS avg_win,
            AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END) AS avg_loss,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate,
            SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) /
                NULLIF(ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)), 0) AS profit_factor
        FROM shadow_trades
        WHERE decision = 'BUY'
          AND outcome_status = 'FINAL'
          AND outcome_checked = 1
          AND pnl_pct IS NOT NULL
    """).fetchone()
    return dict(stats)

def rs_breakdown(conn):
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT
            CASE WHEN rs_1h < 0 THEN '<0'
                 WHEN rs_1h < 0.5 THEN '0-0.5'
                 WHEN rs_1h < 1 THEN '0.5-1'
                 ELSE '>1' END AS rs_bin,
            COUNT(*) AS trades,
            AVG(pnl_pct) AS avg_pnl,
            AVG(outcome_tp1_hit) AS tp1_rate
        FROM shadow_trades
        WHERE decision = 'BUY'
          AND outcome_status = 'FINAL'
          AND outcome_checked = 1
          AND pnl_pct IS NOT NULL
        GROUP BY rs_bin
        ORDER BY MIN(rs_1h)
    """).fetchall()
    return [dict(r) for r in rows]

def main():
    clean = "--clean" in sys.argv

    if not os.path.exists(DB_PATH):
        print(f"❌ DB not found: {DB_PATH}")
        return

    # גיבוי קל לפני ניקוי
    if clean:
        import shutil
        backup = DB_PATH + f".bak_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(DB_PATH, backup)
        print(f"📦 Backup created: {backup}")

    conn = get_conn()

    # 1. כפילויות
    dup_groups, dup_count = count_duplicates(conn)
    print(f"\n🔍 Duplicates: {dup_groups.__len__()} groups, {dup_count} extra rows")

    if clean and dup_count > 0:
        deleted = clean_duplicates(conn)
        print(f"🧹 Deleted {deleted} duplicate rows")
        dup_groups, dup_count = count_duplicates(conn)
        print(f"🔁 After clean: {dup_groups.__len__()} groups, {dup_count} extra rows")

    # 2. Data quality
    dq = data_quality(conn)
    print("\n📊 Data Quality (BUY FINAL, checked):")
    print(f"  Total FINAL: {dq['total_final']}")
    print(f"  With PnL: {dq['with_pnl']}")
    print(f"  With MFE: {dq['with_mfe']}")
    print(f"  With MAE: {dq['with_mae']}")
    print(f"  With AI Score: {dq['with_ai']}")
    print(f"  With Probability: {dq['with_prob']}")
    print(f"  With Compression: {dq['with_compression']}")
    print(f"  With Funding: {dq['with_funding']}")

    # 3. Core stats
    stats = core_stats(conn)
    print("\n📈 Core Stats (clean, BUY FINAL, PnL not null):")
    for k, v in stats.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    # 4. RS breakdown
    rs = rs_breakdown(conn)
    print("\n📈 RS Breakdown:")
    for row in rs:
        print(f"  {row['rs_bin']:8s}  trades={row['trades']:4d}  avg_pnl={row['avg_pnl']:+.2f}%  tp1={row['tp1_rate']*100:.0f}%")

    conn.close()

if __name__ == "__main__":
    main()
