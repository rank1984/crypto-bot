"""
CRYPTO-BOT Elite — Outcome Evaluator

רץ כל שעה. בודק מה קרה למטבעות אחרי 1h/4h/24h.
"""
import requests
import sqlite3
from datetime import datetime, timezone, timedelta
from learning.database import _conn, init_db
from utils.logger import get_logger

log = get_logger(__name__)

_CG = "https://api.coingecko.com/api/v3"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}

# מיפוי מטבעות ל-CoinGecko IDs
_ID_MAP = {
    "BTC":"bitcoin","ETH":"ethereum","SOL":"solana","BNB":"binancecoin",
    "AVAX":"avalanche-2","LINK":"chainlink","UNI":"uniswap","AAVE":"aave",
    "NEAR":"near","APT":"aptos","ARB":"arbitrum","OP":"optimism",
    "INJ":"injective-protocol","SUI":"sui","RUNE":"thorchain",
    "FET":"fetch-ai","RNDR":"render-token","DOGE":"dogecoin",
    "PEPE":"pepe","WIF":"dogwifcoin","BONK":"bonk","SEI":"sei-network",
}


def _get_price(symbol: str) -> float | None:
    base = symbol.replace("USDT","").upper()
    cg_id = _ID_MAP.get(base, base.lower())
    try:
        r = requests.get(f"{_CG}/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            headers=_HEADERS, timeout=8)
        data = r.json()
        if data:
            return float(list(data.values())[0]["usd"])
    except Exception:
        pass
    return None


def evaluate_outcomes():
    """
    מעדכן outcomes לכל מועמד שעדיין לא עודכן.
    """
    init_db()
    now = datetime.now(timezone.utc)

    with _conn() as c:
        # מועמדים ללא outcomes שנוצרו לפחות שעה
        rows = c.execute("""
            SELECT ca.id, ca.symbol, ca.price, ca.ts
            FROM candidates ca
            LEFT JOIN outcomes o ON o.candidate_id = ca.id
            WHERE o.id IS NULL
            AND ca.ts < ?
            AND ca.decision IN ('BUY','WAIT')
            LIMIT 30
        """, ((now - timedelta(hours=1)).isoformat(),)).fetchall()

    updated = 0
    for row in rows:
        cand_id = row["id"]
        symbol  = row["symbol"]
        entry   = float(row["price"] or 0)
        if entry <= 0:
            continue

        price_now = _get_price(symbol)
        if not price_now:
            continue

        ret = round((price_now - entry) / entry * 100, 2)

        # בדוק אם הגיע ל-TP1 (entry + 5%) או SL (entry - 3%)
        with _conn() as c:
            cand = c.execute(
                "SELECT tp1_price, sl_price FROM candidates WHERE id=?", (cand_id,)
            ).fetchone()

        hit_tp1 = int(cand and cand["tp1_price"] and price_now >= cand["tp1_price"])
        hit_sl  = int(cand and cand["sl_price"]  and price_now <= cand["sl_price"])

        with _conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO outcomes
                    (candidate_id, symbol, entry_price, ret_1h, max_gain, hit_tp1, hit_sl, updated_ts)
                VALUES (?,?,?,?,?,?,?,?)
            """, (cand_id, symbol, entry, ret, max(0, ret), hit_tp1, hit_sl,
                  now.isoformat()))
        updated += 1

    if updated:
        log.info(f"Evaluated {updated} outcomes")
    return updated


def update_performance():
    """מעדכן טבלת performance לפי outcomes אמיתיים."""
    with _conn() as c:
        setups_data = c.execute("""
            SELECT s.compression, s.whale, s.flow_strong, s.oi_surge,
                   o.ret_1h
            FROM setups s
            JOIN candidates ca ON ca.id = s.candidate_id
            JOIN outcomes o    ON o.candidate_id = ca.id
            WHERE o.ret_1h IS NOT NULL
        """).fetchall()

    if not setups_data:
        return

    # חשב per-setup
    setups = {
        "Compression": lambda r: r["compression"],
        "Whale":       lambda r: r["whale"],
        "Flow Strong": lambda r: r["flow_strong"],
        "OI Surge":    lambda r: r["oi_surge"],
    }

    with _conn() as c:
        for setup_name, selector in setups.items():
            relevant = [r["ret_1h"] for r in setups_data if selector(r)]
            if not relevant:
                continue
            wins     = [r for r in relevant if r > 0]
            losses   = [r for r in relevant if r <= 0]
            avg_win  = sum(wins)/len(wins) if wins else 0
            avg_loss = abs(sum(losses)/len(losses)) if losses else 0
            exp      = (len(wins)/len(relevant)*avg_win) - (len(losses)/len(relevant)*avg_loss)
            pf       = (len(wins)*avg_win) / (len(losses)*avg_loss) if losses and avg_loss > 0 else 0

            c.execute("""
                INSERT OR REPLACE INTO performance
                    (setup_name, trades, wins, avg_win, avg_loss, expectancy, profit_factor, last_updated)
                VALUES (?,?,?,?,?,?,?,?)
            """, (setup_name, len(relevant), len(wins),
                  round(avg_win,2), round(avg_loss,2),
                  round(exp,2), round(pf,2),
                  datetime.now(timezone.utc).isoformat()))
