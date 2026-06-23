"""
CRYPTO-BOT Elite — MAIN FLOW (PRODUCTION PIPELINE)
"""

from scanner.ranking import rank_universe
from scanner.signal_filter import filter_coins
from utils.logger import get_logger

# ה-renderer הבטוח
from utils.telegram_renderer import send_telegram

log = get_logger(__name__)

def run_once(raw_coins: list[str]):
    """
    ריצה אחת של הבוט - צינור עיבוד נתונים מלא
    """
    log.info(f"Starting scan — coins received: {len(raw_coins)}")

    # ─────────────────────────────
    # 1. Data Pipeline (The BRAIN)
    # ─────────────────────────────
    # מריץ את כל מנועי האלפא, בדיקות הנזילות, וחישובי הכניסה מתוך ranking.py
    # rank_universe כבר מסנן מטבעות זבל ומחזיר רק את ה-Top N שמעל סף משטר השוק
    scored_coins = rank_universe(raw_coins)
    
    if not scored_coins:
        log.info("No coins passed the ranking thresholds — skipping Telegram")
        return

    # ─────────────────────────────
    # 2. Signal Classification
    # ─────────────────────────────
    # עכשיו כשיש למטבעות את כל המידע (entry_decision, rs, flow), הפילטר יעבוד כמו שצריך
    result = filter_coins(scored_coins)

    buy     = result["buy"]
    prepare = result["prepare"]
    watch   = result["watch"]
    has_quality = result["has_quality"]

    log.info(f"FILTER RESULT → BUY:{len(buy)} PREPARE:{len(prepare)} WATCH:{len(watch)}")

    # ─────────────────────────────
    # 3. Build top coins list
    # ─────────────────────────────
    top_coins = []
    top_coins.extend(buy)
    top_coins.extend(prepare)

    if not has_quality:
        top_coins.extend(watch)

    # מיון סופי ובחירת טופ 5
    top_coins = sorted(
        top_coins,
        key=lambda x: x.get("final_score", 0) + x.get("flow_score", 0),
        reverse=True
    )[:5]

    if not top_coins:
        log.info("No quality signals after filtering — skipping Telegram")
        return

    # ─────────────────────────────
    # 4. Send Telegram (SAFE renderer)
    # ─────────────────────────────
    try:
        ok = send_telegram(top_coins)
        if ok:
            log.info("Telegram sent successfully")
        else:
            log.warning("Telegram failed or fallback used")
    except Exception as e:
        log.error(f"CRITICAL MAIN ERROR: {e}")

# ─────────────────────────────
# CLI entry
# ─────────────────────────────
if __name__ == "__main__":
    from scanner.universe import get_coins  
    
    # get_coins אמור להחזיר רשימה של סימבולים (strings) כמו ["BTCUSDT", "ETHUSDT"]
    coins_list = get_coins()
    run_once(coins_list)
