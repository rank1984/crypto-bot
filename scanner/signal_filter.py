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
    """
    מחזיר final_decision אחיד:
    BUY / PREPARE / ARM / WATCH / IGNORE
    """
    dec           = c.get("entry_decision", "NO")
    flow          = c.get("flow_score", 0)
    pre           = c.get("pre_score", 0)
    compressed    = c.get("is_compressed", False)
    oi_change     = c.get("oi_change", 0)
    rs_1h         = c.get("rs_1h", 0)
    prob          = c.get("probability", 0)
    dist_pct      = c.get("trigger_distance_pct", 999)
    market_health = c.get("market_health", 70)
    btc_regime    = c.get("btc_regime", "RANGE")

    oi_growing  = oi_change > 2.0
    rs_positive = rs_1h > 0
    oi_strong   = oi_change > 30.0
    at_trigger  = (0.0 <= dist_pct <= 0.05)

    # ── Strict Regime Filter ─────────────────────────────────────────────
    if btc_regime == "RISK_OFF":
        if dec == "BUY":
            return "WATCH"
    if btc_regime == "RANGE" and market_health < 55:
        if dec == "BUY":
            return "WATCH"
    # ───────────────────────────────────────────────────────────────────────

    # ── Final AI Gate ─────────────────────────────────────────────────────
    if dec == "BUY":
        if prob < 40:
            return "WATCH"
        if flow < 40:
            return "PREPARE"
        if c.get("final_score", 0) < 60:
            return "PREPARE"
        if market_health < 35:
            return "WATCH"
        return "BUY"

    # ── ARM ──────────────────────────────────────────────────────────────
    if at_trigger and (compressed or flow >= 40 or oi_strong):
        return "ARM"
    arm_conditions = [
        prob >= 25 if prob > 0 else True,
        dist_pct <= 1.0,
        compressed or flow >= 45 or oi_strong,
        market_health >= 50,
    ]
    if sum(arm_conditions) >= 3 and dist_pct <= 1.0:
        return "ARM"

    # ── PREPARE ──────────────────────────────────────────────────────────
    prepare_factors = [compressed, flow >= 55, oi_growing, rs_positive]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # ── WATCH ────────────────────────────────────────────────────────────
    if flow >= 45 or pre >= 45 or (prob >= 25 and dist_pct < 2.0):
        return "WATCH"

    return "IGNORE"


def filter_coins(coins: list[dict]) -> dict:
    buy, prepare, arm, watch, ignored = [], [], [], [], []

    for c in coins:
        sig = classify_signal(c)
        c["signal"] = sig
        if   sig == "BUY":     buy.append(c)
        elif sig == "PREPARE": prepare.append(c)
        elif sig == "ARM":     arm.append(c)
        elif sig == "WATCH":   watch.append(c)
        else:                  ignored.append(c)

    # ── הבטח לפחות 5 מטבעות (ללמידה) ──────────────────────────────────
    total_quality = len(buy) + len(prepare) + len(arm) + len(watch)
    if total_quality < 5:
        ignored.sort(key=lambda x: x.get("flow_score",0)+x.get("pre_score",0), reverse=True)
        needed = 5 - total_quality
        for c in ignored[:needed]:
            c["signal"] = "WATCH"
            watch.append(c)
            log.info(f"Promoted {c['symbol']} from IGNORE to WATCH (data boosting)")

    # WATCH – מקסימום 3, רק הטובים ביותר
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
