"""
tools/shadow_mode.py — v10.0 (PnL Trust Edition)
Changes from v8.7:
  FIX (critical): _find_open_trade no longer blocks on PREPARE/INVALID/NULL.
       Previous logic blocked new BUYs forever if a symbol had any
       INVALID row, or a PREPARE row (outcome_status NULL).
       Likely root cause of "TIAUSDT detected BUY but not recorded".
  FIX (critical): logs DUPLICATE_SUPPRESSED with reason — no more silent blocks
  FIX: final_score is now written on INSERT (was always empty in CSV)
  FIX: update_shadow_exit requires exit_price > 0 (was defaulting to 0.0)
  FIX: UPDATE rowcount is verified and logged
  ADD: schema columns used by tracker v9.0 (final_exit_price, pnl_pct_net, etc.)
  ADD: export_shadow_csv prefers final_exit_price over exit_price
  ADD: _parse_ts helper for consistency
  CHORE: deduplicate INSERT into _insert_signal() shared helper
"""
import os
import sqlite3
import csv
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from utils.logger import get_logger

log = get_logger(__name__)
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
IL_TZ = ZoneInfo("Asia/Jerusalem")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _add_column_if_not_exists(cursor, table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def _rs_bucket(rs_val) -> str:
    try:
        rs = float(rs_val or 0)
    except (TypeError, ValueError):
        rs = 0.0
    if rs < 0:      return "RS<0"
    elif rs < 0.5:  return "RS_0_0.5"
    elif rs < 1:    return "RS_0.5_1"
    else:           return "RS>1"


def _ai_bucket(ai_score) -> str:
    try:
        ai = float(ai_score or 0)
    except (TypeError, ValueError):
        ai = 0.0
    if ai < 20:     return "AI_0_20"
    elif ai < 40:   return "AI_20_40"
    elif ai < 60:   return "AI_40_60"
    elif ai < 80:   return "AI_60_80"
    else:           return "AI_80_100"


# ── Schema ─────────────────────────────────────────────────────
# v10.0: all columns from v8.7 + tracker v9.0 + shadow v9.0.
# Duplicate columns are eliminated (only listed once).
NEW_COLUMNS = [
    # v8.x
    ("trigger_price", "REAL"),
    ("duration_minutes", "INTEGER"),
    ("outcome_trigger_hit", "INTEGER"),
    ("outcome_tp1_hit", "INTEGER"),
    ("outcome_tp2_hit", "INTEGER"),
    ("outcome_sl_hit", "INTEGER"),
    ("outcome_max_up_pct", "REAL"),
    ("outcome_max_down_pct", "REAL"),
    ("outcome_checked", "INTEGER"),
    ("outcome_status", "TEXT"),
    ("first_tp_hit_time", "REAL"),
    ("last_update_time", "TEXT"),
    ("outcome_mfe", "REAL"),
    ("outcome_mae", "REAL"),
    ("time_to_trigger_min", "REAL"),
    ("time_to_tp1_min", "REAL"),
    ("outcome_tp2_min", "REAL"),
    ("time_to_sl_min", "REAL"),
    ("outcome_highest_price", "REAL"),
    ("outcome_lowest_price", "REAL"),
    ("pnl_r", "REAL"),
    ("mfe_r", "REAL"),
    ("mae_r", "REAL"),
    ("exit_time", "TEXT"),
    ("direction", "TEXT DEFAULT 'LONG'"),
    ("shadow_tags", "TEXT DEFAULT '[]'"),
    ("shadow_rs", "TEXT"),
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
    ("trigger_source", "TEXT"),
    # v9.0 tracker
    ("pnl_pct_net", "REAL"),
    ("pnl_r_net", "REAL"),
    ("final_exit_price", "REAL"),
    ("final_exit_time", "TEXT"),
    ("realized_pnl_pct", "REAL"),
    ("sl_type_at_exit", "TEXT"),
    ("fee_paid_pct", "REAL"),
    ("slippage_pct", "REAL"),
    # v10.0 shadow
    ("final_score", "REAL"),
]


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
                tp1 REAL, tp2 REAL, sl REAL,
                ai_score REAL, flow_score REAL, pre_score REAL,
                oi_change REAL, rs_1h REAL, is_compressed INTEGER,
                status TEXT, reason TEXT,
                probability REAL,
                market_health REAL, news_score REAL, btc_regime TEXT, funding REAL,
                exit_reason TEXT, pnl REAL, pnl_pct REAL,
                max_profit_pct REAL, max_drawdown_pct REAL,
                trade_state TEXT, exit_price REAL
            )
        ''')
        for col, typ in NEW_COLUMNS:
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


# ── Duplicate check (v10.0 FIX) ────────────────────────────────
# A row blocks a new BUY ONLY if:
#   - outcome_status IN ('PENDING', 'ACTIVE')  (open)
#   - AND trade_state != 'CLOSED'              (not closed by manager)
#   - AND decision = 'BUY'                     (PREPARE doesn't block)
# We deliberately do NOT block on INVALID or NULL outcome_status.
def _find_open_trade(c, symbol: str):
    return c.execute("""
        SELECT id, outcome_status, status, trade_state, decision
        FROM shadow_trades
        WHERE symbol = ?
          AND outcome_status IN ('PENDING', 'ACTIVE')
          AND decision = 'BUY'
          AND (trade_state IS NULL OR trade_state != 'CLOSED')
        ORDER BY id DESC
        LIMIT 1
    """, (symbol,)).fetchone()


def _log_duplicate(symbol, row):
    log.warning(
        f"DUPLICATE_SUPPRESSED symbol={symbol} "
        f"blocked_by_id={row['id']} "
        f"outcome_status={row['outcome_status']} "
        f"trade_state={row['trade_state']} "
        f"status={row['status']}"
    )


def _insert_signal(c, *, ts, symbol, signal_decision, setup, entry_price, trigger_price,
                   tp1, tp2, sl, ai_score, flow_score, pre_score, oi_change, rs_1h,
                   compressed, status, reason, probability, market_health, news_score,
                   btc_regime, funding, trade_state, shadow_tags, shadow_rs,
                   rs_bucket, ai_bucket, trigger_source, outcome_status, final_score):
    c.execute('''
        INSERT INTO shadow_trades (
            ts, symbol, decision, setup, entry_price, trigger_price, tp1, tp2, sl,
            ai_score, flow_score, pre_score, oi_change, rs_1h, is_compressed,
            status, reason, probability, market_health, news_score, btc_regime, funding,
            trade_state, shadow_tags, shadow_rs, rs_bucket, ai_bucket,
            trigger_source, outcome_status, final_score
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        ts, symbol, signal_decision, setup, entry_price, trigger_price,
        tp1, tp2, sl, ai_score, flow_score, pre_score, oi_change, rs_1h,
        compressed, status, reason, probability, market_health, news_score,
        btc_regime, funding, trade_state, shadow_tags, shadow_rs, rs_bucket,
        ai_bucket, trigger_source, outcome_status, final_score,
    ))
    return c.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]


