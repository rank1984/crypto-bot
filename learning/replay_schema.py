"""
DAYS-BOT V5.0.5 – Replay Schema + Snapshot Saver

Saves a full replay record for EVERY Strict Candidate (not just Top 5).
Includes all fields required for V5.0.6 post-market analysis.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime
import pytz
from typing import Dict, Any, Optional

ET = pytz.timezone("America/New_York")
REPLAY_PATH = Path(__file__).resolve().parent.parent / "data" / "replay"


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default=""):
    try:
        if value is None:
            return default
        return str(value)
    except:
        return default


def _get_field(candidate: dict, key: str, default=None):
    return candidate.get(key, default)


def build_replay_record(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a full replay record from a candidate snapshot.
    All fields are point-in-time values at scan time.
    """
    now_et = datetime.now(ET)
    analysis = candidate.get("analysis", {})
    data_comp = candidate.get("data_completeness", {})

    record = {}

    # ============================================================
    # 4.1 IDENTIFICATION
    # ============================================================
    record["replay_id"] = str(uuid.uuid4())
    record["decision_timestamp"] = now_et.isoformat()
    record["ticker"] = _safe_str(candidate.get("ticker"))
    record["strategy_version"] = "V5.0.5"
    record["score_version"] = "V5.0.4"
    record["filter_version"] = "V5.0.5"
    record["trade_type"] = _safe_str(candidate.get("trade_type", "WATCH"))
    record["qualified"] = bool(candidate.get("qualified", False))

    # ============================================================
    # 4.2 DISCOVERY
    # ============================================================
    record["previous_close"] = _safe_float(candidate.get("prev_close"))
    record["last_price"] = _safe_float(candidate.get("price"))
    record["gap_pct"] = _safe_float(candidate.get("gap_pct"))
    record["price"] = _safe_float(candidate.get("price"))
    record["pm_volume"] = _safe_int(candidate.get("pm_volume"))
    record["pm_dollar_volume"] = _safe_float(record["price"] * record["pm_volume"]) if record["price"] and record["pm_volume"] else None
    record["pm_high"] = _safe_float(candidate.get("pm_high"))
    record["pm_low"] = _safe_float(candidate.get("pm_low"))
    record["pm_vwap"] = _safe_float(candidate.get("pm_vwap"))
    record["spread_pct"] = _safe_float(candidate.get("spread_pct"))
    record["average_daily_volume"] = _safe_int(candidate.get("average_daily_volume"))
    record["pm_volume_status"] = _safe_str(candidate.get("pm_volume_status", "UNAVAILABLE"))
    record["pm_data_quality"] = _safe_str(candidate.get("pm_data_quality", "MISSING"))

    # ============================================================
    # 4.3 STOCK CHARACTERISTICS
    # ============================================================
    record["float_shares"] = _safe_float(candidate.get("float"))
    record["shares_outstanding"] = _safe_float(candidate.get("shares_outstanding"))
    record["short_interest"] = _safe_float(candidate.get("short_interest"))
    record["short_interest_pct"] = _safe_float(candidate.get("short_interest_pct"))
    record["rvol"] = _safe_float(candidate.get("rvol"))
    record["rvol_status"] = _safe_str(candidate.get("rvol_status", "UNAVAILABLE"))
    record["rvol_method"] = _safe_str(candidate.get("rvol_method"))
    record["atr"] = _safe_float(candidate.get("atr"))

    # ============================================================
    # 4.4 CATALYST / RISK
    # ============================================================
    record["catalyst_score"] = _safe_int(candidate.get("catalyst_score"))
    record["catalyst_type"] = _safe_str(candidate.get("catalyst_type"))
    record["news_novelty"] = _safe_str(candidate.get("catalyst_summary"))
    record["sec_risk_level"] = _safe_str(candidate.get("sec_risk_level", "LOW"))
    record["sec_risk_reason"] = _safe_str(candidate.get("sec_risk_reason"))
    record["corporate_action"] = bool(candidate.get("corporate_action", False))
    record["corporate_action_type"] = _safe_str(candidate.get("corporate_action_type"))
    record["halt_flag"] = bool(candidate.get("halt_flag", False))

    # ============================================================
    # 4.5 SCORES
    # ============================================================
    record["intraday_score"] = _safe_float(candidate.get("composite_score"))
    record["swing_score"] = _safe_float(candidate.get("swing_score"))
    record["early_score"] = _safe_float(candidate.get("early_score"))
    record["early_state"] = _safe_str(candidate.get("early_state", "UNKNOWN"))
    # Score components (if available)
    # We don't have granular components from current scoring_engine, will be added later
    record["gap_score"] = None
    record["volume_score"] = None
    record["float_score"] = None
    record["short_score"] = None
    record["catalyst_score_component"] = None
    record["data_quality"] = _safe_str(candidate.get("data_status", "NO_TRADE"))
    record["data_status"] = _safe_str(candidate.get("data_status", "NO_TRADE"))

    # ============================================================
    # 4.6 TRADE PLAN
    # ============================================================
    record["entry"] = _safe_float(candidate.get("entry"))
    record["stop"] = _safe_float(candidate.get("stop"))
    record["target_1"] = _safe_float(candidate.get("target_1"))
    record["target_2"] = _safe_float(candidate.get("target_2"))
    record["risk_per_share"] = _safe_float(candidate.get("risk_per_share"))
    record["position_size"] = _safe_int(candidate.get("position_size"))
    record["position_value"] = _safe_float(record["position_size"] * record["entry"]) if record["position_size"] and record["entry"] else None
    record["decision"] = _safe_str(candidate.get("decision", "NO_TRADE"))
    record["entry_trigger"] = _safe_str(candidate.get("decision", "NO_TRADE"))

    # ============================================================
    # 4.7 POST-MARKET (to be filled in V5.0.6)
    # ============================================================
    record["entry_triggered"] = False
    record["entry_trigger_timestamp"] = None
    record["entry_price_actual"] = None
    record["MFE_pct"] = None
    record["MAE_pct"] = None
    record["hit_5pct"] = False
    record["hit_10pct"] = False
    record["hit_15pct"] = False
    record["time_to_5"] = None
    record["time_to_10"] = None
    record["time_to_15"] = None
    record["stop_hit"] = False
    record["target_1_hit"] = False
    record["target_2_hit"] = False
    record["stop_first"] = False
    record["target_1_first"] = False
    record["target_2_first"] = False
    record["ambiguous_bar"] = False
    record["gross_return_pct"] = None
    record["gross_R"] = None
    record["commission_entry"] = None
    record["commission_exit"] = None
    record["spread_cost"] = None
    record["slippage_cost"] = None
    record["tax_cost"] = None
    record["total_cost"] = None
    record["net_return_pct"] = None
    record["net_R"] = None
    record["outcome_class"] = None

    return record


