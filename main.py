"""
CRYPTO-BOT Elite — MAIN FLOW (Fixed Integration with Feature Engine)
"""

from scanner.signal_filter import filter_coins
from scanner.data_normalizer import normalize_universe
from scanner.feature_engine import enrich_universe
from utils.logger import get_logger

# 👇 זה ה-renderer החדש הבטוח
from utils.telegram_renderer import send_telegram

log = get_logger(__name__)


def run_once(raw_coins: list):
    """
    ריצה אחת של הבוט - צינור עיבוד נתונים מלא
    """

    log.info(f"Starting scan — coins received: {len(raw_coins)}")

    # ─────────────────────────────
    # 1. Data Pipeline (Normalize -> Enrich -> Filter)
    # ─────────────────────────────
    # א. הפיכת רשימת הסימבולים למילונים בסיסיים
    coins = normalize_universe(raw_coins)
    
    # ב. הרצת מנוע תכונות והזרקת נתוני שוק (נפח, OI, מחיר, פילטרים)
    coins = enrich_universe(coins)
    
    # ג. סינון האותות וחלוקה לקטגוריות (BUY, PREPARE, WATCH)
    result = filter_coins(coins)

    buy     = result["buy"]
    prepare = result["prepare"]
    watch   = result["watch"]

    has_quality = result["has_quality"]

    log.info(
        f"FILTER RESULT → BUY:{len(buy)} PREPARE:{len(prepare)} WATCH:{len(watch)}"
    )

    # ─────────────────────────────
    # 2. Build top coins list
    # ─────────────────────────────
    top_coins = []

    # BUY קודם
    top_coins.extend(buy)

    # PREPARE שני
    top_coins.extend(prepare)

    # WATCH רק אם אין מספיק איכות
    if not has_quality:
        top_coins.extend(watch)

    # מקסימום 5 כדי לא להציף טלגרם
    top_coins = sorted(
        top_coins,
        key=lambda x: x.get("flow_score", 0) + x.get("pre_score", 0),
        reverse=True
    )[:5]

    # ─────────────────────────────
    # 3. Safety check
    # ─────────────────────────────
    if not top_coins:
        log.info("No quality signals — skipping Telegram")
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
    
    coins_list = get_coins()
    run_once(coins_list)
