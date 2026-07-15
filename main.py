"""
CRYPTO-BOT Elite — Main Loop (v3.0 with Live Monitor, ARM State, Circuit Breaker)
"""
import time, signal, sys, argparse

from scanner.universe           import build_universe
from scanner.dynamic_universe   import build_dynamic_universe
from scanner.market_data        import get_candles
from scanner.ranking            import rank_universe
from notifier.sender            import send_telegram
from utils.config               import SCAN_INTERVAL_SECONDS, USE_DYNAMIC_UNIVERSE
from utils.logger               import get_logger

# ── News & Event Engines ──────────────────────────────────────────────────────
from scanner.news_engine      import get_market_health, get_news_score
from scanner.event_engine     import trading_disabled, get_event_warning

# ── Circuit Breaker, Trade Quality, Trade Replay ──────────────────────────────
from portfolio.circuit_breaker import CircuitBreaker
from scanner.trade_quality     import calc_trade_quality
from storage.trade_replay      import init_replay_db, save_snapshot

# ── Live Monitor ──────────────────────────────────────────────────────────────
from monitor.live_monitor      import LiveMonitor

log = get_logger("main")

_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal — stopping after current scan")
    _running = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Trade Manager Global ──────────────────────────────────────────────────────
from scanner.trade_manager import TradeManager

trade_mgr = TradeManager(portfolio_capital=500.0, max_trades=2)

# ── Circuit Breaker ───────────────────────────────────────────────────────────
circuit_breaker = CircuitBreaker()

# ── Init Trade Replay DB ──────────────────────────────────────────────────────
init_replay_db()

# ── Live Monitor ──────────────────────────────────────────────────────────────
def _send_telegram_safe(msg: str):
    """שליחת הודעה לטלגרם בצורה בטוחה."""
    try:
        send_telegram([{"msg": msg}])
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

live_monitor = LiveMonitor(trade_mgr, _send_telegram_safe)
live_monitor.start()


def _trade_open_message(trade) -> str:
    """צור הודעת פתיחת עסקה לטלגרם."""
    quality = getattr(trade, 'quality', 0)
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
    """צור הודעת סגירת עסקה."""
    return (
        f"🔴 EXIT {trade.symbol} @ {action['price']:.4f}\n"
        f"Reason: {action['reason']}\n"
        f"PnL: {action['pnl']:.2f}$ ({action['pnl_pct']:.2f}%)\n"
        f"Circuit Breaker: {circuit_breaker.status()}"
    )