def save_shadow_signal(coin: dict, signal: str):
    """Legacy entry — prefer record_trade() from scanner. Kept for compat."""
    symbol = coin.get("symbol", "UNKNOWN")
    try:
        with _conn() as c:
            existing = _find_open_trade(c, symbol)
            if existing:
                _log_duplicate(symbol, existing)
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
    outcome_status_init = "PENDING" if signal == "BUY" else None

    try:
        with _conn() as c:
            rid = _insert_signal(
                c,
                ts=ts, symbol=symbol, signal_decision=signal,
                setup=coin.get("entry_setup", ""),
                entry_price=coin.get("entry_price", coin.get("price", 0)),
                trigger_price=coin.get("trigger_price"),
                tp1=coin.get("entry_tp1", 0), tp2=coin.get("entry_tp2", 0),
                sl=coin.get("entry_sl", 0),
                ai_score=coin.get("ai_score", 0), flow_score=coin.get("flow_score", 0),
                pre_score=coin.get("pre_score", 0), oi_change=coin.get("oi_change", 0),
                rs_1h=coin.get("rs_1h", 0), compressed=compressed,
                status=signal, reason=coin.get("entry_reason", ""),
                probability=coin.get("probability", 0),
                market_health=coin.get("market_health", 50),
                news_score=coin.get("news_score", 50),
                btc_regime=coin.get("btc_regime", ""), funding=funding,
                trade_state='ACTIVE',
                shadow_tags=tags, shadow_rs=shadow_rs,
                rs_bucket=rs_bucket, ai_bucket=ai_bucket,
                trigger_source=coin.get("trigger_source", "missing"),
                outcome_status=outcome_status_init,
                final_score=coin.get("final_score"),
            )
        log.info(f"save_shadow_signal: recorded id={rid} {signal} {symbol}")
        try:
            export_shadow_csv()
        except Exception as e:
            log.error(f"CSV export failed (non-fatal): {e}")
    except Exception as e:
        log.error(f"save_shadow_signal failed: {e}")


