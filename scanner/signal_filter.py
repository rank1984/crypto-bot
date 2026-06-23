"""
CRYPTO-BOT Elite — Signal Filter

4 מצבים בלבד:
    IGNORE  — לא מעניין, לא לשלוח
    WATCH   — יש משהו, מוקדם מדי
    PREPARE — הצטברות אמיתית, להתכונן
    BUY     — פריצה מאושרת

קריטריונים קשיחים:
    PREPARE דורש compression + flow>60 + OI עולה + RS חיובי
    בלי כולם — WATCH לכל היותר
    WATCH חלש (flow<40, אין compression, אין OI) — IGNORE
"""
from utils.logger import get_logger
log = get_logger(__name__)


def classify_signal(c: dict) -> str:
    """
    מקבל coin dict מ-ranking ומחזיר: IGNORE / WATCH / PREPARE / BUY
    """
    dec        = c.get("entry_decision", "NO")
    flow       = c.get("flow_score", 0)
    pre        = c.get("pre_score", 0)
    compressed = c.get("is_compressed", False)
    oi_change  = c.get("oi_change", 0)
    rs_1h      = c.get("rs_1h", 0)
    comp_parts = c.get("pre_components", {})
    flow_parts = c.get("flow_components", {})

    oi_growing  = oi_change > 2.0 or flow_parts.get("oi", 0) >= 10
    rs_positive = rs_1h > 0
    cvd_pos     = flow_parts.get("cvd", 0) >= 8

    # ── BUY: טריגר הופעל ────────────────────────────────────────────────────
    if dec == "BUY":
        return "BUY"

    # ── PREPARE: הצטברות אמיתית — כל 4 התנאים חייבים להתקיים ────────────
    prepare_conditions = [
        compressed,     # Compression קיים
        flow >= 60,     # Flow חזק
        oi_growing,     # OI מתחיל לעלות
        rs_positive,    # RS מול BTC חיובי
    ]
    if all(prepare_conditions):
        return "PREPARE"

    # ── WATCH: יש משהו אבל לא מספיק ────────────────────────────────────────
    # דורש לפחות 2 מתוך: compression / flow>40 / OI / RS
    watch_score = sum([compressed, flow >= 40, oi_growing, rs_positive])
    if watch_score >= 2:
        return "WATCH"

    # ── IGNORE: רעש ─────────────────────────────────────────────────────────
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
