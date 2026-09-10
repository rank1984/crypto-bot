"""
DAYS-BOT V5.0.5 – Liquidity Gate

Hard Gate for Intraday liquidity conditions:
- spread_pct <= 8.0%
- average_daily_volume >= 100,000
- price >= 1.0

If failed → candidate is marked as:
    liquidity_pass = False
    liquidity_fail_reason = string
    trade_type = "WATCH_LIQUIDITY" or "NO_TRADE"
"""

from typing import Dict, Any, Optional
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta


def _get_average_daily_volume(ticker: str) -> Optional[float]:
    """
    Fetch average daily volume from yfinance (last 30 days)
    """
    try:
        data = yf.download(ticker, period="1mo", interval="1d", progress=False)
        if data.empty or len(data) < 5:
            return None
        avg_vol = data["Volume"].iloc[-30:].mean()
        return float(avg_vol)
    except Exception:
        return None


def check_liquidity(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main gate entry point. Returns:
        liquidity_pass: bool
        fail_reason: str (if failed)
        spread_pct: float or None
        avg_daily_volume: float or None
        price: float or None
    """
    ticker = candidate.get("ticker")
    price = candidate.get("price")
    spread_pct = candidate.get("spread_pct")
    avg_vol = candidate.get("average_daily_volume") or _get_average_daily_volume(ticker)

    result = {
        "liquidity_pass": True,
        "fail_reason": None,
        "spread_pct": spread_pct,
        "avg_daily_volume": avg_vol,
        "price": price,
    }

    # 1. Price check
    if price is None or price < 1.0:
        result["liquidity_pass"] = False
        result["fail_reason"] = f"Price ${price:.2f} < $1.00"
        return result

    # 2. Spread check (if available)
    if spread_pct is not None and spread_pct > 8.0:
        result["liquidity_pass"] = False
        result["fail_reason"] = f"Spread {spread_pct:.2f}% > 8.0%"
        return result

    # 3. Average daily volume check
    if avg_vol is not None and avg_vol < 100_000:
        result["liquidity_pass"] = False
        result["fail_reason"] = f"Avg daily volume {avg_vol:,.0f} < 100,000"
        return result

    return result
