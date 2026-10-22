"""
scanner/signal_filter.py — v8.7 Emergency
Changes:
  - MIN_STOP_PCT = 0.008 (was 0.005)
  - MIN_RR_RATIO = 1.8 (new)
  - Blocks VWAP_RECLAIM (kill switch)
  - Blocks regime_bad + RS_LOW combo (kill switch)
"""
import json
from utils.logger import get_logger
from utils import config

log = get_logger(__name__)

RANGE_HEALTH_THRESHOLD = 50
MIN_STOP_PCT = config.MIN_STOP_PCT
MIN_RR_RATIO = config.MIN_RR_RATIO


def _get_tags(c: dict) -> list:
    raw = c.get("shadow_tags", "[]")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return [t.strip() for t in raw.strip("[]").replace('"', "").split(",") if t.strip()]
    return raw or []


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
    setup         = c.get("entry_setup", "UNKNOWN")
    rr            = c.get("entry_rr", 0)
    tags          = _get_tags(c)
    symbol        = c.get("symbol", "?")

    # ── KILL SWITCH 1: VWAP_RECLAIM ─────────────────────────────
    if config.BLOCK_VWAP_RECLAIM and setup == "VWAP_RECLAIM":
        log.info(f"{symbol}: IGNORE | VWAP_RECLAIM_BLOCKED | ai={c.get('ai_score',0):.1f}")
        return "IGNORE"

    # ── KILL SWITCH 2: regime_bad + RS_LOW ──────────────────────
    if config.BLOCK_REGIME_BAD_RS_LOW:
        if config.TAG_REGIME_BAD in tags and config.TAG_RS_LOW in tags:
            log.info(f"{symbol}: IGNORE | REGIME_BAD_RS_LOW | ai={c.get('ai_score',0):.1f}")
            return "IGNORE"

    # ── Regime gating ───────────────────────────────────────────
    if dec == "BUY":
        if btc_regime == "RISK_OFF":
            log.info(f"{symbol}: BUY→WATCH (RISK_OFF)")
            return "WATCH"
        if btc_regime == "RANGE" and market_health < RANGE_HEALTH_THRESHOLD:
            log.info(f"{symbol}: BUY→WATCH (RANGE, health={market_health:.0f}<{RANGE_HEALTH_THRESHOLD})")
            return "WATCH"

    # ── BUY gates ──────────────────────────────────────────────
    if dec == "BUY":
        if flow < 35:
            log.info(f"{symbol}: BUY→PREPARE (flow={flow:.1f}<35)")
            return "PREPARE"
        if c.get("final_score", 0) < 45:
            log.info(f"{symbol}: BUY→PREPARE (score={c.get('final_score',0):.1f}<45)")
            return "PREPARE"
        if market_health < 35:
            log.info(f"{symbol}: BUY→WATCH (health={market_health:.0f}<35)")
            return "WATCH"

        # Stop tightness (0.8% floor)
        entry = c.get("entry_price", 0) or 0
        stop  = c.get("entry_sl", 0) or 0
        if entry > 0 and stop > 0:
            stop_pct = abs(entry - stop) / entry
            if stop_pct < MIN_STOP_PCT:
                log.info(f"{symbol}: BUY→WATCH (stop={stop_pct*100:.2f}%<{MIN_STOP_PCT*100:.1f}%)")
                return "WATCH"

        # R:R floor
        if rr < MIN_RR_RATIO:
            log.info(f"{symbol}: BUY→PREPARE (rr={rr:.2f}<{MIN_RR_RATIO})")
            return "PREPARE"

        log.info(f"{symbol}: BUY (confirmed) setup={setup} flow={flow:.1f} score={c.get('final_score',0):.1f} rr={rr:.2f}")
        return "BUY"

    # ── ARM ────────────────────────────────────────────────────
    oi_growing  = oi_change > 2.0
    rs_positive = rs_1h > 0
    oi_strong   = oi_change > 30.0
    at_trigger  = (0.0 <= dist_pct <= 0.05)

    if at_trigger and (compressed or flow >= 40 or oi_strong):
        return "ARM"
    arm_conditions = [
        dist_pct <= 1.0,
        compressed or flow >= 45 or oi_strong,
        market_health >= 50,
    ]
    if sum(arm_conditions) >= 2 and dist_pct <= 1.0:
        return "ARM"

    # ── PREPARE ────────────────────────────────────────────────
    prepare_factors = [compressed, flow >= 55, oi_growing, rs_positive]
    if flow >= 55 and sum(prepare_factors) >= 3:
        return "PREPARE"

    # ── WATCH ──────────────────────────────────────────────────
    if flow >= 45 or pre >= 45 or dist_pct < 2.0:
        return "WATCH"

    return "IGNORE"


def filter_coins(coins: list) -> dict:
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
        ignored.sort(key=lambda x: x.get("flow_score", 0) + x.get("pre_score", 0), reverse=True)
        needed = 5 - total_quality
        for c in ignored[:needed]:
            c["signal"] = "WATCH"
            watch.append(c)
            log.info(f"Promoted {c.get('symbol')} from IGNORE to WATCH (data boosting)")

    watch = sorted(watch, key=lambda x: x.get("flow_score", 0) + x.get("pre_score", 0), reverse=True)[:3]

    has_quality = bool(buy or prepare or arm)

    log.info(f"Signal filter: BUY={len(buy)} PREPARE={len(prepare)} ARM={len(arm)} WATCH={len(watch)} IGNORE={len(ignored)}")
    return {
        "buy": buy,
        "prepare": prepare,
        "arm": arm,
        "watch": watch,
        "ignored": ignored,
        "has_quality": has_quality,
    }
