"""
CRYPTO-BOT Elite — Signal Filter

5 מצבים:
    IGNORE  — לא מעניין
    WATCH   — יש פוטנציאל, מוקדם מדי
    READY   — קרוב מאוד לטריגר, איכותי
    PREPARE — הצטברות אמיתית
    BUY     — פריצה מאושרת
"""
from utils.logger import get_logger
log = get_logger(__name__)


def classify_signal(c: dict) -> str:
    dec        = c.get("entry_decision", "NO")
    flow       = c.get("flow_score", 0)
    pre        = c.get("pre_score", 0)
    compressed = c.get("is_compressed", False)
    oi_change  = c.get("oi_change", 0)
    rs_1h      = c.get("rs_1h", 0)
    prob       = c.get("probability", 0)  # AI Probability
    dist_pct   = c.get("trigger_distance_pct", 999)  # % from trigger
    market_health = c.get("market_health", 70)

    oi_growing  = oi_change > 2.0
    rs_positive = rs_1h > 0

    # BUY: טריגר טכני מאושר
    if dec == "BUY":
        if flow < 30 and pre < 30:
            return "WATCH"
        return "BUY"

       # READY: קרוב לטריגר, איכות גבוהה
    ready_conditions = [
        prob >= 40 if prob > 0 else True,   # הורדנו ל-40
        dist_pct <= 0.5,
        compressed or flow >= 45 or (oi_change > 1000),  # OI חריג = READY
        market_health >= 60,
    ]
    if sum(ready_conditions) >= 3 and dist_pct <= 0.7:
        return "READY"

    # PREPARE: 3 מתוך 4 פקטורי הצטברות
    prepare_factors = [
        compressed,
        flow >= 55,
        oi_growing,
        rs_positive,
    ]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # WATCH: מינימלי
    if flow >= 45 or pre >= 45 or (prob >= 40 and dist_pct < 2.0):
        return "WATCH"

    return "IGNORE"


def filter_coins(coins: list[dict]) -> dict:
    buy, prepare, ready, watch = [], [], [], []

    for c in coins:
        sig = classify_signal(c)
        c["signal"] = sig
        if   sig == "BUY":     buy.append(c)
        elif sig == "PREPARE": prepare.append(c)
        elif sig == "READY":   ready.append(c)
        elif sig == "WATCH":   watch.append(c)

    watch = sorted(watch, key=lambda x: x.get("flow_score",0)+x.get("pre_score",0), reverse=True)[:3]

    has_quality = bool(buy or prepare or ready)

    log.info(f"Signal filter: BUY={len(buy)} PREPARE={len(prepare)} READY={len(ready)} WATCH={len(watch)}")
    return {
        "buy": buy,
        "prepare": prepare,
        "ready": ready,
        "watch": watch,
        "has_quality": has_quality,
    }
