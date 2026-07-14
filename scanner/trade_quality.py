"""
CRYPTO-BOT Elite — Trade Quality Score

ציון איכות לעסקה (לא למטבע).
מבוסס על:
    Flow 22%, Momentum 18%, OI 20%, News 10%, Compression 15%, Volume 15%
"""
from utils.logger import get_logger

log = get_logger("trade_quality")

def calc_trade_quality(coin_data: dict, news_score: float = 50) -> float:
    """
    מחשב Trade Quality Score 0-100.
    """
    flow = coin_data.get("flow_score", 50)
    momentum = coin_data.get("momentum_1h", 0)
    oi_change = coin_data.get("oi_change", 0)
    compressed = coin_data.get("is_compressed", False)
    rvol = coin_data.get("rvol", 1.0)

    # Flow (22%) – 0-100
    flow_score = min(100, max(0, flow))

    # Momentum (18%) – normalize to 0-100
    mom_score = min(100, max(0, 50 + momentum * 10))

    # OI (20%)
    if oi_change > 5:
        oi_score = 90
    elif oi_change > 2:
        oi_score = 70
    elif oi_change > 0:
        oi_score = 55
    elif oi_change > -2:
        oi_score = 40
    else:
        oi_score = 20

    # News (10%)
    news_component = news_score

    # Compression (15%) – binary
    comp_score = 100 if compressed else 40

    # Volume / RVOL (15%)
    if rvol >= 2.0:
        vol_score = 100
    elif rvol >= 1.5:
        vol_score = 80
    elif rvol >= 1.0:
        vol_score = 60
    else:
        vol_score = 30

    total = (flow_score * 0.22 + mom_score * 0.18 + oi_score * 0.20 +
             news_component * 0.10 + comp_score * 0.15 + vol_score * 0.15)

    return round(total, 1)
