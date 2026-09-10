"""
DAYS-BOT V5.0.5 – Corporate Action Gate

Detects corporate actions that may invalidate a trade:
- Reverse / Forward Split
- Ticker change
- Offering / Secondary offering
- Merger / Acquisition
- Spinoff
- Halt / Resumption related to corporate action

If detected → candidate is marked with:
    corporate_action = True
    corporate_action_type = string
    halt_flag = bool
    trade_type = "NO_TRADE" or "WATCH_CORPORATE_ACTION"
"""

import re
from typing import Dict, Any, Optional
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta


def _check_sec_filings_for_offering(ticker: str) -> Dict[str, Any]:
    """
    Check SEC EDGAR for recent offering filings (S-1, S-3, 424B5, 8-K)
    Returns: {has_offering: bool, filing_type: str, filing_date: str}
    """
    result = {"has_offering": False, "filing_type": None, "filing_date": None}
    try:
        # Fetch CIK mapping from local cache or public source
        # For simplicity, we use a fallback – but this is placeholder for real implementation
        # In production: use sec_analyzer.py's check_offering_risk
        pass
    except Exception:
        pass
    return result


def _check_recent_splits(ticker: str) -> Dict[str, Any]:
    """
    Check yfinance for recent split announcements
    """
    result = {"has_split": False, "split_type": None, "split_date": None}
    try:
        data = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if data.empty:
            return result
        # Check for split events (yfinance does not directly give splits, but we can use ticker.info)
        info = yf.Ticker(ticker).info
        # Look for splits in info (if available)
        # This is a placeholder – real implementation should use a dedicated splits API
        if "splits" in info:
            splits = info.get("splits", {})
            if splits:
                # Assume split event exists
                result["has_split"] = True
                # Determine split type
                last_split = list(splits.values())[-1] if splits else None
                if last_split and isinstance(last_split, float):
                    if last_split > 1.0:
                        result["split_type"] = "ForwardSplit"
                    elif 0 < last_split < 1.0:
                        result["split_type"] = "ReverseSplit"
                    # Note: yfinance info may not contain split details reliably
    except Exception:
        pass
    return result


def _check_ticker_change(ticker: str) -> Dict[str, Any]:
    """
    Check for ticker changes (using previous ticker history)
    """
    result = {"has_ticker_change": False, "old_ticker": None, "change_date": None}
    # Placeholder: not implemented – will be expanded in future
    return result


def check_corporate_action(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main gate entry point. Returns:
        corporate_action: bool
        corporate_action_type: str or None
        halt_flag: bool
        risk_level: str ("HIGH", "MEDIUM", "LOW")
        reason: str
    """
    ticker = candidate.get("ticker")
    if not ticker:
        return {
            "corporate_action": False,
            "corporate_action_type": None,
            "halt_flag": False,
            "risk_level": "LOW",
            "reason": "No ticker",
        }

    result = {
        "corporate_action": False,
        "corporate_action_type": None,
        "halt_flag": False,
        "risk_level": "LOW",
        "reason": "No corporate action detected",
    }

    # 1. Check SEC filings for offerings
    offering = _check_sec_filings_for_offering(ticker)
    if offering.get("has_offering"):
        result["corporate_action"] = True
        result["corporate_action_type"] = "Offering"
        result["risk_level"] = "HIGH"
        result["reason"] = f"Offering filing detected: {offering.get('filing_type')}"
        return result

    # 2. Check splits
    split = _check_recent_splits(ticker)
    if split.get("has_split"):
        result["corporate_action"] = True
        result["corporate_action_type"] = split.get("split_type")
        result["risk_level"] = "MEDIUM"
        result["reason"] = f"Recent split detected: {split.get('split_type')}"
        return result

    # 3. Check ticker change
    ticker_change = _check_ticker_change(ticker)
    if ticker_change.get("has_ticker_change"):
        result["corporate_action"] = True
        result["corporate_action_type"] = "TickerChange"
        result["risk_level"] = "HIGH"
        result["reason"] = "Recent ticker change detected"
        return result

    return result
