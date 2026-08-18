import os
import sqlite3
import csv
import json
import requests
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

log = get_logger(__name__)
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _add_column_if_not_exists(cursor, table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def init_shadow_db():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS shadow_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                decision TEXT,
                setup TEXT,
                entry_price REAL,
                tp1 REAL,
                tp2 REAL,
                sl REAL,
                ai_score REAL,
                flow_score REAL,
                pre_score REAL,
                oi_change REAL,
                rs_1h REAL,
                is_compressed INTEGER,
                status TEXT,
                reason TEXT,
                probability REAL,
                market_health REAL,
                news_score REAL,
                btc_regime TEXT,
                funding REAL,
                exit_reason TEXT,
                pnl REAL,
                pnl_pct REAL,
                max_profit_pct REAL,
                max_drawdown_pct REAL,
                trade_state TEXT,
                exit_price REAL
            )
        ''')

        new_columns = [
            ("pnl_pct", "REAL"), ("max_profit_pct", "REAL"), ("max_drawdown_pct", "REAL"),
            ("trade_state", "TEXT"), ("exit_price", "REAL"), ("trigger_price", "REAL"),
            ("duration_minutes", "INTEGER"), ("outcome_trigger_hit", "INTEGER"),
            ("outcome_tp1_hit", "INTEGER"), ("outcome_tp2_hit", "INTEGER"),
            ("outcome_sl_hit", "INTEGER"), ("outcome_max_up_pct", "REAL"),
            ("outcome_max_down_pct", "REAL"), ("outcome_checked", "INTEGER"),
            ("outcome_status", "TEXT"), ("first_tp_hit_time", "REAL"),
            ("last_update_time", "TEXT"), ("outcome_mfe", "REAL"), ("outcome_mae", "REAL"),
            ("time_to_trigger_min", "REAL"), ("time_to_tp1_min", "REAL"),
            ("outcome_tp2_min", "REAL"), ("time_to_sl_min", "REAL"),
            ("outcome_highest_price", "REAL"), ("outcome_lowest_price", "REAL"),
            ("pnl_r", "REAL"), ("mfe_r", "REAL"), ("mae_r", "REAL"),
            ("exit_time", "TEXT"), ("direction", "TEXT DEFAULT 'LONG'"),
            ("shadow_tags", "TEXT DEFAULT '[]'"), ("shadow_rs", "TEXT")
        ]
        for col, typ in new_columns:
            _add_column_if_not_exists(c, "shadow_trades", col, typ)

    log.info("Shadow DB initialized for Trade Tracking & Learning Pipeline")
    try:
        export_shadow_csv()
    except Exception as e:
        log.error(f"Shadow CSV Error: {e}")


def _shadow_tags(coin: dict) -> str:
    tags = []
    try:
        rs_val = float(coin.get("rs_1h", 0) or 0)
    except (TypeError, ValueError):
        rs_val = 0.0
    tags.append("shadow_rs_low" if rs_val < 0.5 else "shadow_rs_ok")

    regime = coin.get("btc_regime", "")
    try:
        mh = float(coin.get("market_health", 0) or 0)
    except (TypeError, ValueError):
        mh = 0.0
    tags.append("shadow_regime_bad" if (regime != "TREND_UP" or mh < 55) else "shadow_regime_ok")

    hour = datetime.now(timezone.utc).hour
    if hour in [0, 1, 6, 9, 11, 13, 19, 21]:
        tags.append("shadow_hour_weak")

    return json.dumps(tags)


def _shadow_rs_value(rs: float) -> str:
    return "RS_OK" if rs >= 0.5 else "RS_LOW"


def save_shadow_signal(coin: dict, signal: str):
    symbol = coin.get("symbol", "UNKNOWN")
    # בדיקת כפילות – אם יש כבר עסקה פעילה, לא מוסיפים
    try:
        with _conn() as c:
            exists = c.execute("""
                SELECT id FROM shadow_trades
                WHERE symbol = ? AND outcome_status != 'FINAL'
                ORDER BY id DESC LIMIT 1
            """, (symbol,)).fetchone()
            if exists:
                return
    except Exception as e:
        log.warning(f"Duplicate check failed: {e}")

    ts = datetime.now(timezone.utc).isoformat()
    tags = _shadow_tags(coin)
    shadow_rs = _shadow_rs_value(float(coin.get("rs_1h", 0) or 0))
    compressed = 1 if bool(coin.get("is_compressed", False)) else 0
    funding = float(coin.get("funding", 0) or 0)

    try:
        with _conn() as c:
            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding, shadow_tags, shadow_rs
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts, symbol, signal, coin.get("entry_setup", ""), coin.get("entry_price", coin.get("price", 0)),
                coin.get("trigger_price", 0), coin.get("entry_tp1", 0), coin.get("entry_tp2", 0), coin.get("entry_sl", 0),
                coin.get("ai_score", 0), coin.get("flow_score", 0), coin.get("pre_score", 0),
                coin.get("oi_change", 0), coin.get("rs_1h", 0), compressed, signal,
                coin.get("entry_reason", ""), coin.get("probability", 0), coin.get("market_health", 50),
                coin.get("news_score", 50), coin.get("btc_regime", ""), funding, tags, shadow_rs
            ))
        export_shadow_csv()
    except Exception as e:
        log.error(f"save_shadow_signal failed: {e}")


def record_trade(coin: dict, signal):
    if not signal or signal.decision not in ["BUY", "PREPARE"]:
        return

    symbol = coin.get("symbol", "UNKNOWN")
    try:
        with _conn() as c:
            exists = c.execute("""
                SELECT id FROM shadow_trades
                WHERE symbol = ? AND outcome_status != 'FINAL'
                ORDER BY id DESC LIMIT 1
            """, (symbol,)).fetchone()
            if exists:
                return
    except Exception as e:
        log.warning(f"Duplicate check failed: {e}")

    ts = datetime.now(timezone.utc).isoformat()
    initial_status = "Pending ⏳" if signal.decision == "BUY" else "-"
    tags = _shadow_tags(coin)
    shadow_rs = _shadow_rs_value(float(coin.get("rs_1h", 0) or 0))
    compressed = 1 if bool(coin.get("is_compressed", False)) else 0
    funding = float(coin.get("funding", 0) or 0)

    try:
        with _conn() as c:
            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding, trade_state, shadow_tags, shadow_rs
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts, symbol, signal.decision, getattr(signal, "setup_type", ""),
                getattr(signal, "entry", 0.0), coin.get("trigger_price", 0.0),
                getattr(signal, "tp1", 0.0), getattr(signal, "tp2", 0.0), getattr(signal, "sl", 0.0),
                coin.get("ai_score", 0), coin.get("flow_score", 0), coin.get("pre_score", 0),
                coin.get("oi_change", 0), coin.get("rs_1h", 0), compressed, initial_status,
                getattr(signal, "reason", ""), coin.get("probability", 0), coin.get("market_health", 50),
                coin.get("news_score", 50), coin.get("btc_regime", ""), funding, 'ACTIVE', tags, shadow_rs
            ))
        log.info(f"Recorded shadow trade for {symbol} ({signal.decision})")
        export_shadow_csv()
    except Exception as e:
        log.error(f"Failed to record shadow trade: {e}")


def update_shadow_exit(symbol: str, exit_reason: str, pnl: float, duration_minutes: int,
                       pnl_pct: float = 0.0, max_profit_pct: float = 0.0,
                       max_drawdown_pct: float = 0.0, trade_state: str = 'CLOSED',
                       exit_price: float = 0.0):
    try:
        with _conn() as c:
            c.execute('''
                UPDATE shadow_trades
                SET status = 'CLOSED 🏁', exit_reason = ?, pnl = ?, pnl_pct = ?,
                    duration_minutes = ?, max_profit_pct = ?, max_drawdown_pct = ?,
                    trade_state = ?, exit_price = ?
                WHERE symbol = ? AND status != 'CLOSED 🏁'
            ''', (exit_reason, pnl, pnl_pct, duration_minutes, max_profit_pct,
                  max_drawdown_pct, trade_state, exit_price, symbol))
        export_shadow_csv()
    except Exception as e:
        log.error(f"Failed to update shadow exit for {symbol}: {e}")


def update_open_trades():
    """Outcome tracking מנוהל בלעדית ע"י tools/outcome_tracker.py"""
    pass


def export_shadow_csv():
    filepath = "shadow_results.csv"
    try:
        with _conn() as c:
            trades = c.execute("SELECT * FROM shadow_trades ORDER BY id DESC").fetchall()

        with open(filepath, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Time (Israel)", "Coin", "Decision", "Setup", "Entry", "Trigger Price", "TP1", "TP2", "SL",
                "AI Score", "Final Score", "Probability", "Flow", "Pre", "OI", "Funding", "RS",
                "Compression", "Market Health", "News Score", "BTC Regime",
                "Status", "Reason", "Exit Reason", "PnL", "PnL%", "PnL R",
                "Max Profit%", "Max DD%", "Trade State", "Exit Price", "Duration (m)",
                "Trigger Hit", "TP1 Hit", "TP2 Hit", "SL Hit",
                "Max Up%", "Max Down%", "MFE%", "MAE%", "Outcome Checked", "Outcome Status",
                "Shadow RS", "Shadow Tags"
            ])

            for t in trades:
                t = dict(t)
                dt_utc = datetime.fromisoformat(t["ts"]) if t.get("ts") else None
                dt_str = (dt_utc + timedelta(hours=3)).strftime("%H:%M:%S") if dt_utc else ""
                writer.writerow([
                    dt_str, t.get("symbol", ""), t.get("decision", ""), t.get("setup", ""),
                    t.get("entry_price", 0), t.get("trigger_price", 0), t.get("tp1", 0),
                    t.get("tp2", 0), t.get("sl", 0), t.get("ai_score", 0),
                    t.get("final_score", 0) if "final_score" in t else 0, t.get("probability", 0),
                    t.get("flow_score", 0), t.get("pre_score", 0), t.get("oi_change", 0),
                    t.get("funding", 0), t.get("rs_1h", 0), t.get("is_compressed", 0),
                    t.get("market_health", 50), t.get("news_score", 50), t.get("btc_regime", ""),
                    t.get("status", ""), t.get("reason", ""), t.get("exit_reason", ""),
                    t.get("pnl", 0), t.get("pnl_pct", 0), t.get("pnl_r", 0),
                    t.get("max_profit_pct", 0), t.get("max_drawdown_pct", 0), t.get("trade_state", ""),
                    t.get("exit_price", 0), t.get("duration_minutes", 0),
                    t.get("outcome_trigger_hit", 0), t.get("outcome_tp1_hit", 0),
                    t.get("outcome_tp2_hit", 0), t.get("outcome_sl_hit", 0),
                    t.get("outcome_max_up_pct", 0), t.get("outcome_max_down_pct", 0),
                    t.get("outcome_mfe", 0), t.get("outcome_mae", 0),
                    t.get("outcome_checked", 0), t.get("outcome_status", ""),
                    t.get("shadow_rs", "UNKNOWN"), t.get("shadow_tags", "")
                ])
        log.info(f"CSV Exported: {os.path.abspath(filepath)}")
    except Exception as e:
        log.error(f"Error exporting shadow CSV: {e}")
