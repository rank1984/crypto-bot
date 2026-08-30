"""
CRYPTO-BOT Elite — Main Loop (v3.0 with Live Monitor, ARM State, Circuit Breaker, Trending Bonus & Dashboards)
"""

import argparse
import os
import signal
import sys
import time

from notifier.sender import send_simple_message
from scanner.dynamic_universe import build_dynamic_universe
from scanner.market_data import get_candles
from scanner.ranking import rank_universe
from scanner.universe import build_universe
from utils.config import SCAN_INTERVAL_SECONDS, USE_DYNAMIC_UNIVERSE
from utils.logger import get_logger

# ── News & Event Engines ──────────────────────────────────────────────────────
from scanner.event_engine import get_event_warning, trading_disabled
from scanner.news_engine import get_market_health, get_news_score

# ── שדרוג א: ייבוא מנוע הטרנדינג של CoinGecko ─────────────────────────────────
from engines.alt_data import get_coingecko_trending, trending_bonus

# ── Circuit Breaker, Trade Quality, Trade Replay ──────────────────────────────
from portfolio.circuit_breaker import CircuitBreaker
from scanner.trade_quality import calc_trade_quality
from storage.trade_replay import init_replay_db, save_snapshot

# ── Live Monitor ──────────────────────────────────────────────────────────────
from monitor.live_monitor import LiveMonitor

log = get_logger("main")

_running = True


def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal — stopping after current scan")
    _running = False


# GitHub Actions / Windows compatibility safe signals
try:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
except Exception:
    pass

# ── Trade Manager Global ──────────────────────────────────────────────────────
from scanner.trade_manager import TradeManager

trade_mgr = TradeManager(portfolio_capital=500.0, max_trades=2)

# ── Circuit Breaker ───────────────────────────────────────────────────────────
circuit_breaker = CircuitBreaker()

# ── Init Trade Replay DB ──────────────────────────────────────────────────────
init_replay_db()

# ── GitHub Actions Detection ──────────────────────────────────────────────────
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"

# ── Live Monitor ──────────────────────────────────────────────────────────────
# מפעילים את Monitor רק אם זו הרצה מקומית, ולא ב-GitHub Actions
live_monitor = None
if not IS_GITHUB_ACTIONS:
    live_monitor = LiveMonitor(trade_mgr, send_simple_message)
    live_monitor.start()

# ── Global WebSocket Monitors Dictionary ──────────────────────────────────────
ws_monitors = {}


def _trade_open_message(trade) -> str:
    quality = getattr(trade, "quality", 0)
    return (
        f"🟢 BUY {trade.symbol}\n"
        f"Entry: {trade.entry_price:.4f}\n"
        f"SL: {trade.sl:.4f}\n"
        f"TP1: {trade.tp1:.4f}\n"
        f"TP2: {trade.tp2:.4f}\n"
        f"Size: {trade.position_size:.4f} ({trade.initial_capital:.2f}$)\n"
        f"Quality: {quality:.0f}/100"
    )


def _trade_close_message(trade, action: dict) -> str:
    return (
        f"🔴 EXIT {trade.symbol} @ {action['price']:.4f}\n"
        f"Reason: {action['reason']}\n"
        f"PnL: {action['pnl']:.2f}$ ({action['pnl_pct']:.2f}%)\n"
        f"Circuit Breaker: {circuit_breaker.status()}"
    )


def _trade_partial_message(trade, action: dict) -> str:
    return (
        f"🟡 TP {action.get('tp','PARTIAL')} {trade.symbol}\n"
        f"Price: {action['price']:.4f}\n"
        f"Sold: {action['ratio']*100:.0f}%"
    )


