"""
CRYPTO-BOT Elite — Main Loop (v2.0 with Trade Lifecycle)

Environment variables:
    TELEGRAM_TOKEN        — bot token
    TELEGRAM_CHAT_ID      — chat/channel ID
    USE_DYNAMIC_UNIVERSE  — true/false (default: true)
"""
import time, signal, sys, argparse

from scanner.universe         import build_universe
from scanner.dynamic_universe import build_dynamic_universe
from scanner.market_data      import get_candles
from scanner.ranking          import rank_universe
from notifier.sender          import send_telegram
from utils.config             import SCAN_INTERVAL_SECONDS, USE_DYNAMIC_UNIVERSE
from utils.logger             import get_logger

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


def run_scan() -> None:
    log.info("── Scan started ──────────────────────────────────────")

    # ── 0. Init Databases (Shadow DB must load BEFORE the scan) ───────────────
    try:
        from tools.shadow_mode import init_shadow_db
        init_shadow_db()
    except Exception as e:
        log.warning(f"Shadow DB init error: {e}")

    # ── 1. Universe ───────────────────────────────────────────────────────────
    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        btc_df     = get_candles("BTCUSDT", "1hour", limit=3)
        btc_1h_mov = 0.0
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

    # ── 3. Decision Engine — החלטה אחת מרכזית ──────────────────────────────
    from scanner.decision_engine import decide_batch
    top = decide_batch(top)

    # ── 4. Quality Gate (legacy - מנוטרל) ───────────────────────────────────
    from scanner.quality_gate import apply_quality_gate_all
    top = apply_quality_gate_all(top)

    # ── 5. Signal Filter ─────────────────────────────────────────────────────
    from scanner.signal_filter import filter_coins
    filtered = filter_coins(top)

    # debug — מה יש לפני הסינון
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
        f"BUY={len(filtered['buy'])} "
        f"PREPARE={len(filtered['prepare'])} "
        f"WATCH={len(filtered['watch'])}"
    )

    # ── 6. Trade Management ───────────────────────────────────────────────────
    # 6a. פתיחת עסקאות חדשות
    for c in filtered["buy"]:
        # מנוע כניסה השיג BUY, ננסה לפתוח עסקה
        if trade_mgr.can_open_trade():
            # נשתמש במחיר נוכחי של המטבע (מ-c)
            current_price = c.get("last_price", 0)
            if current_price == 0:
                # fallback – fetch candle
                df_5m = get_candles(c["symbol"], "5m", limit=5)
                if df_5m is not None and len(df_5m) > 0:
                    current_price = float(df_5m["close"].iloc[-1])
            # signal dict עבור open_trade
            signal = {
                "symbol": c["symbol"],
                "entry": c.get("entry_price", current_price),
                "sl": c.get("sl", current_price * 0.98),
                "tp1": c.get("tp1", current_price * 1.04),
                "tp2": c.get("tp2", current_price * 1.10),
                "setup_type": c.get("setup_type", "UNKNOWN"),
            }
            trade = trade_mgr.open_trade(signal, current_price)
            # שליחת הודעה
            from notifier.sender import send_trade_open
            send_trade_open(trade)
        else:
            log.info(f"Max trades reached, {c['symbol']} put on WATCH (no open slot)")

    # 6b. עדכון עסקאות קיימות
    active_trades = trade_mgr.get_active_trades()
    for trade in active_trades:
        symbol = trade.symbol
        # fetch latest data
        df_5m = get_candles(symbol, "5m", limit=30)
        df_1h = get_candles(symbol, "1hour", limit=30)
        if df_5m is None or len(df_5m) == 0:
            continue
        current_price = float(df_5m["close"].iloc[-1])

        # coin_data for exit engine
        # need: rs_1h, rs_4h, oi_change, vwap, ema20, etc.
        # we can get from the ranking dict (if we kept it) or recompute
        # For now simplified: fetch from precomputed 'top' list if still there
        coin_data = next((x for x in top if x["symbol"] == symbol), None)
        if not coin_data:
            # fallback – minimal data from candles
            coin_data = {
                "symbol": symbol,
                "rs_1h": 0.0,
                "rs_4h": 0.0,
                "oi_change": 0.0,
            }

        # update trade
        action = trade_mgr.update(
            symbol=symbol,
            current_price=current_price,
            coin_data=coin_data,
            df_5m=df_5m,
            df_1h=df_1h,
            btc_momentum_5m=0.0  # can compute from BTC candle
        )
        if action:
            if action["action"] == "SELL_PARTIAL":
                from notifier.sender import send_trade_partial
                send_trade_partial(trade, action)
            elif action["action"] == "SELL_ALL":
                from notifier.sender import send_trade_close
                send_trade_close(trade, action)

    # ── 7. Send Telegram summary ─────────────────────────────────────────────
    if filtered["has_quality"]:
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

    # print active trades
    active_now = trade_mgr.get_active_trades()
    if active_now:
        log.info("── Active Trades ──────────────────────────────────────────")
        for t in active_now:
            log.info(f"  {t.symbol} | Entry={t.entry_price:.4f} | State={t.state} | "
                     f"SL={t.sl:.4f} | TP1={t.tp1:.4f} | TP2={t.tp2:.4f}")


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

    log.info("CRYPTO-BOT Elite stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
