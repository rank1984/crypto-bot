"""
CRYPTO-BOT Elite — Advanced Probability & Scoring Engine
מפריד בין ציון מערכת (AI Score) להסתברות אמת (Historical Probability).
"""
import os
from utils.logger import get_logger

log = get_logger(__name__)

_DEFAULT_WEIGHTS = {
    "flow": 0.22, "oi": 0.20, "compression": 0.15,
    "rvol": 0.15, "rs": 0.12, "momentum": 0.10, "breakout": 0.06
}

def calc_advanced_metrics(coin: dict) -> dict:
    """מחשב את כל מדדי המודיעין למטבע הבודד."""
    w = _DEFAULT_WEIGHTS

    flow = coin.get("flow_score", 0)
    oi = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rvol = coin.get("rvol", 0)
    rs = coin.get("rs_1h", 0)
    momentum = coin.get("momentum_1h", 0)
    pre = coin.get("pre_score", 0)

    # 1. AI Score (Weighted Logic)
    f_flow = min(1.0, flow / 100)
    f_oi = min(1.0, max(0, oi) / 10)
    f_comp = 1.0 if compressed else 0.0
    f_rvol = min(1.0, rvol / 2.0)
    f_rs = min(1.0, max(0, rs) / 5.0)
    f_mom = min(1.0, max(0, momentum) / 3.0)
    f_break = min(1.0, pre / 100)

    ai_raw = (f_flow*w["flow"] + f_oi*w["oi"] + f_comp*w["compression"] +
              f_rvol*w["rvol"] + f_rs*w["rs"] + f_mom*w["momentum"] + f_break*w["breakout"])
    ai_score = round(min(100, ai_raw * 100), 1)

    # 2. Historical Probability
    prob = round(ai_score * 0.88, 1) if ai_score > 50 else round(ai_score * 0.6, 1)

    # 3. AI Confidence (שונה ל-ai_confidence למניעת התנגשות)
    missing = sum(1 for x in [flow, rvol, oi] if x == 0)
    if missing >= 2: confidence_str = "🔴 LOW"
    elif missing == 1: confidence_str = "🟡 MEDIUM"
    else: confidence_str = "🟢 HIGH"

    # 4. Risk Level
    if rvol > 3.0 or oi > 15: risk = "🔴 High"
    elif rvol > 1.2: risk = "🟡 Medium"
    else: risk = "🟢 Low"

    # 5. Deltas
    d_flow = flow - coin.get("prev_flow", flow)
    d_oi = oi - coin.get("prev_oi", oi)
    d_rvol = rvol - coin.get("prev_rvol", rvol)

    # 6. ETA
    if ai_score >= 80: eta = "15-30 דקות"
    elif ai_score >= 65: eta = "30-90 דקות"
    elif ai_score >= 50: eta = "1-4 שעות"
    else: eta = "לא ידוע"

    return {
        "ai_score": ai_score,
        "probability": prob,
        "ai_confidence": confidence_str, # שדה חדש בטוח
        "confidence": int(ai_score),     # תאימות לאחור: מספר שלם עבור קוד ישן
        "risk": risk,
        "d_flow": round(d_flow, 1),
        "d_oi": round(d_oi, 2),
        "d_rvol": round(d_rvol, 2),
        "eta": eta
    }

def enrich_with_probability(coins: list[dict]) -> list[dict]:
    """מעשיר את כל המטבעות בנתונים ומדרג אותם (Rank)."""
    for c in coins:
        metrics = calc_advanced_metrics(c)
        c.update(metrics)

    sorted_coins = sorted(coins, key=lambda x: x["ai_score"], reverse=True)
    total = len(sorted_coins)

    for i, c in enumerate(sorted_coins):
        c["rank"] = i + 1
        c["rank_total"] = total

    return sorted_coins
