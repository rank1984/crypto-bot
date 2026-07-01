"""עוקב אחרי ציון מטבע לאורך זמן."""
import os, sqlite3
from datetime import datetime, timezone
from utils.logger import get_logger
log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/history.db")

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_score_history():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS score_history (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT NOT NULL,
                symbol  TEXT NOT NULL,
                price   REAL,
                score   REAL,
                flow    REAL,
                pre     REAL,
                rating  TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sh_symbol ON score_history(symbol)")

def save_score(coin: dict, rating: str):
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO score_history (ts,symbol,price,score,flow,pre,rating) VALUES (?,?,?,?,?,?,?)",
            (ts, coin["symbol"], coin.get("price"), coin.get("final_score"),
             coin.get("flow_score"), coin.get("pre_score"), rating)
        )

def get_score_trend(symbol: str, hours: int = 12) -> str:
    """מציג איך הציון של מטבע התפתח בשעות האחרונות."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute("""
            SELECT ts, score, flow, pre, rating FROM score_history
            WHERE symbol=? AND ts>=? ORDER BY ts
        """, (symbol, cutoff)).fetchall()

    if not rows:
        return f"אין היסטוריה ל-{symbol}"

    lines = [f"📈 {symbol} — {hours}h trend"]
    for r in rows:
        time_str = r["ts"][11:16]
        lines.append(
            f"  {time_str}  score={r['score']:.0f}  "
            f"flow={r['flow']:.0f}  pre={r['pre']:.0f}  [{r['rating']}]"
        )
    last, first = float(rows[-1]["score"]), float(rows[0]["score"])
    arrow = "⬆️" if last > first else "⬇️" if last < first else "➡️"
    lines.append(f"  {arrow} {first:.0f} → {last:.0f}")
    return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    args = parser.parse_args()
    print(get_score_trend(args.symbol))
