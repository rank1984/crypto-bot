"""
scanner/entry_engine.py — v9.1 (Stress Test 7-Day)
Changes from v8.9:
  - DIP_BUY has its own final_score gate (20 instead of 40)
    Reason: final_score measures positive momentum, which is
    the opposite of what DIP_BUY looks for.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any
from utils.logger import get_logger
from utils import config

log = get_logger(__name__)


@dataclass
class EntrySignal:
    decision: str
    setup_type: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    reason: str
    trigger_price: Optional[float] = None
    trigger_source: str = "missing"


# final_score thresholds per setup
MIN_SCORE_DEFAULT = 40
MIN_SCORE_DIP_BUY = 20     # DIP_BUY is contrarian — lower gate


def evaluate_entry(coin: Dict[str, Any], df_5m: Any = None, btc_mom_5m: float = 0.0) -> EntrySignal:
    symbol = coin.get("symbol", "UNKNOWN")
    last_price = float(coin.get("price", 0) or 0)
    if last_price <= 0:
        return EntrySignal("NO", "UNKNOWN", 0, 0, 0, 0, 0.0, "invalid price")

    final_score = coin.get("final_score", 0)
    flow_score  = coin.get("flow_score", 0)
    pre_score   = coin.get("pre_score", 0)

    # ── Setup detection ────────────────────────────────────────────
    setup_type = coin.get("entry_setup", "UNKNOWN")
    if not setup_type or setup_type == "UNKNOWN":
        vwap_dist  = coin.get("vwap_dist", 0)
        rvol       = coin.get("rvol", 0)
        vol_accel  = coin.get("vol_accel", 0)
        rs_1h      = coin.get("rs_1h", 0)

        if vwap_dist < -0.3 and vol_accel > 0.2 and rs_1h > -0.2:
            setup_type = "DIP_BUY"
        elif -0.5 < vwap_dist < 0.5 and vol_accel > 0.2 and rvol > 0.8:
            setup_type = "VWAP_RECLAIM"
        elif vol_accel > 0.5 and rvol > 1.0 and coin.get("distance_from_breakout", 10) < 2.0:
            setup_type = "BREAKOUT"
        else:
            setup_type = "UNKNOWN"

    # ── ATR ────────────────────────────────────────────────────────
    atr_1h = coin.get("atr_1h", 0)
    atr_5m = coin.get("atr_14", 0)
    if atr_1h and atr_1h > 0:
        atr = atr_1h * 0.5
    elif atr_5m and atr_5m > 0:
        atr = atr_5m * 3
    else:
        atr = last_price * 0.005

    MIN_STOP_PCT = config.MIN_STOP_PCT
    MIN_TP_PCT   = config.MIN_TP_PCT

    # ── Calculate levels ───────────────────────────────────────────
    if setup_type == "DIP_BUY":
        entry = last_price * (1 - 0.001)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance   = max(2.5 * atr, last_price * MIN_TP_PCT)
    elif setup_type == "VWAP_RECLAIM":
        entry = last_price * (1 + 0.001)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance   = max(2.5 * atr, last_price * MIN_TP_PCT)
    elif setup_type == "BREAKOUT":
        entry = last_price * (1 + 0.002)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance   = max(3.0 * atr, last_price * 0.025)
    else:
        entry = last_price
        stop_distance = max(2.0 * atr, last_price * MIN_STOP_PCT)
        tp_distance   = max(2.0 * atr, last_price * MIN_TP_PCT)

    if stop_distance < last_price * MIN_STOP_PCT:
        stop_distance = last_price * MIN_STOP_PCT

    sl  = round(entry - stop_distance, 8)
    tp1 = round(entry + tp_distance, 8)
    tp2 = round(entry + tp_distance * 1.5, 8)

    risk = entry - sl
    reward = tp1 - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    # ── Trigger ────────────────────────────────────────────────────
    trigger_price = None
    trigger_source = "missing"

    if setup_type == "DIP_BUY":
        trigger_price = round(last_price, 8)
        trigger_source = "immediate"
    elif setup_type == "BREAKOUT":
        breakout_level = coin.get("breakout_level", 0)
        if breakout_level and breakout_level > 0:
            trigger_price = round(float(breakout_level), 8)
            trigger_source = "breakout_level"
    elif setup_type == "VWAP_RECLAIM":
        vwap = coin.get("vwap", 0)
        if vwap and vwap > 0:
            trigger_price = round(float(vwap), 8)
            trigger_source = "vwap"

    # ── Decision ───────────────────────────────────────────────────
    decision = "NO"
    reason = ""

    # Score gate depends on setup
    score_gate = MIN_SCORE_DIP_BUY if setup_type == "DIP_BUY" else MIN_SCORE_DEFAULT

    if config.BLOCK_VWAP_RECLAIM and setup_type == "VWAP_RECLAIM":
        decision = "WAIT"
        reason = "VWAP_RECLAIM blocked (emergency)"
    elif setup_type == "UNKNOWN":
        decision = "NO"
        reason = "No valid setup"
    elif final_score < score_gate:
        decision = "NO"
        reason = f"Final score {final_score:.1f} < {score_gate} (setup={setup_type})"
    elif rr < config.MIN_RR_RATIO:
        decision = "WAIT"
        reason = f"R:R {rr:.2f} < {config.MIN_RR_RATIO}"
    elif trigger_price is None or trigger_price <= 0:
        decision = "WAIT"
        reason = "no trigger price (do not invent)"
    else:
        trigger_dist_pct = (trigger_price - last_price) / last_price * 100
        if abs(trigger_dist_pct) > 2.0:
            decision = "WAIT"
            reason = f"trigger distance {trigger_dist_pct:.2f}% > 2%"
        else:
            decision = "BUY"
            reason = "trigger confirmed"

    stop_pct = (entry - sl) / entry * 100 if entry > 0 else 0
    trig_str = f"{trigger_price:.6f}" if trigger_price is not None else "NULL"
    log.info(
        f"{symbol}: decision={decision} setup={setup_type} "
        f"entry={entry:.6f} trigger={trig_str} ({trigger_source}) "
        f"sl={sl:.6f} ({stop_pct:.2f}%) tp1={tp1:.6f} rr={rr:.2f} "
        f"score={final_score:.1f}/{score_gate} reason={reason}"
    )

    return EntrySignal(
        decision=decision,
        setup_type=setup_type,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        rr=rr,
        reason=reason,
        trigger_price=trigger_price,
        trigger_source=trigger_source,
    )