"""
CRYPTO-BOT Elite — Trade Logger / Journal

שומר כל טרייד ומעקב אחר Max Runup.
זה הבסיס ל-Self Learning.

Schema:
    trades  — כל טרייד: כניסה, יציאה, max gain, PnL
    signals — כל סיגנל שנשלח (גם אם לא נכנסנו)
"""
import sqlite3
import os
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/history.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_trade_db() -> None:
    with _conn() as c:
        # טבלת טריידים
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                open_ts         TEXT NOT NULL,
                close_ts        TEXT,
                symbol          TEXT NOT NULL,
                -- Scores at entry
                big_move_score  REAL,
                flow_score      REAL,
                pre_score       REAL,
                final_score     REAL,
                regime          TEXT,
                setup_type      TEXT,
                -- Entry
                entry_price     REAL,
                position_pct    REAL,
                position_usd    REAL,
                confidence      REAL,
                -- Exit
                exit_price      REAL,
                exit_reason     TEXT,
                exit_signal     TEXT,
                -- Performance
                pnl_pct         REAL,
                pnl_usd         REAL,
                max_runup_pct   REAL,   -- MFE: הכי גבוה שהגיע
                max_drawdown_pct REAL,  -- MAE: הכי נמוך שירד
                hit_tp1         INTEGER DEFAULT 0,
                hit_tp2         INTEGER DEFAULT 0,
                hit_sl          INTEGER DEFAULT 0,
                setup_type_label TEXT,  -- לדוגמה: "Compression+OI", "Whale+RS"
                hold_minutes    REAL,
                -- Exit indicators
                cvd_at_exit     REAL,
                rs_at_exit      REAL,
                ema_broken      INTEGER DEFAULT 0
            )
        """)

        # טבלת סיגנלים (לכל מה שנשלח לטלגרם)
        c.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                price           REAL,
                regime          TEXT,
                rvol            REAL,
                vol_accel       REAL,
                momentum_5m     REAL,
                momentum_15m    REAL,
                momentum_1h     REAL,
                vwap_dist       REAL,
                rsi_14          REAL,
                rs_1h           REAL,
                rs_4h           REAL,
                flow_score      REAL,
                pre_score       REAL,
                final_score     REAL,
                entry_decision  TEXT,
                entry_price     REAL,
                is_sympathy     INTEGER DEFAULT 0,
                leader_symbol   TEXT,
                -- Future returns (מתמלא בסריקות הבאות)
                ret_5m          REAL,
                ret_15m         REAL,
                ret_30m         REAL,
                ret_1h          REAL,
                ret_4h          REAL,
                max_gain_24h    REAL
            )
        """)

        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts)")
        log.info("Trade DB initialized")


# ─── Trade Operations ─────────────────────────────────────────────────────────

