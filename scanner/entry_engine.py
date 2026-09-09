"""
scanner/entry_engine.py
Entry Engine – determines entry, stop, targets, and decision (BUY/WAIT/NO).
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
    rr: float              # risk/reward ratio
    reason: str


def evaluate_entry(
    coin: Dict[str, Any],
    df_5m: Any,
    btc_mom_5m: float = 0.0,
) -> EntrySignal:
    """
    Evaluate entry conditions for a single coin.

    Args:
        coin: dictionary with coin data (price, indicators, scores, etc.)
        df_5m: 5-minute DataFrame (for additional context)
        btc_mom_5m: BTC 5-minute momentum (for market context)

    Returns:
        EntrySignal with decision, setup, prices, and reason.
    """
    symbol = coin.get("symbol", "UNKNOWN")
    last_price = float(coin.get("price", 0) or 0)
    if last_price <= 0:
        return EntrySignal("NO", "UNKNOWN", 0, 0, 0, 0, 0.0, "invalid price")

    # ── Extract key data ───────────────────────────────────────────────
    final_score = coin.get("final_score", 0)
    flow_score = coin.get("flow_score", 0)
    pre_score = coin.get("pre_score", 0)
    probability = coin.get("probability", 0)

    # ── Setup detection ────────────────────────────────────────────────
    # Use entry_decision from ranking if available, otherwise determine
    setup_type = coin.get("entry_setup", "UNKNOWN")
    if not setup_type or setup_type == "UNKNOWN":
        # Auto-detect setup based on patterns
        vwap_dist = coin.get("vwap_dist", 0)
        rvol = coin.get("rvol", 0)
        vol_accel = coin.get("vol_accel", 0)
        rs_1h = coin.get("rs_1h", 0)

        # DIP_BUY: price below VWAP, volume acceleration, RS positive
        if vwap_dist < -2.0 and vol_accel > 0.3 and rs_1h > 0:
            setup_type = "DIP_BUY"
        # VWAP_RECLAIM: price crossing above VWAP, volume confirms
        elif -0.5 < vwap_dist < 0.5 and vol_accel > 0.2 and rvol > 0.8:
            setup_type = "VWAP_RECLAIM"
        # BREAKOUT: price near recent high, volume expansion
        elif vol_accel > 0.5 and rvol > 1.0 and coin.get("distance_from_breakout", 10) < 2.0:
            setup_type = "BREAKOUT"
        else:
            setup_type = "UNKNOWN"

    # ── Calculate entry, stop, targets ──────────────────────────────
    # Base ATR for risk sizing (use 14-period ATR from indicators)
    atr = coin.get("atr_14", 0)
    if atr <= 0:
        atr = last_price * 0.01  # fallback 1%

    # Entry price
    if setup_type == "DIP_BUY":
        # Buy near support / VWAP
        entry = last_price * (1 - 0.001)  # slight discount
        stop_distance = 1.5 * atr
        tp_distance = 2.5 * atr
    elif setup_type == "VWAP_RECLAIM":
        entry = last_price * (1 + 0.001)  # slight premium for confirmation
        stop_distance = 1.2 * atr
        tp_distance = 2.0 * atr
    elif setup_type == "BREAKOUT":
        entry = last_price * (1 + 0.002)  # premium for breakout confirmation
        stop_distance = 1.5 * atr
        tp_distance = 3.0 * atr
    else:
        # Default conservative entry
        entry = last_price
        stop_distance = 2.0 * atr
        tp_distance = 2.0 * atr

    sl = round(entry - stop_distance, 4)
    tp1 = round(entry + tp_distance, 4)
    tp2 = round(entry + tp_distance * 1.5, 4)

    # Risk/Reward
    risk = entry - sl
    reward = tp1 - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    # ── Decision logic ────────────────────────────────────────────────
    decision = "NO"
    reason = ""

    # 1. Check if setup is valid
    if setup_type == "UNKNOWN":
        decision = "NO"
        reason = "No valid setup"

    # 2. Check score thresholds
    elif final_score < 50:
        decision = "NO"
        reason = f"Final score {final_score:.1f} < 50"

    # 3. Check probability
    elif probability < 15:
        decision = "NO"
        reason = f"Probability {probability:.1f}% < 15%"

    # 4. Check R:R
    elif rr < 1.5:
        decision = "WAIT"
        reason = f"R:R {rr:.2f} < 1.5"

    # 5. Check trigger distance (if trigger_price exists)
    else:
        trigger_price = coin.get("trigger_price", 0)
        if trigger_price > 0:
            trigger_dist_pct = (trigger_price - last_price) / last_price * 100
            # For BUY, price must be close to trigger (within 1%)
            if abs(trigger_dist_pct) > 2.0:
                decision = "WAIT"
                reason = f"trigger distance {trigger_dist_pct:.2f}% > 2%"
            else:
                decision = "BUY"
                reason = "trigger confirmed"
        else:
            # No trigger price – use flow/pre score to decide
            if flow_score > 45 and pre_score > 40:
                decision = "BUY"
                reason = "flow + pre scores strong"
            else:
                decision = "WAIT"
                reason = "no trigger and flow/pre not strong enough"

    # ── Override: Forced BUY if entry_setup from ranking is BUY ────
    if coin.get("entry_decision") == "BUY" and decision != "BUY":
        decision = "BUY"
        reason = "override from ranking (entry_decision=BUY)"

    # ── Debug log ──────────────────────────────────────────────────────
    log.info(
        f"{symbol}: entry_decision={decision} "
        f"setup={setup_type} "
        f"entry={entry:.4f} "
        f"sl={sl:.4f} "
        f"tp1={tp1:.4f} "
        f"rr={rr:.2f} "
        f"reason={reason}"
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
    )