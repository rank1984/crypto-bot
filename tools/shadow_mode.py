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


# ✅ 4 קטגוריות RS (סקאלת 0-1+)
def _rs_bucket(rs_val) -> str:
    try:
        rs = float(rs_val or 0)
    except (TypeError, ValueError):
        rs = 0.0
    if rs < 0:
        return "RS<0"
    elif rs < 0.5:
        return "RS_0_0.5"
    elif rs < 1:
        return "RS_0.5_1"
    else:
        return "RS>1"


# ✅ 5 קטגוריות AI (סקאלת 0-100)
def _ai_bucket(ai_score) -> str:
    try:
        ai = float(ai_score or 0)
    except (TypeError, ValueError):
        ai = 0.0
    if ai < 20:
        return "AI_0_20"
    elif ai < 40:
        return "AI_20_40"
    elif ai < 60:
        return "AI_40_60"
    elif ai < 80:
        return "AI_60_80"
    else:
        return "AI_80_100"


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
            ("shadow_tags", "TEXT DEFAULT '[]'"), ("shadow_rs", "TEXT"),
            # V8 תוספות
            ("was_executed", "INTEGER DEFAULT 0"),
            ("execution_timestamp", "TEXT"),
            ("actual_fill_price", "REAL"),
            ("execution_delay_sec", "REAL"),
            ("skip_reason", "TEXT"),
            ("buy_intent_time", "TEXT"),
            ("rs_bucket", "TEXT"),
            ("ai_bucket", "TEXT"),
            ("first_outcome_type", "TEXT"),
            ("ambiguous_bar", "INTEGER DEFAULT 0"),
            ("entry_candle_ambiguous", "INTEGER DEFAULT 0"),
            ("pnl_pct_method", "TEXT"),
            ("entry_slippage_pct", "REAL"),
            # עמודות התראות יציאה
            ("tp1_alert_sent", "INTEGER DEFAULT 0"),
            ("tp2_alert_sent", "INTEGER DEFAULT 0"),
            ("sl_alert_sent", "INTEGER DEFAULT 0"),
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
    rs_bucket = _rs_bucket(coin.get("rs_1h", 0))
    ai_bucket = _ai_bucket(coin.get("ai_score", 0))
    compressed = 1 if bool(coin.get("is_compressed", False)) else 0
    funding = float(coin.get("funding", 0) or 0)

    try:
        with _conn() as c:
            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding,
                    shadow_tags, shadow_rs, rs_bucket, ai_bucket
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts, symbol, signal, coin.get("entry_setup", ""), coin.get("entry_price", coin.get("price", 0)),
                coin.get("trigger_price", 0), coin.get("entry_tp1", 0), coin.get("entry_tp2", 0), coin.get("entry_sl", 0),
                coin.get("ai_score", 0), coin.get("flow_score", 0), coin.get("pre_score", 0),
                coin.get("oi_change", 0), coin.get("rs_1h", 0), compressed, signal,
                coin.get("entry_reason", ""), coin.get("probability", 0), coin.get("market_health", 50),
                coin.get("news_score", 50), coin.get("btc_regime", ""), funding,
                tags, shadow_rs, rs_bucket, ai_bucket
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
    rs_bucket = _rs_bucket(coin.get("rs_1h", 0))
    ai_bucket = _ai_bucket(coin.get("ai_score", 0))
    compressed = 1 if bool(coin.get("is_compressed", False)) else 0
    funding = float(coin.get("funding", 0) or 0)

    try:
        with _conn() as c:
            # ✅ תיקון: 27 עמודות = 27 placeholders = 27 ערכים
            c.execute('''
                INSERT INTO shadow_trades (
                    ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
                    ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed, status, reason,
                    probability, market_health, news_score, btc_regime, funding, trade_state,
                    shadow_tags, shadow_rs, rs_bucket, ai_bucket
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                ts, symbol, signal.decision, getattr(signal, "setup_type", ""),
                getattr(signal, "entry", 0.0), coin.get("trigger_price", 0.0),
                getattr(signal, "tp1", 0.0), getattr(signal, "tp2", 0.0), getattr(signal, "sl", 0.0),
                coin.get("ai_score", 0), coin.get("flow_score", 0), coin.get("pre_score", 0),
                coin.get("oi_change", 0), coin.get("rs_1h", 0), compressed, initial_status,
                getattr(signal, "reason", ""), coin.get("probability", 0), coin.get("market_health", 50),
                coin.get("news_score", 50), coin.get("btc_regime", ""), funding, 'ACTIVE',
                tags, shadow_rs, rs_bucket, ai_bucket
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


# =============================================
# פונקציות לפקודות טלגרם (תואמות ל-telegram_commands.py)
# =============================================

def mark_buy_intent(symbol: str):
    """נקרא מ-/buy — מסמן רק את רגע לחיצת הקנייה, לא נוגע ב-entry_price."""
    symbol = symbol.upper().strip()
    candidates = [symbol] if symbol.endswith("USDT") else [symbol, f"{symbol}USDT"]
    now = datetime.now(timezone.utc)
    try:
        with _conn() as c:
            for cand in candidates:
                row = c.execute("""
                    SELECT id FROM shadow_trades
                    WHERE symbol = ? AND outcome_status IN ('PENDING', 'ACTIVE')
                    ORDER BY id DESC LIMIT 1
                """, (cand,)).fetchone()
                if row:
                    c.execute("UPDATE shadow_trades SET buy_intent_time = ? WHERE id = ?",
                              (now.isoformat(), row["id"]))
                    log.info(f"Buy intent marked for {symbol}")
                    export_shadow_csv()
                    return
            log.warning(f"No open trade found for {symbol} to mark buy intent")
    except Exception as e:
        log.error(f"mark_buy_intent failed for {symbol}: {e}")


def confirm_manual_execution(symbol: str, actual_fill_price: float,
                             executed: bool = True, skip_reason: str = None):
    """נקרא מ-/done או /skip — לפי symbol."""
    symbol = symbol.upper().strip()
    candidates = [symbol] if symbol.endswith("USDT") else [symbol, f"{symbol}USDT"]
    now = datetime.now(timezone.utc)

    try:
        with _conn() as c:
            row = None
            for cand in candidates:
                row = c.execute("""
                    SELECT id, ts, entry_price, buy_intent_time FROM shadow_trades
                    WHERE symbol = ? AND outcome_status IN ('PENDING', 'ACTIVE')
                    ORDER BY id DESC LIMIT 1
                """, (cand,)).fetchone()
                if row:
                    break

            if not row:
                log.warning(f"confirm_manual_execution: no open signal found for {symbol}")
                return

            ref_ts = row["buy_intent_time"] or row["ts"]
            ref_dt = datetime.fromisoformat(ref_ts)
            delay_sec = (now - ref_dt).total_seconds()

            slippage_pct = None
            if executed and row["entry_price"] and row["entry_price"] > 0:
                slippage_pct = round(
                    (actual_fill_price - row["entry_price"]) / row["entry_price"] * 100, 3
                )

            c.execute("""
                UPDATE shadow_trades
                SET was_executed = ?,
                    execution_timestamp = ?,
                    actual_fill_price = ?,
                    execution_delay_sec = ?,
                    entry_slippage_pct = ?,
                    skip_reason = ?
                WHERE id = ?
            """, (
                1 if executed else 0,
                now.isoformat(),
                actual_fill_price if executed else None,
                delay_sec,
                slippage_pct,
                skip_reason if not executed else None,
                row["id"]
            ))
        log.info(f"{symbol}: executed={executed}, delay={delay_sec:.0f}s, slippage={slippage_pct}%")
        export_shadow_csv()
    except Exception as e:
        log.error(f"confirm_manual_execution failed for {symbol}: {e}")


# =============================================
# CSV Export
# =============================================

def export_shadow_csv():
    filepath = "shadow_results.csv"
    try:
        with _conn() as c:
            trades = c.execute("SELECT * FROM shadow_trades").fetchall()
            if not trades:
                return
            keys = trades[0].keys()
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(keys)
                for t in trades:
                    writer.writerow([t[k] for k in keys])
    except Exception as e:
        log.error(f"export_shadow_csv failed: {e}")


# =============================================
# Exit Alerts Logic (מנגנון התראות חי)
# =============================================

def check_and_alert_exits():
    """
    בודק עסקאות פעילות שבוצעו בפועל (was_executed=1) ומתריע במקרה של חציית TP/SL.
    שולף מחירים בזמן אמת ושולח התראה לטלגרם פעם אחת בלבד.
    """
    try:
        # ייבוא פנימי כדי למנוע מעגליות
        from scanner.market_data import get_candles
        from notifier.sender import send_simple_message
    except ImportError as e:
        log.error(f"Cannot import dependencies for check_and_alert_exits: {e}")
        return

    try:
        with _conn() as c:
            # שולפים רק עסקאות פעילות שבוצעו
            trades = c.execute("""
                SELECT id, symbol, direction, tp1, tp2, sl,
                       tp1_alert_sent, tp2_alert_sent, sl_alert_sent
                FROM shadow_trades
                WHERE was_executed = 1
                  AND trade_state = 'ACTIVE'
            """).fetchall()

            if not trades:
                return

            for trade in trades:
                symbol = trade["symbol"]
                
                # משיכת מחיר עדכני למטבע (1m candle)
                df = get_candles(symbol, "1m", limit=1)
                if df is None or len(df) == 0:
                    continue
                    
                current_price = float(df["close"].iloc[-1])
                direction = trade["direction"] or "LONG"
                t_id = trade["id"]

                updates = []
                alert_msg = None

                # --- בדיקות לעסקאות LONG ---
                if direction == "LONG":
                    if trade["sl"] and current_price <= trade["sl"] and not trade["sl_alert_sent"]:
                        alert_msg = f"🚨 <b>{symbol}</b> hit Stop Loss!\nPrice: {current_price:.4f}"
                        updates.append("sl_alert_sent = 1")
                    elif trade["tp2"] and current_price >= trade["tp2"] and not trade["tp2_alert_sent"]:
                        alert_msg = f"🎯🎯 <b>{symbol}</b> hit TP2!\nPrice: {current_price:.4f}"
                        updates.append("tp2_alert_sent = 1")
                        # סגירת TP1 אם קפץ ישר ל-TP2
                        if not trade["tp1_alert_sent"]:
                            updates.append("tp1_alert_sent = 1")
                    elif trade["tp1"] and current_price >= trade["tp1"] and not trade["tp1_alert_sent"]:
                        alert_msg = f"🎯 <b>{symbol}</b> hit TP1!\nPrice: {current_price:.4f}"
                        updates.append("tp1_alert_sent = 1")

                # --- בדיקות לעסקאות SHORT ---
                elif direction == "SHORT":
                    if trade["sl"] and current_price >= trade["sl"] and not trade["sl_alert_sent"]:
                        alert_msg = f"🚨 <b>{symbol}</b> hit Stop Loss!\nPrice: {current_price:.4f}"
                        updates.append("sl_alert_sent = 1")
                    elif trade["tp2"] and current_price <= trade["tp2"] and not trade["tp2_alert_sent"]:
                        alert_msg = f"🎯🎯 <b>{symbol}</b> hit TP2!\nPrice: {current_price:.4f}"
                        updates.append("tp2_alert_sent = 1")
                        if not trade["tp1_alert_sent"]:
                            updates.append("tp1_alert_sent = 1")
                    elif trade["tp1"] and current_price <= trade["tp1"] and not trade["tp1_alert_sent"]:
                        alert_msg = f"🎯 <b>{symbol}</b> hit TP1!\nPrice: {current_price:.4f}"
                        updates.append("tp1_alert_sent = 1")

                # --- שליחה ועדכון ---
                if alert_msg and updates:
                    send_simple_message(alert_msg)
                    set_clause = ", ".join(updates)
                    c.execute(f"UPDATE shadow_trades SET {set_clause} WHERE id = ?", (t_id,))
                    log.info(f"Exit alert sent and DB updated for {symbol} (ID: {t_id}): {alert_msg}")

            export_shadow_csv()

    except Exception as e:
        log.error(f"Failed in check_and_alert_exits: {e}", exc_info=True)
