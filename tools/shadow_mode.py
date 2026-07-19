import os
import sqlite3
import csv
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
    """מוסיף עמודה לטבלה אם היא עדיין לא קיימת."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass  # העמודה כבר קיימת

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Init
# ═══════════════════════════════════════════════════════════════════════════════
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
                is_compressed TEXT,
                status TEXT,
                reason TEXT,
                probability REAL,
                market_health REAL,
                news_score REAL,
                btc_regime TEXT,
                funding REAL,
                exit_reason TEXT,
                pnl REAL,
                pnl_pct REAL DEFAULT 0,
                max_profit_pct REAL DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0,
                trade_state TEXT DEFAULT 'ACTIVE',
                exit_price REAL DEFAULT 0
            )
        ''')

        # ── הרצה דינמית ובטוחה של כל העמודות החדשות ───────────────────────────
        new_columns = [
            ("pnl_pct", "REAL DEFAULT 0"),
            ("max_profit_pct", "REAL DEFAULT 0"),
            ("max_drawdown_pct", "REAL DEFAULT 0"),
            ("trade_state", "TEXT DEFAULT 'ACTIVE'"),
            ("exit_price", "REAL DEFAULT 0"),
            ("trigger_price", "REAL DEFAULT 0"),
            ("duration_minutes", "INTEGER DEFAULT 0"),
            ("outcome_trigger_hit", "INTEGER DEFAULT 0"),
            ("outcome_tp1_hit", "INTEGER DEFAULT 0"),
            ("outcome_tp2_hit", "INTEGER DEFAULT 0"),
            ("outcome_sl_hit", "INTEGER DEFAULT 0"),
            ("outcome_max_up_pct", "REAL DEFAULT 0"),
            ("outcome_max_down_pct", "REAL DEFAULT 0"),
            ("outcome_checked", "INTEGER DEFAULT 0"),
            # ── עמודות ה-Ground Truth החדשות לחישוב זמנים ומחירי קצה ─────────
            ("outcome_trigger_min", "REAL DEFAULT 0"),
            ("outcome_tp1_min", "REAL DEFAULT 0"),
            ("outcome_tp2_min", "REAL DEFAULT 0"),
            ("outcome_sl_min", "REAL DEFAULT 0"),
            ("outcome_highest_price", "REAL DEFAULT 0"),
            ("outcome_lowest_price", "REAL DEFAULT 0")
        ]

        for col, typ in new_columns:
            _add_column_if_not_exists(c, "shadow_trades", col, typ)

    log.info("Shadow DB initialized for Trade Tracking")
    try:
        update_open_trades()
        export_shadow_csv()
    except Exception as e:
        log.error(f"Shadow Engine Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Save every signal (WATCH / PREPARE / ARM / BUY / IGNORE)
# ═══════════════════════════════════════════════════════════════════════════════
def save_shadow_signal(coin: dict, signal: str):
    """שומר כל מטבע שנסרק — גם אם לא נכנס כעסקה."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as c:
            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts,
                coin.get("symbol", "UNKNOWN"),
                signal,
                coin.get("entry_setup", ""),
                coin.get("entry_price", coin.get("price", 0)),
                coin.get("trigger_price", 0),
                coin.get("entry_tp1", 0),
                coin.get("entry_tp2", 0),
                coin.get("entry_sl", 0),
                coin.get("final_score", 0),
                coin.get("flow_score", 0),
                coin.get("pre_score", 0),
                coin.get("oi_change", 0),
                coin.get("rs_1h", 0),
                str(coin.get("is_compressed", False)),
                signal,
                coin.get("entry_reason", ""),
                coin.get("probability", 0),
                coin.get("market_health", 50),
                coin.get("news_score", 50),
                coin.get("btc_regime", ""),
                coin.get("funding", 0),
            ))
        export_shadow_csv()
    except Exception as e:
        log.error(f"save_shadow_signal failed: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Record a BUY trade
# ═══════════════════════════════════════════════════════════════════════════════
def record_trade(coin: dict, signal):
    if not signal or signal.decision not in ["BUY", "PREPARE"]:
        return

    ts = datetime.now(timezone.utc).isoformat()
    initial_status = "Pending ⏳" if signal.decision == "BUY" else "-"

    try:
        with _conn() as c:
            count = c.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
            log.info(f"Shadow DB rows BEFORE insert: {count}")

            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding, trade_state
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts,
                coin.get("symbol", "UNKNOWN"),
                signal.decision,
                getattr(signal, "setup_type", ""),
                getattr(signal, "entry", 0.0),
                coin.get("trigger_price", 0.0),
                getattr(signal, "tp1", 0.0),
                getattr(signal, "tp2", 0.0),
                getattr(signal, "sl", 0.0),
                coin.get("final_score", 0),
                coin.get("flow_score", 0),
                coin.get("pre_score", 0),
                coin.get("oi_change", 0),
                coin.get("rs_1h", 0),
                str(coin.get("is_compressed", False)),
                initial_status,
                getattr(signal, "reason", ""),
                coin.get("probability", 0),
                coin.get("market_health", 50),
                coin.get("news_score", 50),
                coin.get("btc_regime", ""),
                coin.get("funding", 0),
                'ACTIVE'
            ))

            count = c.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
            log.info(f"Shadow DB rows AFTER insert: {count}")

        log.info(f"Recorded shadow trade for {coin.get('symbol', 'UNKNOWN')} ({signal.decision})")
        export_shadow_csv()
    except Exception as e:
        log.error(f"Failed to record shadow trade: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Update exit
# ═══════════════════════════════════════════════════════════════════════════════
def update_open_trades():
    try:
        with _conn() as c:
            open_trades = c.execute("SELECT * FROM shadow_trades WHERE status = 'Pending ⏳'").fetchall()

        updated_count = 0
        for trade in open_trades:
            current_price = _get_binance_price(trade["symbol"])
            if current_price <= 0:
                continue

            entry = float(trade["entry_price"])
            tp1 = float(trade["tp1"]) if trade["tp1"] else 0.0
            sl = float(trade["sl"]) if trade["sl"] else 0.0

            # ── עדכון ביצועים בזמן אמת ──────────────────────────────
            pnl_pct = ((current_price - entry) / entry) * 100
            max_profit = max(float(trade["max_profit_pct"] or 0), pnl_pct)
            max_dd = min(float(trade["max_drawdown_pct"] or 0), pnl_pct)

            # שמירה שוטפת
            with _conn() as c:
                c.execute("""
                    UPDATE shadow_trades
                    SET pnl_pct = ?,
                        max_profit_pct = ?,
                        max_drawdown_pct = ?
                    WHERE id = ?
                """, (round(pnl_pct, 2), round(max_profit, 2), round(max_dd, 2), trade["id"]))

            # ── בדיקת סגירה לפי TP1 / SL / Timeout ─────────────────
            new_status = "Pending ⏳"
            if tp1 > 0 and current_price >= tp1:
                new_status = "TP1 Hit 🎯"
            elif sl > 0 and current_price <= sl:
                new_status = "SL Hit 🛑"
            else:
                trade_time = datetime.fromisoformat(trade["ts"])
                if datetime.now(timezone.utc) - trade_time > timedelta(hours=24):
                    new_status = "Timeout ⏱️"

            if new_status != "Pending ⏳":
                duration_min = int((datetime.now(timezone.utc) -
                                    datetime.fromisoformat(trade["ts"])).total_seconds() / 60)
                with _conn() as c:
                    c.execute("""
                        UPDATE shadow_trades
                        SET status = ?,
                            trade_state = 'CLOSED',
                            exit_price = ?,
                            pnl_pct = ?,
                            duration_minutes = ?,
                            outcome_checked = 1
                        WHERE id = ?
                    """, (new_status, current_price, round(pnl_pct, 2), duration_min, trade["id"]))
                updated_count += 1

        if updated_count > 0:
            log.info(f"Shadow Tracker: Updated {updated_count} trades.")
            export_shadow_csv()
    except Exception as e:
        log.error(f"Error in update_open_trades: {e}")
# ═══════════════════════════════════════════════════════════════════════════════
# 6. CSV export
# ═══════════════════════════════════════════════════════════════════════════════
def export_shadow_csv():
    filepath = "shadow_results.csv"
    try:
        with _conn() as c:
            trades = c.execute("SELECT * FROM shadow_trades ORDER BY id DESC").fetchall()

        with open(filepath, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Time", "Coin", "Decision", "Setup", "Entry", "Trigger Price", "TP1", "TP2", "SL",
                "Final Score", "Probability", "Flow", "Pre", "OI", "Funding", "RS",
                "Compression", "Market Health", "News Score", "BTC Regime",
                "Status", "Reason", "Exit Reason", "PnL", "PnL%", "Max Profit%",
                "Max DD%", "Trade State", "Exit Price", "Duration (m)",
                "Trigger Hit", "TP1 Hit", "TP2 Hit", "SL Hit",
                "Max Up%", "Max Down%", "Outcome Checked"
            ])

            log.info(f"Exporting {len(trades)} shadow trades")
            for t in trades:
                t = dict(t)   # ← המרה קריטית שמנקה שגיאות טיפוס
                dt_str = datetime.fromisoformat(t["ts"]).strftime("%H:%M:%S") if t["ts"] else ""
                writer.writerow([
                    dt_str, 
                    t.get("symbol", ""), 
                    t.get("decision", ""), 
                    t.get("setup", ""),
                    t.get("entry_price", 0), 
                    t.get("trigger_price", 0), 
                    t.get("tp1", 0), 
                    t.get("tp2", 0), 
                    t.get("sl", 0),
                    t.get("ai_score", 0), 
                    t.get("probability", 0), 
                    t.get("flow_score", 0), 
                    t.get("pre_score", 0),
                    t.get("oi_change", 0), 
                    t.get("funding", 0), 
                    t.get("rs_1h", 0), 
                    t.get("is_compressed", ""),
                    t.get("market_health", 50), 
                    t.get("news_score", 50), 
                    t.get("btc_regime", ""),
                    t.get("status", ""), 
                    t.get("reason", ""), 
                    t.get("exit_reason", ""), 
                    t.get("pnl", 0), 
                    t.get("pnl_pct", 0),
                    t.get("max_profit_pct", 0), 
                    t.get("max_drawdown_pct", 0), 
                    t.get("trade_state", ""),
                    t.get("exit_price", 0), 
                    t.get("duration_minutes", 0),
                    t.get("outcome_trigger_hit", 0), 
                    t.get("outcome_tp1_hit", 0), 
                    t.get("outcome_tp2_hit", 0),
                    t.get("outcome_sl_hit", 0), 
                    t.get("outcome_max_up_pct", 0), 
                    t.get("outcome_max_down_pct", 0),
                    t.get("outcome_checked", 0)
                ])
        log.info(f"CSV Exported: {os.path.abspath(filepath)}")
    except Exception as e:
        log.error(f"Error exporting shadow CSV: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Forward returns (optional)
# ═══════════════════════════════════════════════════════════════════════════════
def update_forward_returns():
    """Placeholder – not implemented yet."""
    pass