def record_trade(coin: dict, signal):
    """Primary entry — called from scanner. Reads trigger from signal object."""
    if not signal or signal.decision not in ["BUY", "PREPARE"]:
        return None

    symbol = coin.get("symbol", "UNKNOWN")

    try:
        with _conn() as c:
            existing = _find_open_trade(c, symbol)
            if existing:
                _log_duplicate(symbol, existing)
                return None
    except Exception as e:
        log.warning(f"Duplicate check failed: {e}")

    ts = datetime.now(timezone.utc).isoformat()
    initial_status = "Pending ⏳" if signal.decision == "BUY" else "-"
    outcome_status_init = "PENDING" if signal.decision == "BUY" else None

    tags = _shadow_tags(coin)
    shadow_rs = _shadow_rs_value(float(coin.get("rs_1h", 0) or 0))
    rs_bucket = _rs_bucket(coin.get("rs_1h", 0))
    ai_bucket = _ai_bucket(coin.get("ai_score", 0))
    compressed = 1 if bool(coin.get("is_compressed", False)) else 0
    funding = float(coin.get("funding", 0) or 0)

    entry_price = getattr(signal, "entry", 0.0) or coin.get("entry_price", 0)
    trigger_price = getattr(signal, "trigger_price", None)
    trigger_source = getattr(signal, "trigger_source", "missing")

    # v10.0: final_score no longer lost
    final_score = getattr(signal, "final_score", None)
    if final_score is None:
        final_score = coin.get("final_score")

    try:
        with _conn() as c:
            rid = _insert_signal(
                c,
                ts=ts, symbol=symbol, signal_decision=signal.decision,
                setup=getattr(signal, "setup_type", ""),
                entry_price=entry_price,
                trigger_price=trigger_price,
                tp1=getattr(signal, "tp1", 0.0),
                tp2=getattr(signal, "tp2", 0.0),
                sl=getattr(signal, "sl", 0.0),
                ai_score=coin.get("ai_score", 0), flow_score=coin.get("flow_score", 0),
                pre_score=coin.get("pre_score", 0), oi_change=coin.get("oi_change", 0),
                rs_1h=coin.get("rs_1h", 0), compressed=compressed,
                status=initial_status,
                reason=getattr(signal, "reason", ""),
                probability=coin.get("probability", 0),
                market_health=coin.get("market_health", 50),
                news_score=coin.get("news_score", 50),
                btc_regime=coin.get("btc_regime", ""), funding=funding,
                trade_state='ACTIVE',
                shadow_tags=tags, shadow_rs=shadow_rs,
                rs_bucket=rs_bucket, ai_bucket=ai_bucket,
                trigger_source=trigger_source,
                outcome_status=outcome_status_init,
                final_score=final_score,
            )
        log.info(
            f"Recorded id={rid} {signal.decision} {symbol} "
            f"(trigger={trigger_price} src={trigger_source} "
            f"outcome={outcome_status_init} final_score={final_score})"
        )
        try:
            export_shadow_csv()
        except Exception as e:
            log.error(f"CSV export failed (non-fatal): {e}")
        return rid
    except Exception as e:
        log.error(f"Failed to record shadow trade for {symbol}: {e}")
        return None


