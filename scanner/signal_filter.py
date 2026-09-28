"""
CRYPTO-BOT Elite — Signal Filter

5 מצבים:
    IGNORE
    WATCH
    ARM
    PREPARE
    BUY
"""
from utils.logger import get_logger
log = get_logger(__name__)


# ✅ Threshold for RANGE regime gating (tuned from 55 → 50)
RANGE_HEALTH_THRESHOLD = 50


def classify_signal(c: dict) -> str:
    dec           = c.get("entry_decision", "NO")
    flow          = c.get("flow_score", 0)
    pre           = c.get("pre_score", 0)
    compressed    = c.get("is_compressed", False)
    oi_change     = c.get("oi_change", 0)
    rs_1h         = c.get("rs_1h", 0)
    dist_pct      = c.get("trigger_distance_pct")
    if dist_pct is None:
        dist_pct = 999
    market_health = c.get("market_health", 70)
    btc_regime    = c.get("btc_regime", "RANGE")

    oi_growing  = oi_change > 2.0
    rs_positive = rs_1h > 0
    oi_strong   = oi_change > 30.0
    at_trigger  = (0.0 <= dist_pct <= 0.05)

    # ── Regime gating ─────────────────────────────────────────────────
    if dec == "BUY":
        if btc_regime == "RISK_OFF":
            log.info(f"{c.get('symbol','?')}: BUY→WATCH (regime=RISK_OFF)")
            return "WATCH"
        if btc_regime == "RANGE" and market_health < RANGE_HEALTH_THRESHOLD:
            log.info(f"{c.get('symbol','?')}: BUY→WATCH (RANGE, health={market_health:.0f} < {RANGE_HEALTH_THRESHOLD})")
            return "WATCH"

    # ── Final AI Gate ─────────────────────────────────────────────────────
    # ⚠️ Probability gate removed – we proved correlation with outcome is ~0.
    if dec == "BUY":
        if flow < 40:
            log.info(f"{c.get('symbol','?')}: BUY→PREPARE (flow={flow:.1f} < 40)")
            return "PREPARE"
        if c.get("final_score", 0) < 60:
            log.info(f"{c.get('symbol','?')}: BUY→PREPARE (final_score={c.get('final_score',0):.1f} < 60)")
            return "PREPARE"
        if market_health < 35:
            log.info(f"{c.get('symbol','?')}: BUY→WATCH (health={market_health:.0f} < 35)")
            return "WATCH"
        log.info(f"{c.get('symbol','?')}: BUY (confirmed) | flow={flow:.1f} score={c.get('final_score',0):.1f}")
        return "BUY"

    # ── ARM ──────────────────────────────────────────────────────────────
    if at_trigger and (compressed or flow >= 40 or oi_strong):
        return "ARM"
    arm_conditions = [
        dist_pct <= 1.0,
        compressed or flow >= 45 or oi_strong,
        market_health >= 50,
    ]
    if sum(arm_conditions) >= 2 and dist_pct <= 1.0:
        return "ARM"

    # ── PREPARE ──────────────────────────────────────────────────────────
    prepare_factors = [compressed, flow >= 55, oi_growing, rs_positive]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # ── WATCH ────────────────────────────────────────────────────────────
    if flow >= 45 or pre >= 45 or dist_pct < 2.0:
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

    total_quality = len(buy) + len(prepare) + len(arm) + len(watch)
    if total_quality < 5:
        ignored.sort(key=lambda x: x.get("flow_score",0)+x.get("pre_score",0), reverse=True)
        needed = 5 - total_quality
        for c in ignored[:needed]:
            c["signal"] = "WATCH"
            watch.append(c)
            log.info(f"Promoted {c['symbol']} from IGNORE to WATCH (data boosting)")

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
