"""
CRYPTO-BOT Elite — Main Loop (v3.2 with Fixed Investment Advisor)
"""
import argparse
import os
import signal
import sys
import time
import sqlite3

from notifier.sender import send_simple_message
from scanner.dynamic_universe import build_dynamic_universe
from scanner.market_data import get_candles
from scanner.ranking import rank_universe
from scanner.universe import build_universe
from utils.config import SCAN_INTERVAL_SECONDS, USE_DYNAMIC_UNIVERSE, DB_PATH
from utils.logger import get_logger

from scanner.event_engine import get_event_warning, trading_disabled
from scanner.news_engine import get_market_health, get_news_score
from engines.alt_data import get_coingecko_trending, trending_bonus
from portfolio.circuit_breaker import CircuitBreaker
from scanner.trade_quality import calc_trade_quality
from storage.trade_replay import init_replay_db, save_snapshot
from monitor.live_monitor import LiveMonitor

try:
    from scanner.expected_moves import get_expected_stats, format_expected_move
    _HAS_EXPECTED_MOVES = True
except ImportError:
    _HAS_EXPECTED_MOVES = False
    def get_expected_stats(*args, **kwargs): return None
    def format_expected_move(*args, **kwargs): return ""

from datetime import datetime, timezone, timedelta

log = get_logger("main")
_running = True


def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal — stopping after current scan")
    _running = False


try:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
except Exception:
    pass

from scanner.trade_manager import TradeManager
trade_mgr = TradeManager(portfolio_capital=500.0, max_trades=2)
circuit_breaker = CircuitBreaker()
init_replay_db()

IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"

live_monitor = None
if not IS_GITHUB_ACTIONS:
    live_monitor = LiveMonitor(trade_mgr, send_simple_message)
    live_monitor.start()

ws_monitors = {}

# ── Advisor constants ────────────────────────────────────────────────
AI_MIN = 60
RECENCY_DAYS = 90
MIN_SAMPLE = 20
MIN_TP1_RATE = 0.25
MIN_AVG_R = 0.0


def _confidence_from_ai(ai_score: float) -> str:
    try:
        ai = float(ai_score or 0)
    except (TypeError, ValueError):
        ai = 0.0
    if ai >= 75:   return "HIGH"
    elif ai >= 60: return "MEDIUM"
    else:          return "LOW"


def _tags(c):
    raw = c.get("shadow_tags", "[]")
    if isinstance(raw, str):
        try:
            import json
            return json.loads(raw)
        except Exception:
            return []
    return raw or []


def _format_candidate(idx: int, coin: dict) -> list:
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
        stop_pct = (entry - sl) / entry * 100 if sl > 0 else 0
        lines.append(f"   🟢 Entry: {entry:.4f}")
        lines.append(f"   🛡 Stop: {sl:.4f} ({stop_pct:.2f}%)")
        lines.append(f"   🎯 TP1: {tp1:.4f} | TP2: {tp2:.4f}")
        lines.append(f"   ⚖️ R:R = {rr:.2f}")
        if trigger and trigger > 0:
            lines.append(f"   🔔 Trigger: {trigger:.4f} ({trigger_src})")

    if _HAS_EXPECTED_MOVES:
        try:
            stats = get_expected_stats(ai, setup)
            if stats:
                txt = format_expected_move(stats)
                if txt:
                    lines.append("")
                    lines.append(txt)
        except Exception as e:
            log.debug(f"Expected stats error for {sym}: {e}")

    return lines


