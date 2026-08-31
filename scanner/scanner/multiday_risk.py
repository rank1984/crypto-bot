"""
scanner/multiday_risk.py
Risk engine for Multi-Day trades.
Entry, Stop, Targets based on structure and ATR.
No LLM-generated prices.
"""

import numpy as np


class MultiDayRisk:
    def __init__(self, atr_4h: float, atr_1d: float, last_price: float):
        self.atr_4h = atr_4h
        self.atr_1d = atr_1d
        self.last_price = last_price

    def get_entry(self, setup_type: str, breakout_level: float = None, pullback_level: float = None) -> float:
        """
        Returns entry price based on setup type.
        - BREAKOUT: entry at breakout_level + 0.2 * ATR_4h (confirmation)
        - PULLBACK: entry at pullback_level (support/VWAP) + 0.1 * ATR_4h
        """
        if setup_type == "BREAKOUT" and breakout_level is not None:
            return round(breakout_level + 0.2 * self.atr_4h, 4)
        elif setup_type == "PULLBACK" and pullback_level is not None:
            return round(pullback_level + 0.1 * self.atr_4h, 4)
        else:
            # Fallback: current price + 0.5% (conservative)
            return round(self.last_price * 1.005, 4)

    def get_stop(self, entry: float, setup_type: str) -> float:
        """Stop based on structure + ATR multiplier."""
        if setup_type == "BREAKOUT":
            # Stop below breakout level or recent low
            stop_distance = 1.5 * self.atr_4h
        elif setup_type == "PULLBACK":
            # Stop below pullback support
            stop_distance = 1.2 * self.atr_4h
        else:
            stop_distance = 2.0 * self.atr_4h

        return round(entry - stop_distance, 4)

    def get_targets(self, entry: float, setup_type: str) -> tuple:
        """Returns (tp1, tp2)."""
        if setup_type == "BREAKOUT":
            tp1_mult = 2.0
            tp2_mult = 4.0
        else:  # PULLBACK
            tp1_mult = 1.5
            tp2_mult = 3.0

        tp1 = entry + tp1_mult * self.atr_4h
        tp2 = entry + tp2_mult * self.atr_4h
        return round(tp1, 4), round(tp2, 4)

    def get_risk_reward(self, entry: float, stop: float, tp1: float) -> float:
        """R:R ratio."""
        risk = entry - stop
        reward = tp1 - entry
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)


def build_risk_params(features: dict, setup_type: str, last_price: float) -> dict:
    """Build complete risk parameters."""
    atr_4h = features.get("atr_4h", 0)
    atr_1d = features.get("atr_1d", 0)

    risk = MultiDayRisk(atr_4h, atr_1d, last_price)

    breakout_level = features.get("breakout_level", 0)
    pullback_level = features.get("resistance", 0)  # placeholder

    entry = risk.get_entry(setup_type, breakout_level, pullback_level)
    stop = risk.get_stop(entry, setup_type)
    tp1, tp2 = risk.get_targets(entry, setup_type)
    rr = risk.get_risk_reward(entry, stop, tp1)

    return {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "risk_reward": rr,
        "atr_4h": atr_4h,
        "atr_1d": atr_1d
    }