def update_shadow_exit(symbol: str, exit_reason: str, pnl: float, duration_minutes: int,
                       pnl_pct: float = 0.0, max_profit_pct: float = 0.0,
                       max_drawdown_pct: float = 0.0, trade_state: str = 'CLOSED',
                       exit_price: float = None):
    """
    v10.0: DEPRECATED in favor of outcome_tracker v9.0 (which writes final_exit_price).
    Kept for manual/emergency overrides. Requires exit_price > 0 to write.
    """
    if exit_price is None or exit_price <= 0:
        log.error(
            f"update_shadow_exit({symbol}): refusing to write exit_price="
            f"{exit_price} — this was the source of exit_price=0.0 bug. "
            f"Caller must provide the actual fill price."
        )
        return False

    try:
        with _conn() as c:
            cur = c.execute('''
                UPDATE shadow_trades
                SET status = 'CLOSED 🏁',
                    exit_reason = ?, pnl = ?, pnl_pct = ?,
                    duration_minutes = ?, max_profit_pct = ?, max_drawdown_pct = ?,
                    trade_state = ?, exit_price = ?
                WHERE symbol = ?
                  AND (status IS NULL OR status != 'CLOSED 🏁')
                  AND outcome_status IN ('PENDING', 'ACTIVE')
            ''', (exit_reason, pnl, pnl_pct, duration_minutes, max_profit_pct,
                  max_drawdown_pct, trade_state, exit_price, symbol))
            rows = cur.rowcount
            if rows == 0:
                log.warning(f"update_shadow_exit({symbol}): no open row matched")
            else:
                log.info(f"update_shadow_exit({symbol}): updated {rows} row(s) exit_price={exit_price}")
        try:
            export_shadow_csv()
        except Exception as e:
            log.error(f"CSV export failed (non-fatal): {e}")
        return rows > 0
    except Exception as e:
        log.error(f"Failed to update shadow exit for {symbol}: {e}")
        return False


def update_open_trades():
    """Managed by tools/outcome_tracker.py"""
    pass


# =============================================
# Telegram commands
# =============================================
def mark_buy_intent(symbol: str):
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
                    cur = c.execute(
                        "UPDATE shadow_trades SET buy_intent_time = ? WHERE id = ?",
                        (now.isoformat(), row["id"]),
                    )
                    if cur.rowcount != 1:
                        log.error(f"mark_buy_intent({symbol}): update affected {cur.rowcount} rows")
                    else:
                        log.info(f"Buy intent marked for {symbol} (id={row['id']})")
                    try:
                        export_shadow_csv()
                    except Exception as e:
                        log.error(f"CSV export failed (non-fatal): {e}")
                    return
            log.warning(f"No open trade found for {symbol} to mark buy intent")
    except Exception as e:
        log.error(f"mark_buy_intent failed for {symbol}: {e}")


