"""
DAYS-BOT V5.0.5 – PM Data Quality Gate

Ensures PM data is correctly interpreted:
- pm_volume == 0 and no data source → pm_volume_status = "UNAVAILABLE"
- pm_volume == 0 but data source confirmed → pm_volume_status = "ZERO"
- pm_data_quality = "COMPLETE" / "PARTIAL" / "MISSING"

Does NOT assign score/penalty; only sets status flags for downstream.
"""

from typing import Dict, Any


def check_pm_data_quality(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main gate entry point. Returns:
        pm_volume_status: "UNAVAILABLE" | "ZERO" | "PRESENT"
        pm_data_quality: "COMPLETE" | "PARTIAL" | "MISSING"
        pm_volume: int
        pm_high: float or None
        pm_vwap: float or None
        source: str
    """
    pm_volume = candidate.get("pm_volume", 0)
    pm_high = candidate.get("pm_high")
    pm_vwap = candidate.get("pm_vwap")
    source = candidate.get("pm_source", "unknown")

    result = {
        "pm_volume": pm_volume,
        "pm_high": pm_high,
        "pm_vwap": pm_vwap,
        "source": source,
        "pm_volume_status": None,
        "pm_data_quality": None,
    }

    # Determine pm_volume_status
    if pm_volume == 0:
        if source in ("alpaca_iex", "yfinance", "alpaca_sip"):
            result["pm_volume_status"] = "ZERO"  # Data existed but volume is zero
        else:
            result["pm_volume_status"] = "UNAVAILABLE"  # No data source
    else:
        result["pm_volume_status"] = "PRESENT"

    # Determine pm_data_quality
    if pm_high is not None and pm_vwap is not None and pm_volume > 0:
        result["pm_data_quality"] = "COMPLETE"
    elif (pm_high is not None or pm_vwap is not None) and pm_volume > 0:
        result["pm_data_quality"] = "PARTIAL"
    else:
        result["pm_data_quality"] = "MISSING"

    return result