def open_trade(coin: dict, position: dict) -> int:
    """
    פותח טרייד חדש. מחזיר trade_id.
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO trades (
                open_ts, symbol,
                big_move_score, flow_score, pre_score, final_score,
                regime, setup_type,
                entry_price, position_pct, position_usd, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts, coin["symbol"],
            coin.get("pre_score", 0),
            coin.get("flow_score", 0),
            coin.get("pre_score", 0),
            coin.get("final_score", 0),
            coin.get("regime",""),
            coin.get("entry_setup",""),
            coin.get("entry_price", 0),
            position.get("pct_of_portfolio", 0),
            position.get("usd_amount", 0),
            position.get("confidence", 0),
        ))
        trade_id = cur.lastrowid
        log.info(f"Trade opened: {coin['symbol']} #{trade_id} @ {coin.get('entry_price',0)}")
        return trade_id


def update_runup(trade_id: int, current_price: float, entry_price: float) -> None:
    """מעדכן Max Runup — קורא בכל סריקה כשהפוזיציה פתוחה."""
    if entry_price <= 0:
        return
    gain_pct = (current_price - entry_price) / entry_price * 100
    with _conn() as c:
        existing = c.execute(
            "SELECT max_runup_pct, max_drawdown_pct FROM trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not existing:
            return
        max_runup = max(existing["max_runup_pct"] or 0, gain_pct)
        max_dd    = min(existing["max_drawdown_pct"] or 0, gain_pct)
        c.execute(
            "UPDATE trades SET max_runup_pct=?, max_drawdown_pct=? WHERE id=?",
            (max_runup, max_dd, trade_id)
        )


def close_trade(
    trade_id:     int,
    exit_price:   float,
    exit_reason:  str,
    exit_signal:  str,
    entry_price:  float,
    position_usd: float,
    cvd_at_exit:  float = 0.0,
    rs_at_exit:   float = 0.0,
    ema_broken:   bool  = False,
) -> dict:
    """
    סוגר טרייד. מחשב PnL ו-hold time. מחזיר summary dict.
    """
    close_ts = datetime.now(timezone.utc).isoformat()

    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 3) if entry_price > 0 else 0
    pnl_usd = round(position_usd * pnl_pct / 100, 2)

    with _conn() as c:
        opened = c.execute("SELECT open_ts, max_runup_pct FROM trades WHERE id=?", (trade_id,)).fetchone()
        hold_min = 0.0
        max_runup = 0.0
        if opened:
            from datetime import datetime as dt
            try:
                open_dt   = dt.fromisoformat(opened["open_ts"])
                close_dt  = dt.fromisoformat(close_ts)
                hold_min  = (close_dt - open_dt).total_seconds() / 60
                max_runup = opened["max_runup_pct"] or 0
            except Exception:
                pass

        c.execute("""
            UPDATE trades SET
                close_ts=?, exit_price=?, exit_reason=?, exit_signal=?,
                pnl_pct=?, pnl_usd=?, hold_minutes=?,
                cvd_at_exit=?, rs_at_exit=?, ema_broken=?
            WHERE id=?
        """, (
            close_ts, exit_price, exit_reason, exit_signal,
            pnl_pct, pnl_usd, round(hold_min, 1),
            cvd_at_exit, rs_at_exit, int(ema_broken),
            trade_id,
        ))

    summary = {
        "trade_id":    trade_id,
        "pnl_pct":     pnl_pct,
        "pnl_usd":     pnl_usd,
        "max_runup":   max_runup,
        "hold_min":    round(hold_min, 1),
        "exit_signal": exit_signal,
    }
    icon = "✅" if pnl_pct > 0 else "❌"
    log.info(f"{icon} Trade closed #{trade_id}: {pnl_pct:+.1f}% (${pnl_usd:+.0f}) | max runup: {max_runup:.1f}%")
    return summary


# ─── Signal Logging ───────────────────────────────────────────────────────────

def log_signal(coin: dict) -> int:
    """שומר כל סיגנל שנשלח לטלגרם."""
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO signals (
                ts, symbol, price, regime,
                rvol, vol_accel, momentum_5m, momentum_15m, momentum_1h,
                vwap_dist, rsi_14, rs_1h, rs_4h,
                flow_score, pre_score, final_score,
                entry_decision, entry_price,
                is_sympathy, leader_symbol
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts, coin["symbol"], coin.get("price"), coin.get("regime",""),
            coin.get("rvol"), coin.get("vol_accel"),
            coin.get("momentum_5m"), coin.get("momentum_15m"), coin.get("momentum_1h"),
            coin.get("vwap_dist"), coin.get("rsi_14"),
            coin.get("rs_1h"), coin.get("rs_4h"),
            coin.get("flow_score"), coin.get("pre_score"), coin.get("final_score"),
            coin.get("entry_decision"), coin.get("entry_price"),
            int(coin.get("is_sympathy", False)),
            coin.get("leader", ""),
        ))
        return cur.lastrowid


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_performance_stats() -> dict:
    """
    סטטיסטיקות ביצועים לאחר מספיק טריידים.
    """
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0]
        if total == 0:
            return {"total": 0, "message": "אין עדיין טריידים סגורים"}

        wins = c.execute("SELECT COUNT(*) FROM trades WHERE pnl_pct > 0 AND close_ts IS NOT NULL").fetchone()[0]
        avg_pnl   = c.execute("SELECT AVG(pnl_pct) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0] or 0
        avg_runup = c.execute("SELECT AVG(max_runup_pct) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0] or 0
        best      = c.execute("SELECT MAX(pnl_pct) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0] or 0
        worst     = c.execute("SELECT MIN(pnl_pct) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0] or 0
        avg_hold  = c.execute("SELECT AVG(hold_minutes) FROM trades WHERE close_ts IS NOT NULL").fetchone()[0] or 0

        # הכי טוב לפי setup
        best_setup = c.execute("""
            SELECT setup_type, AVG(pnl_pct) as avg_pnl, COUNT(*) as cnt
            FROM trades WHERE close_ts IS NOT NULL
            GROUP BY setup_type ORDER BY avg_pnl DESC LIMIT 1
        """).fetchone()

        return {
            "total":         total,
            "win_rate":      round(wins / total * 100, 1),
            "avg_pnl":       round(avg_pnl, 2),
            "avg_max_runup": round(avg_runup, 2),
            "best_trade":    round(best, 2),
            "worst_trade":   round(worst, 2),
            "avg_hold_min":  round(avg_hold, 1),
            "best_setup":    dict(best_setup) if best_setup else {},
        }


if __name__ == "__main__":
    init_trade_db()
    stats = get_performance_stats()
    print(f"Stats: {stats}")
