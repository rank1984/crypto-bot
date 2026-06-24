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
        symbols = build_dynamic_universe(
            get_candles_fn=get_candles,
            btc_1h_move=btc_1h_mov,
            use_layers=True,
        )
    else:
        log.info("Mode: Static Universe")
        symbols = build_universe()

    if not symbols:
        log.error("Empty universe — skipping scan")
        return

    # ── 2. Score & Rank ───────────────────────────────────────────────────────
    top = rank_universe(symbols)
    if not top:
        log.warning("No coins passed scoring — sending 'no signal' message")
        send_telegram([])   # שולח הודעת "אין סיגנל" לטלגרם
        return

    # ── 3. Signal Filter ─────────────────────────────────────────────────────
    from scanner.signal_filter import filter_coins
    filtered = filter_coins(top)

    # ── 4. Send ───────────────────────────────────────────────────────────────
    send_telegram(top, filtered=filtered)

    # ── 5. Log summary ────────────────────────────────────────────────────────
    log.info("── Scan complete ─────────────────────────────────────")
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
