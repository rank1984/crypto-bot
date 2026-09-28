"""
scanner/entry_engine.py
Entry Engine – determines entry, stop, targets, trigger, and decision.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class EntrySignal:
    decision: str          # "BUY", "WAIT", "NO"
    setup_type: str        # "DIP_BUY", "VWAP_RECLAIM", "BREAKOUT", "UNKNOWN"
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    reason: str
    trigger_price: Optional[float] = None
    trigger_source: str = "missing"


def evaluate_entry(
    coin: Dict[str, Any],
    df_5m: Any,
    btc_mom_5m: float = 0.0,
) -> EntrySignal:
    symbol = coin.get("symbol", "UNKNOWN")
    last_price = float(coin.get("price", 0) or 0)
    if last_price <= 0:
        return EntrySignal("NO", "UNKNOWN", 0, 0, 0, 0, 0.0, "invalid price")

    final_score = coin.get("final_score", 0)
    flow_score = coin.get("flow_score", 0)
    pre_score = coin.get("pre_score", 0)
    probability = coin.get("probability", 0)

    # ── Setup detection ────────────────────────────────────────────
    setup_type = coin.get("entry_setup", "UNKNOWN")
    if not setup_type or setup_type == "UNKNOWN":
        vwap_dist = coin.get("vwap_dist", 0)
        rvol = coin.get("rvol", 0)
        vol_accel = coin.get("vol_accel", 0)
        rs_1h = coin.get("rs_1h", 0)

        if vwap_dist < -2.0 and vol_accel > 0.3 and rs_1h > 0:
            setup_type = "DIP_BUY"
        elif -0.5 < vwap_dist < 0.5 and vol_accel > 0.2 and rvol > 0.8:
            setup_type = "VWAP_RECLAIM"
        elif vol_accel > 0.5 and rvol > 1.0 and coin.get("distance_from_breakout", 10) < 2.0:
            setup_type = "BREAKOUT"
        else:
            setup_type = "UNKNOWN"

    # ── Calculate entry, stop, targets ────────────────────────────
    atr = coin.get("atr_14", 0)
    if atr <= 0:
        atr = last_price * 0.01

    if setup_type == "DIP_BUY":
        entry = last_price * (1 - 0.001)
        stop_distance = 1.5 * atr
        tp_distance = 2.5 * atr
    elif setup_type == "VWAP_RECLAIM":
        entry = last_price * (1 + 0.001)
        stop_distance = 1.2 * atr
        tp_distance = 2.0 * atr
    elif setup_type == "BREAKOUT":
        entry = last_price * (1 + 0.002)
        stop_distance = 1.5 * atr
        tp_distance = 3.0 * atr
    else:
        entry = last_price
        stop_distance = 2.0 * atr
        tp_distance = 2.0 * atr

    sl = round(entry - stop_distance, 4)
    tp1 = round(entry + tp_distance, 4)
    tp2 = round(entry + tp_distance * 1.5, 4)

    risk = entry - sl
    reward = tp1 - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    # ── Determine trigger_price (do NOT invent) ──────────────────
    trigger_price = None
    trigger_source = "missing"

    if setup_type == "DIP_BUY":
        trigger_price = round(last_price, 4)
        trigger_source = "immediate"

    elif setup_type == "BREAKOUT":
        breakout_level = coin.get("breakout_level", 0)
        if breakout_level and breakout_level > 0:
            trigger_price = round(float(breakout_level), 4)
            trigger_source = "breakout_level"

    elif setup_type == "VWAP_RECLAIM":
        vwap = coin.get("vwap", 0)
        if vwap and vwap > 0:
            trigger_price = round(float(vwap), 4)
            trigger_source = "vwap"

    # ── Decision logic ────────────────────────────────────────────
    decision = "NO"
    reason = ""

    if setup_type == "UNKNOWN":
        decision = "NO"
        reason = "No valid setup"
    elif final_score < 50:
        decision = "NO"
        reason = f"Final score {final_score:.1f} < 50"
    elif probability < 15:
        decision = "NO"
        reason = f"Probability {probability:.1f}% < 15%"
    elif rr < 1.5:
        decision = "WAIT"
        reason = f"R:R {rr:.2f} < 1.5"
    else:
        if trigger_price is not None and last_price > 0:
            trigger_dist_pct = (trigger_price - last_price) / last_price * 100
            if abs(trigger_dist_pct) > 2.0:
                decision = "WAIT"
                reason = f"trigger distance {trigger_dist_pct:.2f}% > 2%"
            else:
                decision = "BUY"
                reason = "trigger confirmed"
        else:
            if flow_score > 45 and pre_score > 40:
                decision = "BUY"
                reason = "flow + pre scores strong"
            else:
                decision = "WAIT"
                reason = "no trigger and flow/pre not strong enough"

    if coin.get("entry_decision") == "BUY" and decision != "BUY":
        decision = "BUY"
        reason = "override from ranking (entry_decision=BUY)"

    trig_str = f"{trigger_price:.4f}" if trigger_price is not None else "NULL"
    log.info(
        f"{symbol}: entry_decision={decision} "
        f"setup={setup_type} "
        f"entry={entry:.4f} "
        f"trigger={trig_str} ({trigger_source}) "
        f"sl={sl:.4f} tp1={tp1:.4f} rr={rr:.2f} reason={reason}"
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