"""
CRYPTO-BOT Elite — Main Loop (v3.0 with Live Monitor, ARM State, Circuit Breaker)
"""
import time, signal, sys, argparse

from scanner.universe            import build_universe
from scanner.dynamic_universe    import build_dynamic_universe
from scanner.market_data         import get_candles
from scanner.ranking             import rank_universe
from notifier.sender             import send_simple_message
from utils.config                import SCAN_INTERVAL_SECONDS, USE_DYNAMIC_UNIVERSE
from utils.logger                import get_logger

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
live_monitor = LiveMonitor(trade_mgr, send_simple_message)
live_monitor.start()


def _trade_open_message(trade) -> str:
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

    # ── 1. Universe ───────────────────────────────────────────────────────────
    btc_1h_mov = 0.0

    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        btc_df = get_candles("BTCUSDT", "1hour", limit=3)
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

    # ── Market Health (לפני rank_universe – מחשבים עם ערכי default) ──────────
    news_score = get_news_score()
    market_health = get_market_health(
        btc_change_1h=btc_1h_mov,
        oi_change_pct=0,
        funding_rate=0.0,
        liquidations=0.0,
        news_score=news_score,
        regime="RANGE"
    )

    # עדכון גלובלי ב-entry_engine (לפני rank_universe)
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

    # ── חישוב Market Health מחדש עם נתוני ranking ────────────────────────────
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

    # עדכון גלובלי סופי
    entry_engine.GLOBAL_MARKET_HEALTH = market_health
    entry_engine.GLOBAL_NEWS_SCORE = news_score
    entry_engine.GLOBAL_BTC_REGIME = regime

    # הוספת market_health לכל מטבע
    for c in top:
        c["market_health"] = market_health
        c["news_score"] = news_score
        c["btc_regime"] = regime

    # בדיקת אירועים קרובים
    original_max = None
    if trading_disabled():
        log.warning("Trading disabled due to high impact event")
        send_simple_message(get_event_warning())
        original_max = trade_mgr.max_trades
        trade_mgr.max_trades = 0

    # ── 3. Decision Engine ────────────────────────────────────────────────────
    from scanner.decision_engine import decide_batch
    top = decide_batch(top)

    # ── 4. Quality Gate (legacy) ──────────────────────────────────────────────
    from scanner.quality_gate import apply_quality_gate_all
    top = apply_quality_gate_all(top)

    # ── ודא last_price + trigger_distance_pct ────────────────────────────────
    for c in top:
        # last_price fallback
        if "last_price" not in c or c.get("last_price", 0) == 0:
            fallback = c.get("close", c.get("price", 0))
            if fallback == 0:
                df_tmp = get_candles(c["symbol"], "5m", limit=1)
                if df_tmp is not None and len(df_tmp) > 0:
                    fallback = float(df_tmp["close"].iloc[-1])
            c["last_price"] = fallback

        # trigger distance
        last_price = c.get("last_price", 0)
        trigger_price = c.get("trigger_price", c.get("entry_price", 0))
        if last_price > 0 and trigger_price > 0:
            c["trigger_distance_pct"] = ((trigger_price - last_price) / last_price) * 100
        elif trigger_price > 0:
            c["trigger_distance_pct"] = 0.5
        else:
            c["trigger_distance_pct"] = 999

        if "trigger_price" not in c and trigger_price > 0:
            c["trigger_price"] = trigger_price

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
    arm_candidates.sort(key=lambda x: (x.get("probability", 0)*0.5 + x.get("flow_score", 0)*0.3 + x.get("oi_change", 0)/10), reverse=True)
    top_arm = arm_candidates[:5]

    live_monitor.clear_watchlist()

    for c in top_arm:
        if "trigger_price" not in c:
            entry = c.get("entry_price", c.get("last_price", 0))
            if entry > 0:
                c["trigger_price"] = entry * 1.001
            else:
                c["trigger_price"] = 0
        live_monitor.add_to_watchlist(c)

    # ── 6. Trade Management ───────────────────────────────────────────────────
    # 6a. Open new trades
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
                    # ההודעה תישלח בהודעה המאוחדת בסוף הסריקה
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

        coin_data["market_health"] = market_health
        coin_data["news_score"] = news_score
        coin_data["btc_regime"] = regime

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
                send_simple_message(_trade_partial_message(trade, action))
            elif action["action"] == "SELL_ALL":
                send_simple_message(_trade_close_message(trade, action))
                circuit_breaker.update_on_close(action["pnl"], market_health)

    # ── 7. הודעה מאוחדת בעברית (ייעוץ בלבד) ──────────────────────────────
    lines = []
    
    # כותרת עליונה – המטבע המוביל
    if top:
        leader = top[0]
        lines.append(f"🥇 {leader['symbol']} – המוביל כרגע")
        lines.append(f"   מחיר: {leader.get('price', 0):.5f}  |  "
                     f"בינה: {leader.get('ai_score', 0):.0f}  |  "
                     f"הסתברות: {leader.get('probability', 0):.0f}%")
        if leader.get('trigger_price'):
            lines.append(f"   טריגר: {leader['trigger_price']:.5f}")
        lines.append("")

    # מצב שוק
    lines.append(f"📊 מצב שוק: {market_health:.0f}/100 | חדשות: {news_score} | משטר: {regime}")
    if market_health >= 65:
        lines.append("   ↳ שוק חזק – מותר לסחור.")
    elif market_health >= 40:
        lines.append("   ↳ שוק בינוני – אפשר לסחור בזהירות.")
    else:
        lines.append("   ↳ שוק חלש – עדיף להמתין.")

    # מפסק
    cb_status = circuit_breaker.status()
    lines.append(f"🛡 מפסק: {cb_status}")
    if cb_status != "ACTIVE":
        lines.append(f"   ⚠️ סיבה: {circuit_breaker.block_reason}")
    lines.append("")

    # טבלת 5 מומלצים
    lines.append("📊 דירוג 5 מומלצים:")
    lines.append("┌──────┬──────┬────────┬────────┐")
    lines.append("│ מטבע │ בינה │ הסתברות│ מרחק   │")
    lines.append("├──────┼──────┼────────┼────────┤")
    for c in top[:5]:
        sym = c['symbol'].replace('USDT', '')[:8].ljust(6)
        ai = str(c.get('ai_score', 0)).rjust(4)
        prob = (str(c.get('probability', 0)) + '%').rjust(6)
        dist = f"{c.get('trigger_distance_pct', 0):.2f}%".rjust(6)
        lines.append(f"│ {sym} │ {ai} │ {prob} │ {dist} │")
    lines.append("└──────┴──────┴────────┴────────┘")
    lines.append("")

    # קטגוריות BUY / WATCH / ARM
    buy_list = filtered.get("buy", [])
    if buy_list:
        lines.append("🟢 קניות (BUY) – הבוט ממליץ:")
        for c in buy_list:
            lines.append(f"  {c['symbol']}  כניסה: {c.get('entry_price', 0):.4f}  "
                         f"סטופ: {c.get('entry_sl', 0):.4f}  יעד1: {c.get('entry_tp1', 0):.4f}")
        lines.append("")

    watch_list = filtered.get("watch", [])
    if watch_list:
        lines.append("🟡 במעקב (WATCH) – טרם בשל:")
        for c in watch_list[:3]:
            lines.append(f"  {c['symbol']}  בינה: {c.get('ai_score', 0):.0f}  "
                         f"הסתברות: {c.get('probability', 0):.0f}%")
        lines.append("")

    arm_list = filtered.get("arm", [])
    if arm_list:
        lines.append("🟠 במעקב צמוד (ARM) – קרובים לפריצה:")
        for c in arm_list[:3]:
            lines.append(f"  {c['symbol']}  בינה: {c.get('ai_score', 0):.0f}  "
                         f"הסתברות: {c.get('probability', 0):.0f}%  "
                         f"מרחק: {c.get('trigger_distance_pct', 0):.2f}%")
        lines.append("")

    if not (buy_list or arm_list):
        lines.append("ℹ️ אין כרגע המלצות קנייה.")

    lines.append("")
    lines.append("🔹 מה לעשות עכשיו:")
    lines.append("• ℹ️ הבוט מייעץ – **לא** קונה אוטומטית.")
    lines.append("• 🟢 קניות – מומלץ לקנות ידנית את המטבעות הרשומים.")
    lines.append("• 🟡 במעקב – לא לקנות עדיין. להמתין.")
    lines.append("• 🟠 במעקב צמוד – להתכונן, קרובים לפריצה.")
    lines.append("• 📊 שוק בינוני – מותר לסחור בזהירות.")
    lines.append("• 📋 בדוק טבלת מומלצים למעלה.")

    send_simple_message("\n".join(lines))
