"""
CRYPTO-BOT Elite — Signal Filter

5 מצבים:
    IGNORE
    WATCH
    ARM      — קרוב לטריגר (≤1%), איכותי – נכנס למעקב מהיר
    PREPARE
    BUY
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
    prob       = c.get("probability", 0)
    dist_pct   = c.get("trigger_distance_pct", 999)
    market_health = c.get("market_health", 70)

    oi_growing  = oi_change > 2.0
    rs_positive = rs_1h > 0
    oi_strong   = oi_change > 30.0

    # BUY – טריגר מאושר
    if dec == "BUY":
        if flow < 30 and pre < 30:
            return "WATCH"
        return "BUY"

    # ARM – מרחק ≤1%, איכות גבוהה – ניטור 10 שניות
    arm_conditions = [
        prob >= 25 if prob > 0 else True,
        dist_pct <= 1.0,
        compressed or flow >= 45 or oi_strong,
        market_health >= 60,
    ]
    if sum(arm_conditions) >= 3 and dist_pct <= 1.0:
        return "ARM"

    # PREPARE – הצטברות
    prepare_factors = [compressed, flow >= 55, oi_growing, rs_positive]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # WATCH
    if flow >= 45 or pre >= 45 or (prob >= 25 and dist_pct < 2.0):
        return "WATCH"

    return "IGNORE"


def filter_coins(coins: list[dict]) -> dict:
    buy, prepare, arm, watch = [], [], [], []

    for c in coins:
        sig = classify_signal(c)
        c["signal"] = sig
        if   sig == "BUY":     buy.append(c)
        elif sig == "PREPARE": prepare.append(c)
        elif sig == "ARM":     arm.append(c)
        elif sig == "WATCH":   watch.append(c)

    watch = sorted(watch, key=lambda x: x.get("flow_score",0)+x.get("pre_score",0), reverse=True)[:3]

    has_quality = bool(buy or prepare or arm)

    log.info(f"Signal filter: BUY={len(buy)} PREPARE={len(prepare)} ARM={len(arm)} WATCH={len(watch)}")
    return {
        "buy": buy,
        "prepare": prepare,
        "arm": arm,
        "watch": watch,
        "has_quality": has_quality,
    }