def _advisor_historical_stats():
    """Recent 90d stats for AI>=60 DIP_BUY FINAL trades."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"""
            SELECT
                COUNT(*) as n,
                AVG(pnl_r) as avg_r,
                AVG(CASE WHEN outcome_tp1_hit=1 THEN 1.0 ELSE 0.0 END) as tp1_rate
            FROM shadow_trades
            WHERE decision='BUY'
              AND setup != 'VWAP_RECLAIM'
              AND ai_score >= {AI_MIN}
              AND outcome_status='FINAL'
              AND ts >= '{cutoff}'
        """).fetchone()
        conn.close()
        return {
            "n": (row["n"] or 0),
            "avg_r": (row["avg_r"] or 0.0),
            "tp1_rate": (row["tp1_rate"] or 0.0),
        }
    except Exception as e:
        log.error(f"Advisor historical stats failed: {e}")
        return {"n": 0, "avg_r": 0.0, "tp1_rate": 0.0}


def _advisor_select_candidates(top: list) -> list:
    """Strict filters: DIP_BUY, AI>=60, BUY (not WAIT), trigger confirmed, no regime_bad+RS_LOW."""
    filtered = []
    for c in top:
        if c.get("ai_score", 0) < AI_MIN: continue
        if c.get("entry_decision") != "BUY": continue           # not WAIT
        if c.get("entry_setup") == "VWAP_RECLAIM": continue
        if c.get("entry_price", 0) <= 0: continue
        if (c.get("trigger_price") or 0) <= 0: continue         # trigger required
        tags = _tags(c)
        if "shadow_regime_bad" in tags and "shadow_rs_low" in tags: continue
        filtered.append(c)
    filtered.sort(key=lambda x: x.get("ai_score", 0), reverse=True)
    return filtered[:3]


def run_scan() -> None:
    log.info("── Scan started ──────────────────────────────────────")

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

    btc_1h_mov = 0.0
    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        btc_df = get_candles("BTCUSDT", "1hour", limit=3)
        if btc_df is not None and len(btc_df) >= 2:
            btc_1h_mov = (
                (float(btc_df["close"].iloc[-1]) - float(btc_df["close"].iloc[-2]))
                / float(btc_df["close"].iloc[-2]) * 100
            )
            symbols = build_dynamic_universe(btc_1h_move=btc_1h_mov)
        else:
            symbols = build_universe()
    else:
        log.info("Mode: Static Universe")
        symbols = build_universe()

    if not symbols:
        log.error("Empty universe — skipping scan")
        send_simple_message("⚠️ CRYPTO-BOT DATA ERROR: Empty universe")
        return

    news_score = get_news_score()
    market_health = get_market_health(
        btc_change_1h=btc_1h_mov, oi_change_pct=0, funding_rate=0.0,
        liquidations=0.0, news_score=news_score, regime="RANGE",
    )

    import scanner.entry_engine as entry_engine
    entry_engine.GLOBAL_MARKET_HEALTH = market_health
    entry_engine.GLOBAL_NEWS_SCORE = news_score
    entry_engine.GLOBAL_BTC_REGIME = "RANGE"

    result = rank_universe(symbols)
    top, _diag = result if isinstance(result, tuple) else (result, None)
    if not top:
        log.warning("No coins passed scoring")
        send_simple_message("ℹ️ No opportunities found. Market is quiet.")
        return

    # Recompute market health with diagnostics
    if _diag is not None:
        oi_change_total = getattr(_diag, "total_oi_change", 0) if not hasattr(_diag, "get") else _diag.get("total_oi_change", 0)
        regime = getattr(_diag, "regime", "RANGE") if not hasattr(_diag, "get") else _diag.get("regime", "RANGE")
        funding_rate = getattr(_diag, "avg_funding", 0.0) if not hasattr(_diag, "get") else _diag.get("avg_funding", 0.0)
        liquidations = getattr(_diag, "total_liquidations", 0.0) if not hasattr(_diag, "get") else _diag.get("total_liquidations", 0.0)
    else:
        oi_change_total = 0; regime = "RANGE"; funding_rate = 0.0; liquidations = 0.0

    news_score = get_news_score()
    market_health = get_market_health(
        btc_change_1h=btc_1h_mov, oi_change_pct=oi_change_total,
        funding_rate=funding_rate, liquidations=liquidations,
        news_score=news_score, regime=regime,
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

    from scanner.decision_engine import decide_batch
    top = decide_batch(top)

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

    from scanner.signal_filter import filter_coins
    filtered = filter_coins(top)

    for c in top:
        c["final_decision"] = c.get("signal", "IGNORE")

    try:
        trending_coins = get_coingecko_trending()
        for c in top:
            c["trending_bonus"] = trending_bonus(c["symbol"], trending_coins)
    except Exception as e:
        log.warning(f"Trending data error: {e}")

    log.info(f"TOP COINS = {len(top)}")

    if live_monitor:
        arm_candidates = filtered.get("arm", [])
        arm_candidates.sort(key=lambda x: (x.get("probability",0)*0.5 + x.get("flow_score",0)*0.3 + x.get("oi_change",0)/10), reverse=True)
        live_monitor.clear_watchlist()
        for c in arm_candidates[:5]:
            if "trigger_price" not in c:
                entry = c.get("entry_price", c.get("last_price", 0))
                c["trigger_price"] = entry * 1.001 if entry > 0 else 0
            live_monitor.add_to_watchlist(c)

    if circuit_breaker.can_trade():
        for c in filtered.get("buy", []):
            if trade_mgr.can_open_trade():
                entry_price = c.get("entry_price", 0)
                sl = c.get("sl", 0); tp1 = c.get("tp1", 0); tp2 = c.get("tp2", 0)
                current_price = c.get("last_price", 0)
                if entry_price == 0 or current_price == 0:
                    df_5m = get_candles(c["symbol"], "5m", limit=5)
                    if df_5m is not None and len(df_5m) > 0:
                        current_price = float(df_5m["close"].iloc[-1])
                        if entry_price == 0:
                            entry_price = current_price
                if sl == 0:  sl = round(entry_price * 0.98, 8)
                if tp1 == 0: tp1 = round(entry_price * 1.04, 8)
                if tp2 == 0: tp2 = round(entry_price * 1.10, 8)
                quality = calc_trade_quality(c, news_score)
                c["trade_quality"] = quality
                signal_data = {"symbol": c["symbol"], "entry": entry_price, "sl": sl, "tp1": tp1, "tp2": tp2, "setup_type": c.get("setup_type", "UNKNOWN")}
                trade = trade_mgr.open_trade(signal_data, entry_price)
                if trade:
                    trade.quality = quality

    # ══════════════════════════════════════════════════════════════
    # INVESTMENT ADVISOR v8.7 (Emergency)
    # ══════════════════════════════════════════════════════════════
    hist = _advisor_historical_stats()
    top_3 = _advisor_select_candidates(top)

    no_trade_reason = None
    if hist["n"] < MIN_SAMPLE:
        no_trade_reason = f"מדגם היסטורי קטן מדי (n={hist['n']} < {MIN_SAMPLE})"
    elif hist["avg_r"] <= MIN_AVG_R:
        no_trade_reason = f"Avg R היסטורי שלילי ({hist['avg_r']:.2f})"
    elif hist["tp1_rate"] < MIN_TP1_RATE:
        no_trade_reason = f"TP1 rate נמוך ({hist['tp1_rate']:.0%} < {MIN_TP1_RATE:.0%})"
    elif not top_3:
        no_trade_reason = "אין מועמד DIP_BUY עם AI≥60 וטריגר מאושר (VWAP_RECLAIM חסום)"

    lines = [
        "🧠 *INVESTMENT ADVISOR*", "",
        f"📊 שוק: {market_health:.0f}/100",
        f"🌐 Regime: {regime}",
        f"🛡 Trading: {circuit_breaker.status()}",
        f"📈 היסטוריה (90 יום, AI≥{AI_MIN}): n={hist['n']} | AvgR={hist['avg_r']:.2f} | TP1={hist['tp1_rate']:.0%}",
        "", "━━━━━━━━━━━━━━━━━━━━",
    ]

    if no_trade_reason:
        lines += ["", "🚫 *NO TRADE*", "", no_trade_reason, ""]
        if top:
            top5 = ', '.join(c['symbol'].replace('USDT','') for c in top[:5])
            lines.append(f"📌 5 מובילים בדירוג (לא עוברים את השער): {top5}")
        lines += ["", "אל תקנה מטבע רק כי הוא נמצא בראש הדירוג."]
    else:
        for i, c in enumerate(top_3, 1):
            lines.append("")
            lines.extend(_format_candidate(i, c))
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
        if len(top_3) < 3:
            lines.append("")
            lines.append(f"ℹ️ נמצאו רק {len(top_3)} מועמדים עם AI≥60.")
        lines += ["", "💰 *כסף אמיתי:* ❌ עדיין לא — פיילוט אחרי 72h"]

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    send_simple_message("\n".join(lines))

    # ── Post-scan tasks ────────────────────────────────────────
    try:
        from learning.recorder import record_scan
        record_scan(_diag, top)
    except Exception as e:
        log.debug(f"Learning recorder skipped: {e}")

    try:
        from tools.ensure_open_trade_candles import ensure_candles_for_open_trades
        ensure_candles_for_open_trades()
    except Exception as e:
        log.error(f"Ensure candles error: {e}", exc_info=True)

    try:
        from tools.outcome_tracker import update_outcomes
        updated = update_outcomes()
        log.info(f"Outcome tracker updated {updated} trades")
    except Exception as e:
        log.error(f"Outcome tracker error: {e}", exc_info=True)

    try:
        from tools.backfill_buckets import backfill
        backfill()
    except Exception as e:
        log.error(f"Backfill error: {e}", exc_info=True)

    try:
        from scanner.multiday_outcome import update_multiday_outcomes
        update_multiday_outcomes()
    except Exception as e:
        log.error(f"Multi-Day outcome error: {e}", exc_info=True)

    try:
        from scanner.multiday_engine import run_multiday_scan
        signals = run_multiday_scan(symbols)
        if signals:
            log.info(f"Multi-Day scan: {len(signals)} signals")
    except Exception as e:
        log.error(f"Multi-Day scan error: {e}", exc_info=True)

    try:
        from tools.multiday_dashboard import run_multiday_dashboard
        md = run_multiday_dashboard()
        if md: log.info(md)
    except Exception as e:
        log.debug(f"Multi-Day dashboard skipped: {e}")

    try:
        from tools.export_learning_dataset import export_ml_dataset
        export_ml_dataset()
    except Exception as e:
        log.error(f"ML Dataset error: {e}", exc_info=True)

    try:
        from tools.learning_dashboard import run_dashboard
        lr = run_dashboard()
        if lr: log.info(lr)
    except Exception as e:
        log.error(f"Learning dashboard error: {e}", exc_info=True)

    if original_max is not None:
        trade_mgr.max_trades = original_max


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    run_once = args.once or IS_GITHUB_ACTIONS
    log.info(f"CRYPTO-BOT Elite v8.7 | dynamic_universe={USE_DYNAMIC_UNIVERSE} | GH={IS_GITHUB_ACTIONS}")

    if run_once:
        log.info("Mode: Single scan (--once)")
        run_scan()
        log.info("Scan complete. Exiting.")
        sys.exit(0)

    log.info(f"Mode: Loop every {SCAN_INTERVAL_SECONDS}s")
    while _running:
        try:
            run_scan()
        except Exception as e:
            log.error(f"Scan error: {e}", exc_info=True)
        if not _running: break
        time.sleep(SCAN_INTERVAL_SECONDS)

    if live_monitor: live_monitor.stop()
    log.info("CRYPTO-BOT Elite stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