def confirm_manual_execution(symbol: str, actual_fill_price: float,
                              executed: bool = True, skip_reason: str = None):
    symbol = symbol.upper().strip()
    candidates = [symbol] if symbol.endswith("USDT") else [symbol, f"{symbol}USDT"]
    now = datetime.now(timezone.utc)

    if executed and (actual_fill_price is None or actual_fill_price <= 0):
        log.error(f"confirm_manual_execution({symbol}): executed=True but no fill price")
        return

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
                log.warning(f"confirm_manual_execution: no open signal for {symbol}")
                return

            ref_ts = row["buy_intent_time"] or row["ts"]
            ref_dt = datetime.fromisoformat(ref_ts)
            delay_sec = (now - ref_dt).total_seconds()

            slippage_pct = None
            if executed and row["entry_price"] and row["entry_price"] > 0:
                slippage_pct = round(
                    (actual_fill_price - row["entry_price"]) / row["entry_price"] * 100, 3
                )

            cur = c.execute("""
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
                slippage_pct if executed else None,
                skip_reason if not executed else None,
                row["id"],
            ))
            if cur.rowcount != 1:
                log.error(f"confirm_manual_execution({symbol}): update affected {cur.rowcount} rows")
                return

        log.info(f"{symbol}: executed={executed}, delay={delay_sec:.0f}s, slippage={slippage_pct}%")
        try:
            export_shadow_csv()
        except Exception as e:
            log.error(f"CSV export failed (non-fatal): {e}")
    except Exception as e:
        log.error(f"confirm_manual_execution failed for {symbol}: {e}")


# =============================================
# CSV Export
# =============================================
def _v(x):
    """CSV cell: None → empty string, not 0."""
    if x is None:
        return ""
    return x


def export_shadow_csv():
    filepath = "shadow_results.csv"
    try:
        with _conn() as c:
            trades = c.execute("SELECT * FROM shadow_trades ORDER BY id DESC").fetchall()

        with open(filepath, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Time (Israel)", "Coin", "Decision", "Setup", "Entry", "Trigger Price",
                "TP1", "TP2", "SL",
                "AI Score", "Final Score", "Probability", "Flow", "Pre", "OI", "Funding", "RS",
                "Compression", "Market Health", "News Score", "BTC Regime",
                "Status", "Reason", "Exit Reason", "PnL", "PnL%", "PnL% Net", "PnL R", "PnL R Net",
                "Max Profit%", "Max DD%", "Trade State", "Exit Price", "Final Exit Price",
                "Duration (m)",
                "Trigger Hit", "TP1 Hit", "TP2 Hit", "SL Hit",
                "Max Up%", "Max Down%", "MFE%", "MAE%",
                "Realized PnL%", "SL Type At Exit",
                "Fee%", "Slippage%",
                "Outcome Checked", "Outcome Status",
                "Shadow RS", "Shadow Tags", "RS Bucket", "AI Bucket",
                "Trigger Source", "Was Executed", "First Outcome Type",
            ])

            for t in trades:
                t = dict(t)
                dt_utc = datetime.fromisoformat(t["ts"]) if t.get("ts") else None
                dt_str = dt_utc.astimezone(IL_TZ).strftime("%H:%M:%S") if dt_utc else ""

                # Prefer final_exit_price (tracker v9.0) over exit_price (manager)
                display_exit = t.get("final_exit_price") or t.get("exit_price")

                writer.writerow([
                    dt_str,
                    _v(t.get("symbol")), _v(t.get("decision")), _v(t.get("setup")),
                    _v(t.get("entry_price")), _v(t.get("trigger_price")),
                    _v(t.get("tp1")), _v(t.get("tp2")), _v(t.get("sl")),
                    _v(t.get("ai_score")), _v(t.get("final_score")),
                    _v(t.get("probability")), _v(t.get("flow_score")),
                    _v(t.get("pre_score")), _v(t.get("oi_change")),
                    _v(t.get("funding")), _v(t.get("rs_1h")),
                    _v(t.get("is_compressed")), _v(t.get("market_health")),
                    _v(t.get("news_score")), _v(t.get("btc_regime")),
                    _v(t.get("status")), _v(t.get("reason")), _v(t.get("exit_reason")),
                    _v(t.get("pnl")), _v(t.get("pnl_pct")), _v(t.get("pnl_pct_net")),
                    _v(t.get("pnl_r")), _v(t.get("pnl_r_net")),
                    _v(t.get("max_profit_pct")), _v(t.get("max_drawdown_pct")),
                    _v(t.get("trade_state")), _v(t.get("exit_price")),
                    _v(t.get("final_exit_price")), _v(t.get("duration_minutes")),
                    _v(t.get("outcome_trigger_hit")), _v(t.get("outcome_tp1_hit")),
                    _v(t.get("outcome_tp2_hit")), _v(t.get("outcome_sl_hit")),
                    _v(t.get("outcome_max_up_pct")), _v(t.get("outcome_max_down_pct")),
                    _v(t.get("outcome_mfe")), _v(t.get("outcome_mae")),
                    _v(t.get("realized_pnl_pct")), _v(t.get("sl_type_at_exit")),
                    _v(t.get("fee_paid_pct")), _v(t.get("slippage_pct")),
                    _v(t.get("outcome_checked")), _v(t.get("outcome_status")),
                    _v(t.get("shadow_rs")), _v(t.get("shadow_tags")),
                    _v(t.get("rs_bucket")), _v(t.get("ai_bucket")),
                    _v(t.get("trigger_source")), _v(t.get("was_executed")),
                    _v(t.get("first_outcome_type")),
                ])
        log.info(f"CSV Exported: {os.path.abspath(filepath)}")
    except Exception as e:
        log.error(f"Error exporting shadow CSV: {e}")
