"""
CRYPTO-BOT Elite — Liquidity Engine

Bid/Ask imbalance + Buy/Sell walls + Sweep orders.
מקור: KuCoin Order Book API (חינמי).

liquidity_score 0–100:
    גבוה = ביקוש אמיתי, קל לקנות, קשה למוכרים
    נמוך = supply כבד, מכשולים מעל
"""
import requests
from utils.logger import get_logger

log = get_logger(__name__)

_SPOT    = "https://api.kucoin.com"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_TIMEOUT = 8


def _kucoin_sym(symbol: str) -> str:
    """BTCUSDT → BTC-USDT"""
    base = symbol.replace("USDT", "")
    return f"{base}-USDT"


def calc_liquidity_score(symbol: str, depth: int = 20) -> dict:
    """
    מחשב liquidity_score מה-order book.

    Returns
    -------
    {
        "liquidity_score": float,   # 0–100
        "bid_ask_ratio":   float,   # bid_vol / ask_vol (>1 = ביקוש)
        "buy_wall":        float,   # גודל הקיר הגדול בצד קנייה
        "sell_wall":       float,   # גודל הקיר הגדול בצד מכירה
        "imbalance_pct":   float,   # % עודף צד הביקוש
        "available":       bool,
    }
    """
    result = {
        "liquidity_score": 50.0,
        "bid_ask_ratio":   1.0,
        "buy_wall":        0.0,
        "sell_wall":       0.0,
        "imbalance_pct":   0.0,
        "available":       False,
    }

    try:
        r = requests.get(
            f"{_SPOT}/api/v1/market/orderbook/level2_{depth}",
            headers=_HEADERS,
            params={"symbol": _kucoin_sym(symbol)},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return result

        data = r.json().get("data", {})
        bids = data.get("bids", [])   # [[price, size], ...]
        asks = data.get("asks", [])

        if not bids or not asks:
            return result

        # ── נפח כולל ─────────────────────────────────────────────────────────
        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        total   = bid_vol + ask_vol

        if total == 0:
            return result

        result["available"] = True

        # ── Bid/Ask Ratio ─────────────────────────────────────────────────────
        ratio = bid_vol / ask_vol if ask_vol > 0 else 1.0
        result["bid_ask_ratio"] = round(ratio, 3)

        # ── Imbalance % ───────────────────────────────────────────────────────
        imbalance = (bid_vol - ask_vol) / total * 100
        result["imbalance_pct"] = round(imbalance, 2)

        # ── Buy/Sell Walls ────────────────────────────────────────────────────
        # קיר = הרמה עם הנפח הגדול ביותר ב-10 הרמות הראשונות
        top_bids = bids[:10]
        top_asks = asks[:10]
        result["buy_wall"]  = max(float(b[1]) for b in top_bids) if top_bids else 0
        result["sell_wall"] = max(float(a[1]) for a in top_asks) if top_asks else 0

        # ── Liquidity Score ───────────────────────────────────────────────────
        score = 50.0

        # Bid/Ask ratio
        if ratio > 2.0:    score += 25
        elif ratio > 1.5:  score += 15
        elif ratio > 1.2:  score += 8
        elif ratio < 0.7:  score -= 20
        elif ratio < 0.9:  score -= 10

        # Sell wall vs Buy wall
        wall_ratio = result["buy_wall"] / (result["sell_wall"] + 1e-10)
        if wall_ratio > 3:    score += 15
        elif wall_ratio > 1.5: score += 8
        elif wall_ratio < 0.5: score -= 15

        result["liquidity_score"] = round(max(0.0, min(100.0, score)), 1)

        log.debug(
            f"Liquidity {symbol}: score={result['liquidity_score']} "
            f"ratio={ratio:.2f} imb={imbalance:.1f}%"
        )

    except Exception as e:
        log.debug(f"Liquidity failed {symbol}: {e}")

    return result