watch_list = filtered.get("watch", [])
if watch_list:
    lines.append("🟡 במעקב (WATCH) – טרם בשל:")
    for c in watch_list[:3]:
        lines.append(f"  {c['symbol']}  בינה: {c.get('ai_score', 0):.0f}  "
                     f"הסתברות: {c.get('probability', 0):.0f}%")
    lines.append("")

arm_list = filtered.get("arm", [])
if arm_list:
    lines.append("🟠 במעקב צמוד (ARM) – קרובים לפריצה:")
    for c in arm_list[:3]:
        lines.append(f"  {c['symbol']}  בינה: {c.get('ai_score', 0):.0f}  "
                     f"הסתברות: {c.get('probability', 0):.0f}%  "
                     f"מרחק: {c.get('trigger_distance_pct', 0):.2f}%")
    lines.append("")

if not (buy_list or arm_list):
    lines.append("ℹ️ אין כרגע המלצות קנייה.")

lines.append("")
lines.append("🔹 מה לעשות עכשיו:")
lines.append("• ℹ️ הבוט מייעץ – **לא** קונה אוטומטית.")
lines.append("• 🟢 קניות – מומלץ לקנות ידנית את המטבעות הרשומים.")
lines.append("• 🟡 במעקב – לא לקנות עדיין. להמתין.")
lines.append("• 🟠 במעקב צמוד – להתכונן, קרובים לפריצה.")
lines.append("• 📊 שוק בינוני – מותר לסחור בזהירות.")
lines.append("• 📋 בדוק טבלת מומלצים למעלה.")

send_simple_message("\n".join(lines))
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

    # ── Outcome Tracking ──────────────────────────────────────────────────────
    try:
        from tools.outcome_tracker import update_outcomes
        update_outcomes()
    except Exception as e:
        log.debug(f"Outcome tracker error: {e}")

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