def run_scan() -> None:
    log.info("── Scan started ──────────────────────────────────────")

    # ── 0. Init Databases ─────────────────────────────────────────────────────
    try:
        from tools.shadow_mode import init_shadow_db
        init_shadow_db()
    except Exception as e:
        log.warning(f"Shadow DB init error: {e}")

    try:
        from storage.candle_cache import init_cache
        init_cache()
    except Exception as e:
        log.warning(f"Candle Cache init error: {e}")

    # ── 1. Universe ───────────────────────────────────────────────────────────
    btc_1h_mov = 0.0

    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        btc_df = get_candles("BTCUSDT", "1hour", limit=3)
        if btc_df is not None and len(btc_df) >= 2:
            btc_1h_mov = (
                (
                    float(btc_df["close"].iloc[-1])
                    - float(btc_df["close"].iloc[-2])
                )
                / float(btc_df["close"].iloc[-2])
                * 100
            )
            symbols = build_dynamic_universe(btc_1h_move=btc_1h_mov)
        else:
            symbols = build_universe()
    else:
        log.info("Mode: Static Universe")
        symbols = build_universe()

    if not symbols:
        log.error("Empty universe — skipping scan")
        return

    # ── Market Health (לפני rank_universe) ────────────────────────────────────
    news_score = get_news_score()
    market_health = get_market_health(
        btc_change_1h=btc_1h_mov,
        oi_change_pct=0,
        funding_rate=0.0,
        liquidations=0.0,
        news_score=news_score,
        regime="RANGE",
    )

    import scanner.entry_engine as entry_engine

    entry_engine.GLOBAL_MARKET_HEALTH = market_health
    entry_engine.GLOBAL_NEWS_SCORE = news_score
    entry_engine.GLOBAL_BTC_REGIME = "RANGE"

    # ── 2. Score & Rank ───────────────────────────────────────────────────────
    result = rank_universe(symbols)
    top, _diag = result if isinstance(result, tuple) else (result, None)
    if not top:
        log.warning("No coins passed scoring — sending 'no signal' message")
        send_simple_message("ℹ️ No opportunities found. Market is quiet.")
        return

    # ── חישוב Market Health מחדש ──────────────────────────────────────────────
    if _diag is not None:
        if hasattr(_diag, "get"):
            oi_change_total = _diag.get("total_oi_change", 0)
            regime = _diag.get("regime", "RANGE")
            funding_rate = _diag.get("avg_funding", 0.0)
            liquidations = _diag.get("total_liquidations", 0.0)
        else:
            oi_change_total = getattr(_diag, "total_oi_change", 0)
            regime = getattr(_diag, "regime", "RANGE")
            funding_rate = getattr(_diag, "avg_funding", 0.0)
            liquidations = getattr(_diag, "total_liquidations", 0.0)
    else:
        oi_change_total = 0
        regime = "RANGE"
        funding_rate = 0.0
        liquidations = 0.0

    news_score = get_news_score()
    market_health = get_market_health(
        btc_change_1h=btc_1h_mov,
        oi_change_pct=oi_change_total,
        funding_rate=funding_rate,
        liquidations=liquidations,
        news_score=news_score,
        regime=regime,
    )

    entry_engine.GLOBAL_MARKET_HEALTH = market_health
    entry_engine.GLOBAL_NEWS_SCORE = news_score
    entry_engine.GLOBAL_BTC_REGIME = regime

    for c in top:
        c["market_health"] = market_health
        c["news_score"] = news_score
        c["btc_regime"] = regime

    original_max = None
    if trading_disabled():
        log.warning("Trading disabled due to high impact event")
        send_simple_message(get_event_warning())
        original_max = trade_mgr.max_trades
        trade_mgr.max_trades = 0

    # ── 3. Decision Engine ────────────────────────────────────────────────────
    from scanner.decision_engine import decide_batch
    top = decide_batch(top)

    # ── 4. Quality Gate ───────────────────────────────────────────────────────
    from scanner.quality_gate import apply_quality_gate_all
    top = apply_quality_gate_all(top)

    for c in top:
        if "last_price" not in c or c.get("last_price", 0) == 0:
            fallback = c.get("close", c.get("price", 0))
            if fallback == 0:
                df_tmp = get_candles(c["symbol"], "5m", limit=1)
                if df_tmp is not None and len(df_tmp) > 0:
                    fallback = float(df_tmp["close"].iloc[-1])
            c["last_price"] = fallback

        last_price = c.get("last_price", 0)
        trigger_price = c.get("trigger_price", c.get("entry_price", 0))

        if last_price > 0 and trigger_price and trigger_price > 0:
            c["trigger_distance_pct"] = ((trigger_price - last_price) / last_price) * 100
        else:
            c["trigger_distance_pct"] = None

        if "trigger_price" not in c and trigger_price > 0:
            c["trigger_price"] = trigger_price

    # ── 5. Signal Filter ──────────────────────────────────────────────────────
    from scanner.signal_filter import filter_coins
    filtered = filter_coins(top)

    for c in top:
        c["final_decision"] = c.get("signal", "IGNORE")

    try:
        trending_coins = get_coingecko_trending()
        for c in top:
            c["trending_bonus"] = trending_bonus(c["symbol"], trending_coins)
    except Exception as e:
        log.warning(f"Failed to fetch trending data: {e}")

    log.info(f"TOP COINS BEFORE FILTER = {len(top)}")

    if live_monitor:
        arm_candidates = filtered.get("arm", [])
        arm_candidates.sort(
            key=lambda x: (
                x.get("probability", 0) * 0.5
                + x.get("flow_score", 0) * 0.3
                + x.get("oi_change", 0) / 10
            ),
            reverse=True,
        )
        top_arm = arm_candidates[:5]
        live_monitor.clear_watchlist()
        for c in top_arm:
            if "trigger_price" not in c:
                entry = c.get("entry_price", c.get("last_price", 0))
                c["trigger_price"] = entry * 1.001 if entry > 0 else 0
            live_monitor.add_to_watchlist(c)

    # ── 6. Trade Management ───────────────────────────────────────────────────
    if circuit_breaker.can_trade():
        for c in filtered.get("buy", []):
            if trade_mgr.can_open_trade():
                entry_price = c.get("entry_price", 0)
                sl = c.get("sl", 0)
                tp1 = c.get("tp1", 0)
                tp2 = c.get("tp2", 0)
                current_price = c.get("last_price", 0)

                if entry_price == 0 or current_price == 0:
                    df_5m = get_candles(c["symbol"], "5m", limit=5)
                    if df_5m is not None and len(df_5m) > 0:
                        current_price = float(df_5m["close"].iloc[-1])
                        if entry_price == 0:
                            entry_price = current_price
                if sl == 0:
                    sl = round(entry_price * 0.98, 8)
                if tp1 == 0:
                    tp1 = round(entry_price * 1.04, 8)
                if tp2 == 0:
                    tp2 = round(entry_price * 1.10, 8)
                quality = calc_trade_quality(c, news_score)
                c["trade_quality"] = quality
                signal_data = {
                    "symbol": c["symbol"],
                    "entry": entry_price,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "setup_type": c.get("setup_type", "UNKNOWN"),
                }
                trade = trade_mgr.open_trade(signal_data, entry_price)
                if trade:
                    trade.quality = quality

    # ── 7. הודעה מאוחדת ברורה בעברית ─────────────────────────────────────────
    lines = []
    lines.append("📊 תמונת מצב מהירה")
    lines.append(f"שוק: {market_health:.0f}/100 | חדשות: {news_score} | משטר: {regime}")
    cb_status = circuit_breaker.status()
    lines.append(f"מפסק: {cb_status}")
    lines.append("")

    lines.append("🏆 דירוג 5 מובילים:")
    lines.append("מטבע        AI   הסתברות   מרחק לטריגר")
    lines.append("-" * 44)
    for c in top[:5]:
        sym = c['symbol'].replace('USDT', '')[:12].ljust(12)
        ai = f"{c.get('ai_score', 0):.0f}".rjust(4)
        prob = f"{c.get('probability', 0):.0f}%".rjust(6)
        dist_val = c.get('trigger_distance_pct')
        dist = "—" if dist_val is None else f"{dist_val:.2f}%"
        lines.append(f"{sym}  {ai}  {prob}  {dist}")
    lines.append("")

    buy_list = filtered.get("buy", [])
    if buy_list:
        lines.append("🟢 קנייה מומלצת:")
        for c in buy_list:
            lines.append(f"  {c['symbol']}")
            lines.append(f"    כניסה: {c.get('entry_price', 0):.4f}")
            lines.append(f"    סטופ: {c.get('entry_sl', 0):.4f}")
            lines.append(f"    יעד1: {c.get('entry_tp1', 0):.4f}")
            lines.append(f"    יעד2: {c.get('entry_tp2', 0):.4f}")
        lines.append("")
    else:
        lines.append("🟢 אין קנייה כרגע.")
        lines.append("")

    prepare_list = filtered.get("prepare", [])
    if prepare_list:
        lines.append("🟡 הכנה (PREPARE) – הצטברות טובה, חסר טריגר:")
        for c in prepare_list[:3]:
            lines.append(f"  {c['symbol']} AI:{c.get('ai_score',0):.0f} Prob:{c.get('probability',0):.0f}%")
        lines.append("")

    arm_list = filtered.get("arm", [])
    if arm_list:
        lines.append("🟠 במעקב צמוד (ARM) – קרוב לפריצה:")
        for c in arm_list[:3]:
            dist_val = c.get('trigger_distance_pct')
            dist = f"{dist_val:.2f}%" if dist_val is not None else "—"
            lines.append(f"  {c['symbol']} מרחק:{dist}")
        lines.append("")

    watch_list = filtered.get("watch", [])
    if watch_list:
        lines.append("🟡 במעקב (WATCH):")
        for c in watch_list[:3]:
            lines.append(f"  {c['symbol']} AI:{c.get('ai_score',0):.0f} Prob:{c.get('probability',0):.0f}%")
        lines.append("")

    lines.append("🔹 מה לעשות:")
    lines.append("• 🟢 קנייה – בצע קנייה ידנית אם הכניסה עדיין בתוקף.")
    lines.append("• 🟡 הכנה/מעקב – המתן לפריצה ברורה.")
    lines.append("• 📊 אם השוק חלש (מתחת 50) – עדיף לא לקנות.")
    lines.append("• 🛡 מפסק ACTIVE = מותר לסחור. BLOCKED = אין כניסות חדשות.")

    send_simple_message("\n".join(lines))

    # ── 8. Learning & Shadow ──────────────────────────────────────────────────
    try:
        from learning.recorder import record_scan
        record_scan(_diag, top)
    except Exception as e:
        log.debug(f"Learning recorder skipped: {e}")

    # ── 9. הבטחת נרות לכל העסקאות הפתוחות (לפני outcome tracker) ────────────
    try:
        from tools.ensure_open_trade_candles import ensure_candles_for_open_trades
        ensure_candles_for_open_trades()
    except Exception as e:
        log.error(f"Ensure candles error: {e}", exc_info=True)

    # ── 10. Outcome Tracking (מקור אמת יחיד) ──────────────────────────────────
    try:
        from tools.outcome_tracker import update_outcomes
        updated = update_outcomes()
        log.info(f"Outcome tracker updated {updated} trades")
    except Exception as e:
        log.error(f"Outcome tracker error: {e}", exc_info=True)

    # ── 10b. Backfill RS/AI buckets (לאחר עדכון התוצאות) ─────────────────────
    try:
        from tools.backfill_buckets import backfill
        backfill()
    except Exception as e:
        log.error(f"Backfill error: {e}", exc_info=True)

    # ── 11. Export ML Learning Dataset ─────────────────────────────────────────
    try:
        from tools.export_learning_dataset import export_ml_dataset
        export_ml_dataset()
    except Exception as e:
        log.error(f"ML Dataset export error: {e}", exc_info=True)

    # ── 12. Learning Dashboard (לוג בלבד) ─────────────────────────────────────
    try:
        from tools.learning_dashboard import run_dashboard
        lr = run_dashboard()
        if lr:
            log.info(lr)

        import sqlite3
        conn = sqlite3.connect(os.getenv("DB_PATH", "data/shadow.db"))
        method_counts = conn.execute("""
            SELECT pnl_pct_method, COUNT(*) 
            FROM shadow_trades
            WHERE decision='BUY' AND outcome_status='FINAL' AND outcome_checked=1
            GROUP BY pnl_pct_method
        """).fetchall()
        log.info(f"pnl_pct_method breakdown: {method_counts}")
        conn.close()
    except Exception as e:
        log.error(f"Learning dashboard error: {e}", exc_info=True)

    if original_max is not None:
        trade_mgr.max_trades = original_max


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Single scan and exit")
    args = parser.parse_args()

    run_once = args.once or IS_GITHUB_ACTIONS

    log.info(f"CRYPTO-BOT Elite starting | dynamic_universe={USE_DYNAMIC_UNIVERSE} | GitHubActions={IS_GITHUB_ACTIONS}")

    if run_once:
        log.info("Mode: Single scan execution (--once)")
        run_scan()
        log.info("Scan completed successfully. Exiting.")
        sys.exit(0)

    log.info(f"Mode: Loop every {SCAN_INTERVAL_SECONDS}s")
    while _running:
        try:
            run_scan()
        except Exception as e:
            log.error(f"Scan error: {e}", exc_info=True)

        if not _running:
            break

        time.sleep(SCAN_INTERVAL_SECONDS)

    if live_monitor:
        live_monitor.stop()

    log.info("CRYPTO-BOT Elite stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
