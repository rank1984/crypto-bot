"""
CRYPTO-BOT Elite — Shadow Mode

הבוט רץ בשקט:
- לא שולח התראות
- שומר כל סיגנל עם כל המשתנים
- בודק מה קרה אחר כך (forward returns)
- אחרי 2-4 שבועות: נתונים אמיתיים לכיוון

Schema:
    shadow_signals:
        ts, symbol, flow, pre, rvol, oi_change,
        is_compressed, rs_1h, whale, final_score,
        would_be_signal (BUY/PREPARE/WATCH/IGNORE),
        price_at_signal,
        ret_30m, ret_1h, ret_4h, ret_24h  ← מתמלא בריצות הבאות
"""
import os
import sqlite3
import requests
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


# ─── DB ──────────────────────────────────────────────────────────────────────

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_shadow_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS shadow_signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                price           REAL,
                final_score     REAL,
                flow_score      REAL,
                pre_score       REAL,
                rvol            REAL,
                oi_change       REAL,
                is_compressed   INTEGER,
                rs_1h           REAL,
                whale_detected  INTEGER,
                momentum_1h     REAL,
                would_be_signal TEXT,
                -- forward returns (מתמלא אחר כך)
                ret_30m         REAL,
                ret_1h          REAL,
                ret_4h          REAL,
                ret_24h         REAL,
                max_gain_24h    REAL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_shadow_ts     ON shadow_signals(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_shadow_symbol ON shadow_signals(symbol)")
    log.info("Shadow DB initialized")


def save_shadow_signal(coin: dict, signal: str):
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            INSERT INTO shadow_signals (
                ts, symbol, price, final_score,
                flow_score, pre_score, rvol, oi_change,
                is_compressed, rs_1h, whale_detected, momentum_1h,
                would_be_signal
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts, coin["symbol"], coin.get("price"),
            coin.get("final_score"), coin.get("flow_score"),
            coin.get("pre_score"), coin.get("rvol"),
            coin.get("oi_change"), int(coin.get("is_compressed", False)),
            coin.get("rs_1h"), int(coin.get("whale_detected", False)),
            coin.get("momentum_1h"), signal,
        ))


# ─── Forward Returns ──────────────────────────────────────────────────────────

def _get_price_now(symbol: str) -> float | None:
    """מחיר נוכחי מ-CoinGecko."""
    try:
        base = symbol.replace("USDT","").lower()
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": base, "vs_currencies": "usd"},
            headers={"User-Agent": "crypto-bot/1.0"}, timeout=8,
        )
        data = r.json()
        return float(list(data.values())[0]["usd"]) if data else None
    except Exception:
        return None


def update_forward_returns():
    """
    מעדכן forward returns לסיגנלים שעדיין לא מולאו.
    קורא בכל ריצה של main.py.
    """
    from datetime import datetime, timedelta
    now = datetime.now(timezone.utc)

    with _conn() as c:
        # סיגנלים שhret_24h חסר להם וגיל > 24h
        rows = c.execute("""
            SELECT id, symbol, price, ts
            FROM shadow_signals
            WHERE ret_24h IS NULL
            AND ts < ?
            LIMIT 50
        """, ((now - timedelta(hours=24)).isoformat(),)).fetchall()

    for row in rows:
        price_then = row["price"]
        if not price_then or price_then <= 0:
            continue
        price_now = _get_price_now(row["symbol"])
        if not price_now:
            continue
        ret_24h = round((price_now - price_then) / price_then * 100, 2)
        with _conn() as c:
            c.execute("UPDATE shadow_signals SET ret_24h=? WHERE id=?",
                      (ret_24h, row["id"]))


# ─── Analytics ────────────────────────────────────────────────────────────────

def shadow_report() -> str:
    """
    מפיק דוח: אילו משתנים משותפים ל-Winners?
    """
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM shadow_signals WHERE ret_24h IS NOT NULL").fetchone()[0]
        if total < 10:
            return f"Shadow Mode: {total} סיגנלים עם נתונים. צריך לפחות 10 לדוח."

        winners = c.execute("""
            SELECT AVG(flow_score) as flow, AVG(pre_score) as pre,
                   AVG(rvol) as rvol, AVG(oi_change) as oi,
                   COUNT(*) as cnt
            FROM shadow_signals
            WHERE ret_24h >= 20
        """).fetchone()

        losers = c.execute("""
            SELECT AVG(flow_score) as flow, AVG(pre_score) as pre,
                   AVG(rvol) as rvol, AVG(oi_change) as oi,
                   COUNT(*) as cnt
            FROM shadow_signals
            WHERE ret_24h < 5
        """).fetchone()

        by_signal = c.execute("""
            SELECT would_be_signal,
                   COUNT(*) as cnt,
                   AVG(ret_24h) as avg_ret,
                   SUM(CASE WHEN ret_24h >= 20 THEN 1 ELSE 0 END) as winners
            FROM shadow_signals
            WHERE ret_24h IS NOT NULL
            GROUP BY would_be_signal
        """).fetchall()

    lines = [
        f"📊 SHADOW MODE REPORT",
        f"סה\"כ סיגנלים: {total}",
        "",
        f"🟢 Winners (20%+): {winners['cnt'] if winners else 0}",
        f"   Flow ממוצע: {winners['flow']:.0f}" if winners and winners['flow'] else "",
        f"   Pre ממוצע:  {winners['pre']:.0f}"  if winners and winners['pre']  else "",
        f"   RVOL ממוצע: {winners['rvol']:.1f}" if winners and winners['rvol'] else "",
        "",
        f"🔴 חלשים (<5%): {losers['cnt'] if losers else 0}",
        f"   Flow ממוצע: {losers['flow']:.0f}" if losers and losers['flow'] else "",
        "",
        "📈 לפי סיגנל:",
    ]
    for row in by_signal:
        win_rate = row["winners"]/row["cnt"]*100 if row["cnt"] > 0 else 0
        lines.append(
            f"   {row['would_be_signal']:<10} "
            f"n={row['cnt']} "
            f"avg={row['avg_ret']:+.1f}% "
            f"win_rate={win_rate:.0f}%"
        )
    return "\n".join(l for l in lines if l is not None)
