"""
CRYPTO-BOT Elite — Main Loop

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


def run_scan() -> None:
    log.info("── Scan started ──────────────────────────────────────")

    # ── 1. Universe ───────────────────────────────────────────────────────────
    if USE_DYNAMIC_UNIVERSE:
        log.info("Mode: Dynamic Universe")
        # BTC 1h move לLayer RS
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

    # ── 4. Signal Filter ─────────────────────────────────────────────────────
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

    # ── 5. Send ───────────────────────────────────────────────────────────────
    if filtered["has_quality"]:
        send_telegram(top, filtered=filtered, stats=_diag, all_coins=top)
    else:
        # אין עסקה — שלח diagnostic עם מועמדים קרובים
        log.info("No quality signals — sending diagnostic")
        send_telegram(top, filtered=filtered, stats=_diag, all_coins=top)

    # ── 5. Log summary ────────────────────────────────────────────────────────
    # ── 6. Shadow Mode — שמור הכל בשקט ──────────────────────────────────────
    try:
        from tools.shadow_mode import save_shadow_signal, init_shadow_db, update_forward_returns
        init_shadow_db()
        for c in top:
            save_shadow_signal(c, c.get("signal", "IGNORE"))
        update_forward_returns()   # מעדכן returns מסריקות קודמות
        log.info(f"Shadow Mode: saved {len(top)} signals")
    except Exception as e:
        log.debug(f"Shadow Mode skipped: {e}")

    # ── 7. Score History ─────────────────────────────────────────────────────
    try:
        from tools.score_history import init_score_history, save_score
        init_score_history()
        for c in top:
            save_score(c, c.get("rating", "C"))
    except Exception as e:
        log.debug(f"Score history skipped: {e}")
    for i, c in enumerate(top, 1):
        log.info(
            f"  {i}. {c['symbol']:<12} "
            f"score={c['final_score']:.0f}  "
            f"flow={c.get('flow_score',0):.0f}  "
            f"pre={c.get('pre_score',0):.0f}  "
            f"signal={c.get('signal','?'):<10}  "
            f"entry={c.get('entry_decision','NO')}"
        )


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
