"""
CRYPTO-BOT Elite — Quality Gate

בדיקה אחרונה לפני BUY:
    entry_decision = "BUY" + טריגר טכני
    אבל:
    flow_score >= 55
    AND (pre_score >= 40 OR oi_change > 2)

בלי אלה — downgrade ל-WAIT
"""
from utils.logger import get_logger

log = get_logger(__name__)


def apply_quality_gate(coin: dict) -> dict:
    """
    בדיקה אחרונה לפני BUY.
    Regime-aware: ב-Bear/Risk-Off הרף עולה — רק A+ עם catalyst עוברים.
    """
    entry_dec = coin.get("entry_decision", "NO")
    flow      = coin.get("flow_score", 0)
    pre       = coin.get("pre_score", 0)
    oi        = coin.get("oi_change", 0)
    regime    = coin.get("regime", "RANGE")
    catalyst  = coin.get("has_catalyst", False)

    if entry_dec != "BUY":
        return coin

    if regime in ("TRENDING_BEAR", "RISK_OFF"):
        if flow >= 75 and pre >= 65 and catalyst:
            return coin
        log.debug(f"{coin['symbol']}: BUY blocked in {regime} (needs A+ + catalyst)")
        coin["entry_decision"] = "WAIT"
        return coin

    if flow >= 55 and (pre >= 40 or oi > 2):
        return coin

    log.debug(
        f"{coin['symbol']}: BUY downgrade → WAIT "
        f"(flow={flow:.0f}, pre={pre:.0f}, oi={oi:.1f})"
    )
    coin["entry_decision"] = "WAIT"
    return coin


def apply_quality_gate_all(coins: list[dict]) -> list[dict]:
    """הפעל gate על כל המטבעות."""
    return [apply_quality_gate(c) for c in coins]
