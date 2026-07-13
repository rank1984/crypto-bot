"""
CRYPTO-BOT Elite — Signal Filter

4 מצבים בלבד:
    IGNORE  — לא מעניין, לא לשלוח
    WATCH   — יש משהו, מוקדם מדי
    PREPARE — הצטברות אמיתית, להתכונן
    BUY     — פריצה מאושרת

קריטריונים קשיחים:
    PREPARE דורש לפחות 3 מתוך 4 פקטורי הצטברות (Compression, Flow>55, OI עולה, RS חיובי).
    בלי כולם — WATCH לכל היותר.
    WATCH חלש (flow<40, אין compression, אין OI) — IGNORE.
"""
from utils.logger import get_logger
log = get_logger(__name__)


def _big_move_score(c: dict) -> float:
    """מיון לפי פוטנציאל מהלך גדול."""
    return c.get("flow_score", 0) * 0.50 + c.get("pre_score", 0) * 0.50


def classify_signal(c: dict) -> str:
    dec        = c.get("entry_decision", "NO")
    flow       = c.get("flow_score", 0)
    pre        = c.get("pre_score", 0)
    compressed = c.get("is_compressed", False)
    oi_change  = c.get("oi_change", 0)
    rs_1h      = c.get("rs_1h", 0)
    flow_parts = c.get("flow_components", {})

    oi_growing  = oi_change > 2.0 or flow_parts.get("oi", 0) >= 10
    rs_positive = rs_1h > 0

    # BUY: טריגר טכני מאושר
    if dec == "BUY":
    # Downgrade רק אם שני הציונים ממש גרועים
    if flow < 30 and pre < 30:
        return "WATCH"
    return "BUY"

    # ── PREPARE: 3 מתוך 4 (לא חובה כולם) ──────────────────────────────────
    prepare_factors = [
        compressed,
        flow >= 55,
        oi_growing,
        rs_positive,
    ]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # WATCH: יש משהו מינימלי
    if flow >= 45 or pre >= 45:
        return "WATCH"

    return "IGNORE"


def filter_coins(coins: list[dict]) -> dict:
    """
    מקבל רשימת מטבעות, מחלק ל-4 קבוצות, מסנן רעש.

    Returns
    -------
    {
        "buy":     [coin, ...],
        "prepare": [coin, ...],
        "watch":   [coin, ...],    # מקסימום 3
        "has_quality": bool,
    }
    """
    buy, prepare, watch = [], [], []

    for c in coins:
        sig = classify_signal(c)
        c["signal"] = sig
        if   sig == "BUY":     buy.append(c)
        elif sig == "PREPARE": prepare.append(c)
        elif sig == "WATCH":   watch.append(c)
        # IGNORE — לא נכנס לשום רשימה

    # WATCH — מקסימום 3, רק הטובים ביותר
    watch = sorted(watch, key=lambda x: x.get("flow_score",0)+x.get("pre_score",0), reverse=True)[:3]

    has_quality = bool(buy or prepare)

    log.info(f"Signal filter: BUY={len(buy)} PREPARE={len(prepare)} WATCH={len(watch)}")
    return {"buy": buy, "prepare": prepare, "watch": watch, "has_quality": has_quality}
