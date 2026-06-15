"""
CRYPTO-BOT Elite — Main Loop
רץ כל 5 דקות, סורק את ה-universe, ושולח לטלגרם.

Usage:
    python main.py

Environment variables required:
    TELEGRAM_TOKEN   — bot token from @BotFather
    TELEGRAM_CHAT_ID — your chat/channel ID
"""
import time
import signal
import sys
import argparse

from scanner.universe  import build_universe
from scanner.ranking   import rank_universe
from telegram.sender   import send_telegram
from utils.config      import SCAN_INTERVAL_SECONDS
from utils.logger      import get_logger

log = get_logger("main")

# ─── Graceful shutdown ────────────────────────────────────────────────────────
_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received — stopping after current scan")
    _running = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ─── Single scan cycle ────────────────────────────────────────────────────────

def run_scan() -> None:
    log.info("── Scan started ──────────────────────────────────────")

    # 1. Universe
    symbols = build_universe()
    if not symbols:
        log.error("Empty universe — skipping scan")
        return

    # 2. Score & rank
    top = rank_universe(symbols)
    if not top:
        log.warning("No coins passed scoring — nothing to send")
        return

    # 3. Send
    send_telegram(top)

    log.info("── Scan complete ─────────────────────────────────────")
    for i, c in enumerate(top, 1):
        log.info(
            f"  {i}. {c['symbol']:<12}  "
            f"score={c['final_score']:.0f}  "
            f"rvol={c['rvol']:.1f}x  "
            f"mom5m={c['momentum_5m']:+.2f}%"
        )


# ─── Main loop ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (used by GitHub Actions)",
    )
    args = parser.parse_args()

    log.info("CRYPTO-BOT Elite starting...")

    if args.once:
        log.info("Mode: single scan (--once)")
        run_scan()
        sys.exit(0)

    log.info(f"Mode: loop every {SCAN_INTERVAL_SECONDS}s ({SCAN_INTERVAL_SECONDS//60}m)")
    while _running:
        try:
            run_scan()
        except Exception as e:
            log.error(f"Unhandled error in scan cycle: {e}", exc_info=True)

        if not _running:
            break

        log.info(f"Sleeping {SCAN_INTERVAL_SECONDS}s until next scan...")
        for _ in range(SCAN_INTERVAL_SECONDS):
            if not _running:
                break
            time.sleep(1)

    log.info("CRYPTO-BOT Elite stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
