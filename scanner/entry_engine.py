"""
scanner/entry_engine.py
Entry Engine – determines entry, stop, targets, trigger, and decision.
Includes minimum stop distance protection for crypto volatility.
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

    # ── ATR Calculation (🆕 prefer 1h ATR) ────────────────────────
    atr_1h = coin.get("atr_1h", 0)
    atr_5m = coin.get("atr_14", 0)

    if atr_1h > 0:
        atr = atr_1h * 0.5  # Half of 1h ATR ≈ 30min movement
    elif atr_5m > 0:
        atr = atr_5m * 3    # 5m ATR × 3 ≈ 15m volatility
    else:
        atr = last_price * 0.005  # 0.5% fallback

    # ── Calculate entry, stop, targets (🆕 with minimums) ────────
    MIN_STOP_PCT = 0.008   # 0.8% minimum stop
    MIN_TP_PCT = 0.015     # 1.5% minimum TP1

    if setup_type == "DIP_BUY":
        entry = last_price * (1 - 0.001)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance = max(2.5 * atr, last_price * MIN_TP_PCT)
    elif setup_type == "VWAP_RECLAIM":
        entry = last_price * (1 + 0.001)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance = max(2.5 * atr, last_price * MIN_TP_PCT)
    elif setup_type == "BREAKOUT":
        entry = last_price * (1 + 0.002)
        stop_distance = max(1.5 * atr, last_price * MIN_STOP_PCT)
        tp_distance = max(3.0 * atr, last_price * 0.025)  # 2.5% for breakout
    else:
        entry = last_price
        stop_distance = max(2.0 * atr, last_price * MIN_STOP_PCT)
        tp_distance = max(2.0 * atr, last_price * MIN_TP_PCT)

    sl = round(entry - stop_distance, 6)
    tp1 = round(entry + tp_distance, 6)
    tp2 = round(entry + tp_distance * 1.5, 6)

    risk = entry - sl
    reward = tp1 - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    # ── Determine trigger_price (do NOT invent) ──────────────────
    trigger_price = None
    trigger_source = "missing"

    if setup_type == "DIP_BUY":
        trigger_price = round(last_price, 6)
        trigger_source = "immediate"

    elif setup_type == "BREAKOUT":
        breakout_level = coin.get("breakout_level", 0)
        if breakout_level and breakout_level > 0:
            trigger_price = round(float(breakout_level), 6)
            trigger_source = "breakout_level"

    elif setup_type == "VWAP_RECLAIM":
        vwap = coin.get("vwap", 0)
        if vwap and vwap > 0:
            trigger_price = round(float(vwap), 6)
            trigger_source = "vwap"

    # ── Decision logic ────────────────────────────────────────────
    decision = "NO"
    reason = ""

    if setup_type == "UNKNOWN":
        decision = "NO"
        reason = "No valid setup"
    elif final_score < 40:
        decision = "NO"
        reason = f"Final score {final_score:.1f} < 40"
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

    trig_str = f"{trigger_price:.6f}" if trigger_price is not None else "NULL"
    stop_pct = (entry - sl) / entry * 100 if entry > 0 else 0
    log.info(
        f"{symbol}: entry_decision={decision} "
        f"setup={setup_type} "
        f"entry={entry:.6f} "
        f"trigger={trig_str} ({trigger_source}) "
        f"sl={sl:.6f} ({stop_pct:.2f}%) "
        f"tp1={tp1:.6f} rr={rr:.2f} reason={reason}"
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