def _trade_partial_message(trade, action: dict) -> str:
    """צור הודעת מימוש חלקי."""
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

    # ── 1. Universe ───────────────────────────────────────────────────────────
    btc_1h_mov = 0.0
    
    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        btc_df     = get_candles("BTCUSDT", "1hour", limit=3)
        if btc_df is not None and len(btc_df) >= 2:
            btc_1h_mov = (float(btc_df["close"].iloc[-1]) - float(btc_df["close"].iloc[-2])) \
                         / float(btc_df["close"].iloc[-2]) * 100
        symbols = build_dynamic_universe(btc_1h_move=btc_1h_mov)
    else:
        log.info("Mode: Static Universe")
        symbols = build_universe()

    if not symbols:
        log.error("Empty universe — skipping scan")
        return

    # ── 2. Score & Rank ───────────────────────────────────────────────────────
    result = rank_universe(symbols)
    top, _diag = result if isinstance(result, tuple) else (result, None)
    if not top:
        log.warning("No coins passed scoring — sending 'no signal' message")
        send_telegram([], stats=_diag)
        return

    # ── Market Health & Event Check ───────────────────────────────────────────
    if _diag is not None:
        if hasattr(_diag, 'get'):
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
        regime=regime
    )
    
    # הוספת market_health לכל מטבע לשימוש ב-ARM
    for c in top:
        c["market_health"] = market_health
    
    health_msg = f"Market Health: {market_health:.0f}/100 | News Score: {news_score} | Regime: {regime} | Circuit Breaker: {circuit_breaker.status()}"
    send_telegram([{"msg": health_msg}])
    
    # בדיקת אירועים קרובים
    original_max = None
    if trading_disabled():
        log.warning("Trading disabled due to high impact event")
        send_telegram([{"msg": get_event_warning()}])
        original_max = trade_mgr.max_trades
        trade_mgr.max_trades = 0

    # ── 3. Decision Engine ────────────────────────────────────────────────────
    from scanner.decision_engine import decide_batch
    top = decide_batch(top)

    # ── 4. Quality Gate (legacy) ──────────────────────────────────────────────
    from scanner.quality_gate import apply_quality_gate_all
    top = apply_quality_gate_all(top)

    # ── Compute trigger distance for ARM classification ───────────────────────
    for c in top:
        last_price = c.get("last_price", 0)
        trigger_price = c.get("trigger_price", c.get("entry_price", 0))
        if last_price > 0 and trigger_price > 0:
            c["trigger_distance_pct"] = ((trigger_price - last_price) / last_price) * 100
        else:
            c["trigger_distance_pct"] = 999
        # וודא ש-trigger_price שמור (למקרה שלא קיים)
        if "trigger_price" not in c and trigger_price > 0:
            c["trigger_price"] = trigger_price
    # ──────────────────────────────────────────────────────────────────────────

    # ── 5. Signal Filter (כולל ARM) ──────────────────────────────────────────
    from scanner.signal_filter import filter_coins
    filtered = filter_coins(top)

    log.info(f"TOP COINS BEFORE FILTER = {len(top)}")
    for c in top[:10]:
        log.info(
            f"  {c['symbol']:<12} "
            f"score={c.get('final_score',0):.0f} "
            f"flow={c.get('flow_score',0):.0f} "
            f"pre={c.get('pre_score',0):.0f} "
            f"compressed={c.get('is_compressed',False)} "
            f"oi={c.get('oi_change',0):.1f} "
            f"rs={c.get('rs_1h',0):.2f} "
            f"decision={c.get('entry_decision','NO')}"
        )
    
    log.info(
        f"FILTER RESULT → "
        f"BUY={len(filtered.get('buy', []))} "
        f"PREPARE={len(filtered.get('prepare', []))} "
        f"ARM={len(filtered.get('arm', []))} "
        f"WATCH={len(filtered.get('watch', []))}"
    )

    # ── Live Monitor: Priority Queue (Top 5 ARM) ─────────────────────────────
    arm_candidates = filtered.get("arm", [])
    # מיין לפי ציון משולב (Probability + Flow + OI)
    arm_candidates.sort(key=lambda x: (x.get("probability", 0)*0.5 + x.get("flow_score", 0)*0.3 + x.get("oi_change", 0)/10), reverse=True)
    top_arm = arm_candidates[:5]  # max 5
    
    live_monitor.clear_watchlist()  # נקה לפני הוספה
    
    for c in top_arm:
        if "trigger_price" not in c:
            entry = c.get("entry_price", c.get("last_price", 0))
            if entry > 0:
                c["trigger_price"] = entry * 1.001
            else:
                c["trigger_price"] = 0
        live_monitor.add_to_watchlist(c)
        msg = (f"🟠 ARM {c['symbol']}\n"
               f"Trigger: {c['trigger_price']:.5f}\n"
               f"Distance: {c.get('trigger_distance_pct', 0):.2f}%\n"
               f"Probability: {c.get('probability', 0):.1f}%\n"
               f"Flow: {c.get('flow_score', 0):.0f} | OI: {c.get('oi_change', 0):.1f}%")
        _send_telegram_safe(msg)

    # ── 6. Trade Management ───────────────────────────────────────────────────
    # 6a. Open new trades (רק אם Circuit Breaker מאפשר)
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

                # חישוב Trade Quality Score
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
                    msg = _trade_open_message(trade)
                    _send_telegram_safe(msg)
            else:
                log.info(f"Max trades reached, {c['symbol']} put on WATCH (no open slot)")
    else:
        log.warning(f"Circuit Breaker active: {circuit_breaker.status()} — no new trades")

    # 6b. Update existing trades
    active_trades = trade_mgr.get_active_trades()
    for trade in active_trades:
        symbol = trade.symbol
        df_5m = get_candles(symbol, "5m", limit=30)
        df_1h = get_candles(symbol, "1hour", limit=30)
        if df_5m is None or len(df_5m) == 0:
            continue
        current_price = float(df_5m["close"].iloc[-1])

        coin_data = next((x for x in top if x["symbol"] == symbol), None)
        if not coin_data:
            coin_data = {
                "symbol": symbol,
                "rs_1h": 0.0,
                "rs_4h": 0.0,
                "oi_change": 0.0,
                "last_price": current_price,
            }
        else:
            coin_data["last_price"] = current_price

        # ── Trade Replay Snapshot ─────────────────────────────────────────────
        try:
            save_snapshot(trade, coin_data, market_health, news_score, regime)
        except Exception as e:
            log.debug(f"Trade replay save error: {e}")

        action = trade_mgr.update(
            symbol=symbol,
            current_price=current_price,
            coin_data=coin_data,
            df_5m=df_5m,
            df_1h=df_1h,
            market_health=market_health,
            btc_regime=regime
        )
        if action:
            if action["action"] == "SELL_PARTIAL":
                msg = _trade_partial_message(trade, action)
                _send_telegram_safe(msg)
            elif action["action"] == "SELL_ALL":
                msg = _trade_close_message(trade, action)
                _send_telegram_safe(msg)
                # ── Circuit Breaker Update ────────────────────────────────────
                circuit_breaker.update_on_close(action["pnl"], market_health)

    # ── 7. Telegram summary ───────────────────────────────────────────────────
    if filtered.get("has_quality", False):
        send_telegram(top, filtered=filtered, stats=_diag, all_coins=top)
    else:
        log.info("No quality signals — sending diagnostic")
        send_telegram(top, filtered=filtered, stats=_diag, all_coins=top)

    # ── 8. Learning & Shadow ──────────────────────────────────────────────────
    try:
        from learning.recorder import record_scan
        record_scan(_diag, top)
    except Exception as e:
        log.debug(f"Learning recorder skipped: {e}")

    try:
        from tools.shadow_mode import save_shadow_signal, update_forward_returns
        for c in top:
            save_shadow_signal(c, c.get("signal", "IGNORE"))
        update_forward_returns()
        log.info(f"Shadow Mode: saved {len(top)} signals")
    except Exception as e:
        log.debug(f"Shadow Mode skipped: {e}")

    try:
        from tools.score_history import init_score_history, save_score
        init_score_history()
        for c in top:
            save_score(c, c.get("rating", "C"))
    except Exception as e:
        log.debug(f"Score history skipped: {e}")

    # print summary
    for i, c in enumerate(top, 1):
        log.info(
            f"  {i}. {c['symbol']:<12} "
            f"score={c['final_score']:.0f}  "
            f"flow={c.get('flow_score',0):.0f}  "
            f"pre={c.get('pre_score',0):.0f}  "
            f"signal={c.get('signal','?'):<10}  "
            f"entry={c.get('entry_decision','NO')}"
        )

    active_now = trade_mgr.get_active_trades()
    if active_now:
        log.info("── Active Trades ──────────────────────────────────────────")
        for t in active_now:
            quality = getattr(t, 'quality', 0)
            log.info(f"  {t.symbol} | Entry={t.entry_price:.4f} | State={t.state} | "
                     f"SL={t.sl:.4f} | TP1={t.tp1:.4f} | TP2={t.tp2:.4f} | "
                     f"Health={getattr(t, 'health', 0):.0f} | Quality={quality:.0f}")

    # שחזור max_trades
    if original_max is not None:
        trade_mgr.max_trades = original_max


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Single scan and exit (GitHub Actions)")
    args = parser.parse_args()

    log.info(f"CRYPTO-BOT Elite starting | dynamic_universe={USE_DYNAMIC_UNIVERSE}")

    if args.once:
        log.info("Mode: --once")
        run_scan()
        sys.exit(0)

    log.info(f"Mode: loop every {SCAN_INTERVAL_SECONDS}s")
    while _running:
        try:
            run_scan()
        except Exception as e:
            log.error(f"Scan error: {e}", exc_info=True)

        if not _running:
            break

        log.info(f"Sleeping {SCAN_INTERVAL_SECONDS}s...")
        for _ in range(SCAN_INTERVAL_SECONDS):
            if not _running: break
            time.sleep(1)

    live_monitor.stop()
    log.info("CRYPTO-BOT Elite stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
