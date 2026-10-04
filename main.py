"""
CRYPTO-BOT Elite — Main Loop (v3.1 with Investment Advisor)
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

# ── Expected Moves (Investment Advisor) ───────────────────────────────────────
try:
    from scanner.expected_moves import get_expected_stats, format_expected_move
    _HAS_EXPECTED_MOVES = True
except ImportError:
    _HAS_EXPECTED_MOVES = False
    def get_expected_stats(*args, **kwargs):
        return None
    def format_expected_move(*args, **kwargs):
        return ""

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
live_monitor = None
if not IS_GITHUB_ACTIONS:
    live_monitor = LiveMonitor(trade_mgr, send_simple_message)
    live_monitor.start()

# ── Global WebSocket Monitors Dictionary ──────────────────────────────────────
ws_monitors = {}


def _confidence_from_ai(ai_score: float) -> str:
    """Map AI score to confidence level (research-only label)."""
    try:
        ai = float(ai_score or 0)
    except (TypeError, ValueError):
        ai = 0.0
    if ai >= 75:
        return "HIGH"
    elif ai >= 60:
        return "MEDIUM"
    else:
        return "LOW"


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


def _format_candidate(idx: int, coin: dict) -> list:
    """Format a single AI≥60 candidate for Telegram."""
    lines = []
    sym = coin.get('symbol', '').replace('USDT', '')
    ai = coin.get('ai_score', 0)
    setup = coin.get('entry_setup', 'UNKNOWN')
    decision = coin.get('entry_decision', 'NO')
    confidence = _confidence_from_ai(ai)

    emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, "•")
    lines.append(f"{emoji} #{idx} {sym}")
    lines.append(f"   AI: {ai:.0f} | Confidence: {confidence}")
    lines.append(f"   Setup: {setup} | Decision: {decision}")

    entry = coin.get('entry_price', 0)
    sl = coin.get('entry_sl', 0)
    tp1 = coin.get('entry_tp1', 0)
    tp2 = coin.get('entry_tp2', 0)
    rr = coin.get('entry_rr', 0)
    trigger = coin.get('trigger_price')
    trigger_src = coin.get('trigger_source', 'unknown')

    if entry > 0:
        lines.append(f"   🟢 Entry: {entry:.4f}")
        lines.append(f"   🛡 Stop: {sl:.4f}")
        lines.append(f"   🎯 TP1: {tp1:.4f} | TP2: {tp2:.4f}")
        lines.append(f"   ⚖️ R:R = {rr:.2f}")
        if trigger and trigger > 0:
            lines.append(f"   🔔 Trigger: {trigger:.4f} ({trigger_src})")

    # Expected stats from historical data
    if _HAS_EXPECTED_MOVES:
        try:
            stats = get_expected_stats(ai, setup)
            if stats:
                expected_text = format_expected_move(stats)
                if expected_text:
                    lines.append("")
                    lines.append(expected_text)
        except Exception as e:
            log.debug(f"Expected stats error for {sym}: {e}")

    return lines


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
                (float(btc_df["close"].iloc[-1]) - float(btc_df["close"].iloc[-2]))
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
        send_simple_message("⚠️ CRYPTO-BOT DATA ERROR: Empty universe — no coins to scan")
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
        trigger_price = c.get("trigger_price")

        if last_price > 0 and trigger_price is not None and trigger_price > 0:
            c["trigger_distance_pct"] = ((trigger_price - last_price) / last_price) * 100
        else:
            c["trigger_distance_pct"] = None

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

    # ══════════════════════════════════════════════════════════════════════════
    # ── 7. INVESTMENT ADVISOR – רק AI≥60, Top 3, ללא Probability ─────────────
    # ══════════════════════════════════════════════════════════════════════════

    # Filter candidates: AI ≥ 60 AND (BUY or WAIT) AND valid entry
    ai_60_plus = [
        c for c in top
        if c.get("ai_score", 0) >= 60
        and c.get("entry_decision") in ("BUY", "WAIT")
        and c.get("entry_price", 0) > 0
    ]

    # Sort by AI score (highest first)
    ai_60_plus.sort(key=lambda x: x.get("ai_score", 0), reverse=True)
    top_3 = ai_60_plus[:3]

    lines = []
    lines.append("🧠 *INVESTMENT ADVISOR*")
    lines.append("")
    lines.append(f"📊 שוק: {market_health:.0f}/100")
    lines.append(f"🌐 Regime: {regime}")
    lines.append(f"🛡 Trading: {circuit_breaker.status()}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if not top_3:
        lines.append("")
        lines.append("🚫 *NO TRADE*")
        lines.append("")
        lines.append("אין כרגע מטבע שעובר את רף האיכות (AI≥60).")
        lines.append("")
        lines.append("אל תקנה מטבע רק כי הוא נמצא בראש הדירוג.")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("📌 *סטטיסטיקה כללית:*")
        if top:
            top_5_syms = ', '.join([c['symbol'].replace('USDT','') for c in top[:5]])
            lines.append(f"   • 5 מובילים בדירוג (AI<60): {top_5_syms}")
        lines.append(f"   • Market Health: {market_health:.0f}/100")
    else:
        for i, c in enumerate(top_3, 1):
            lines.append("")
            candidate_lines = _format_candidate(i, c)
            lines.extend(candidate_lines)
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")

        # Add "no more candidates" if less than 3
        if len(top_3) < 3:
            lines.append("")
            lines.append(f"ℹ️ אין מועמד נוסף עם AI≥60 (נמצאו {len(top_3)}).")

        lines.append("")
        lines.append("💰 *כסף אמיתי:*")
        lines.append("❌ עדיין לא")
        lines.append("")
        lines.append("סיבה:")
        lines.append("אין מספיק היסטוריית AI≥60 מאומתת.")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    send_simple_message("\n".join(lines))

    # ── 8. Learning & Shadow ──────────────────────────────────────────────────
    try:
        from learning.recorder import record_scan
        record_scan(_diag, top)
    except Exception as e:
        log.debug(f"Learning recorder skipped: {e}")

    # ── 9. הבטחת נרות לכל העסקאות הפתוחות ────────────────────────────────────
    try:
        from tools.ensure_open_trade_candles import ensure_candles_for_open_trades
        ensure_candles_for_open_trades()
    except Exception as e:
        log.error(f"Ensure candles error: {e}", exc_info=True)

    # ── 10. Outcome Tracking ──────────────────────────────────────────────────
    try:
        from tools.outcome_tracker import update_outcomes
        updated = update_outcomes()
        log.info(f"Outcome tracker updated {updated} trades")
    except Exception as e:
        log.error(f"Outcome tracker error: {e}", exc_info=True)

    # ── 10b. Backfill RS/AI buckets ───────────────────────────────────────────
    try:
        from tools.backfill_buckets import backfill
        backfill()
    except Exception as e:
        log.error(f"Backfill error: {e}", exc_info=True)

    # ── 10c. Multi-Day Research (Shadow Mode) ────────────────────────────────
    try:
        from scanner.multiday_outcome import update_multiday_outcomes
        update_multiday_outcomes()
    except Exception as e:
        log.error(f"Multi-Day outcome update error: {e}", exc_info=True)

    try:
        from scanner.multiday_engine import run_multiday_scan
        signals = run_multiday_scan(symbols)
        if signals:
            log.info(f"Multi-Day scan generated {len(signals)} research signals (Shadow mode)")
    except Exception as e:
        log.error(f"Multi-Day scan error: {e}", exc_info=True)

    try:
        from tools.multiday_dashboard import run_multiday_dashboard
        md_dash = run_multiday_dashboard()
        if md_dash:
            log.info(md_dash)
    except Exception as e:
        log.debug(f"Multi-Day dashboard skipped: {e}")

    # ── 11. Export ML Learning Dataset ────────────────────────────────────────
    try:
        from tools.export_learning_dataset import export_ml_dataset
        export_ml_dataset()
    except Exception as e:
        log.error(f"ML Dataset export error: {e}", exc_info=True)

    # ── 12. Learning Dashboard ────────────────────────────────────────────────
    try:
        from tools.learning_dashboard import run_dashboard
        lr = run_dashboard()
        if lr:
            log.info(lr)
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
