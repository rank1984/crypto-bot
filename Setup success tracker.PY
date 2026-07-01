"""
CRYPTO-BOT Elite — Setup Success Tracker

מנתח אילו קומבינציות של תנאים (Setup Types) באמת מצליחות.

לדוגמה:
    Compression + OI       Win Rate 82%
    Whale + RS              Win Rate 76%
    Volume Explosion בלבד  Win Rate 61%
    Catalyst בלבד            Win Rate 45%

משתמש בנתוני trades מ-storage/trade_logger.py.
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger(__name__)
DB_PATH = os.getenv("DB_PATH", "data/history.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def _setup_label(row: dict) -> str:
    """בונה תווית setup מתוך תנאים שהיו מסומנים ב-True."""
    parts = []
    if row.get("had_compression"):  parts.append("Compression")
    if row.get("had_oi"):           parts.append("OI")
    if row.get("had_whale"):        parts.append("Whale")
    if row.get("had_rs"):           parts.append("RS")
    if row.get("had_catalyst"):     parts.append("Catalyst")
    if row.get("had_vol_explosion"):parts.append("VolExplosion")
    return "+".join(parts) if parts else "Other"


def analyze_setups() -> str:
    """
    מנתח win rate לפי קומבינציית setup.
    דורש שדות had_compression וכו' בטבלת trades (extension עתידי).
    כרגע — fallback פשוט לפי setup_type הקיים.
    """
    try:
        with _conn() as c:
            rows = c.execute("""
                SELECT setup_type, COUNT(*) as cnt,
                       AVG(pnl_pct) as avg_pnl,
                       SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                       AVG(max_runup_pct) as avg_runup
                FROM trades
                WHERE close_ts IS NOT NULL
                GROUP BY setup_type
                ORDER BY avg_pnl DESC
            """).fetchall()
    except Exception as e:
        return f"שגיאה: {e}"

    if not rows:
        return "אין עדיין טריידים סגורים לניתוח."

    lines = ["📊 SETUP SUCCESS TRACKER", "━━━━━━━━━━━━━━━━━━━━━━"]
    for setup, cnt, avg_pnl, wins, avg_runup in rows:
        win_rate = wins / cnt * 100 if cnt > 0 else 0
        setup_name = setup or "Unknown"
        lines.append(
            f"\n{setup_name}\n"
            f"  n={cnt}  Win Rate: {win_rate:.0f}%\n"
            f"  Avg PnL: {avg_pnl:+.1f}%  Avg MFE: {avg_runup:+.1f}%"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print(analyze_setups())
