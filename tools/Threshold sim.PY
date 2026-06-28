"""
CRYPTO-BOT Elite — Threshold Simulator

מסמלץ: אם נשנה סף X → כמה Winners נוספים היינו תופסים?
מה היה ה-False Positive Rate?

משתמש בנתוני Shadow Mode אחרי צבירת מספיק דוגמאות.
"""
import os
import sqlite3
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def simulate_threshold(field: str, thresholds: list[float],
                       winner_pct: float = 20.0) -> str:
    """
    בודק: אם נשנה threshold של 'field', מה קורה?

    field: 'rvol' / 'flow_score' / 'pre_score' / 'final_score'
    """
    with _conn() as c:
        rows = c.execute(f"""
            SELECT {field}, ret_24h
            FROM shadow_signals
            WHERE ret_24h IS NOT NULL AND {field} IS NOT NULL
        """).fetchall()

    if len(rows) < 20:
        return f"צריך לפחות 20 סיגנלים עם forward returns. יש: {len(rows)}"

    all_data = [(float(r[0]), float(r[1])) for r in rows]
    total_winners = sum(1 for _, ret in all_data if ret >= winner_pct)

    lines = [
        f"🔬 THRESHOLD SIMULATOR — {field}",
        f"סה\"כ סיגנלים: {len(all_data)} | Winners ({winner_pct}%+): {total_winners}",
        "",
        f"{'סף':<8} {'נכנסים':<10} {'Winners':<10} {'FP':<10} {'Win Rate':<10}",
        "─" * 50,
    ]

    for thr in thresholds:
        included = [(v, ret) for v, ret in all_data if v >= thr]
        wins     = sum(1 for _, ret in included if ret >= winner_pct)
        fps      = len(included) - wins
        win_rate = wins / len(included) * 100 if included else 0
        lines.append(
            f"{thr:<8.1f} {len(included):<10} {wins:<10} {fps:<10} {win_rate:<10.0f}%"
        )

    return "\n".join(lines)


def full_simulation() -> str:
    """מסמלץ כל הספים המרכזיים."""
    parts = []
    parts.append(simulate_threshold("rvol",        [0.5, 0.8, 1.0, 1.5, 2.0, 3.0]))
    parts.append("")
    parts.append(simulate_threshold("flow_score",  [30, 40, 50, 55, 60, 70]))
    parts.append("")
    parts.append(simulate_threshold("pre_score",   [20, 30, 40, 50, 60]))
    parts.append("")
    parts.append(simulate_threshold("final_score", [50, 55, 60, 65, 70]))
    return "\n".join(parts)


if __name__ == "__main__":
    print(full_simulation())
