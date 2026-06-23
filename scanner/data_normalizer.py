"""
CRYPTO-BOT Elite — Data Normalizer Layer

המטרה:
לייצר פורמט אחיד לכל מטבע לפני שהוא נכנס ל-ranking / signal_filter

זה פותר:
- strings במקום dict
- missing keys
- קריסות classify_signal
"""

from utils.logger import get_logger

log = get_logger(__name__)


def normalize_coin(c: dict | str) -> dict | None:
    """
    הופך כל input לסטנדרט אחד.

    אם זה string → הופך לדיקט בסיסי
    אם זה dict → משלים שדות חסרים
    """

    # ─────────────────────────────────────────────
    # 1. תיקון קטסטרופה: סטרינג במקום מטבע
    # ─────────────────────────────────────────────
    if isinstance(c, str):
        if not c:
            return None

        return {
            "symbol": c,
            "price": 0.0,
            "volume": 0.0,

            "flow_score": 0,
            "pre_score": 0,

            "entry_decision": "NO",

            "is_compressed": False,
            "oi_change": 0,
            "rs_1h": 0,

            "flow_components": {},
            "pre_components": {},
        }

    # ─────────────────────────────────────────────
    # 2. אם כבר dict — רק נרמל חסרים
    # ─────────────────────────────────────────────
    if not isinstance(c, dict):
        log.warning(f"Invalid coin type skipped: {type(c)}")
        return None

    return {
        "symbol": c.get("symbol", "UNKNOWN"),

        "price": float(c.get("price", 0) or 0),
        "volume": float(c.get("volume", 0) or 0),

        "flow_score": float(c.get("flow_score", 0) or 0),
        "pre_score": float(c.get("pre_score", 0) or 0),

        "entry_decision": c.get("entry_decision", "NO"),

        "is_compressed": bool(c.get("is_compressed", False)),
        "oi_change": float(c.get("oi_change", 0) or 0),
        "rs_1h": float(c.get("rs_1h", 0) or 0),

        "flow_components": c.get("flow_components", {}) or {},
        "pre_components": c.get("pre_components", {}) or {},
    }


def normalize_universe(coins: list) -> list[dict]:
    """
    מריץ ניקוי מלא על כל ה-universe
    """

    cleaned = []

    for c in coins:
        n = normalize_coin(c)
        if n:
            cleaned.append(n)

    log.info(f"Normalized universe: {len(cleaned)} coins")
    return cleaned