def save_replay_record(candidate: Dict[str, Any]) -> bool:
    """
    Save a replay record for a Strict Candidate.
    Returns True on success, False on failure (silently handled).
    """
    try:
        # Build record
        record = build_replay_record(candidate)

        # Ensure directory exists
        REPLAY_PATH.mkdir(parents=True, exist_ok=True)

        # File per day
        today = datetime.now(ET).strftime("%Y-%m-%d")
        file_path = REPLAY_PATH / f"replay_{today}.json"

        # Load existing data
        data = []
        if file_path.exists():
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
            except:
                data = []

        # Append new record
        data.append(record)

        # Write back
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return True

    except Exception as e:
        print(f"[Replay] Error saving record for {candidate.get('ticker')}: {e}")
        return False


def count_replay_records_for_date(date_str: str = None) -> int:
    """Count total replay records for a given date."""
    if date_str is None:
        date_str = datetime.now(ET).strftime("%Y-%m-%d")
    file_path = REPLAY_PATH / f"replay_{date_str}.json"
    if file_path.exists():
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                return len(data)
        except:
            return 0
    return 0


def replay_integrity_check(date_str: str = None) -> dict:
    """
    Check replay integrity:
    - records_count
    - unique replay_ids
    - decision_timestamp present
    """
    if date_str is None:
        date_str = datetime.now(ET).strftime("%Y-%m-%d")
    file_path = REPLAY_PATH / f"replay_{date_str}.json"
    if not file_path.exists():
        return {"status": "NO_FILE", "records": 0}

    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        records = len(data)
        ids = [r.get("replay_id") for r in data if r.get("replay_id")]
        unique_ids = len(set(ids))
        timestamps_present = sum(1 for r in data if r.get("decision_timestamp"))

        return {
            "status": "OK",
            "records": records,
            "unique_ids": unique_ids,
            "unique_ok": unique_ids == records,
            "timestamps_present": timestamps_present,
            "timestamps_ok": timestamps_present == records,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "records": 0}
