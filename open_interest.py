"""
CRYPTO-BOT Elite — Open Interest + Funding Rate

Flow > Price. כסף חכם מסתכל על זרימת כסף, לא על מחיר.

מקור: KuCoin Futures API (חינמי, ללא הרשמה)

הלוגיקה:
    מחיר עולה + OI עולה   → כסף חדש נכנס         ✅ איכותי
    מחיר עולה + OI יורד   → Short covering         ⚠️  פחות איכותי
    Funding חיובי קיצוני   → לונגים משלמים הרבה   ⚠️  סיכון squeeze
    Funding שלילי          → שורטים כבדים          🎯 potential squeeze
"""
import requests
from utils.logger import get_logger

log = get_logger(__name__)

_BASE    = "https://api-futures.kucoin.com"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_TIMEOUT = 8


def _kucoin_futures_symbol(symbol: str) -> str:
    """BTCUSDT → XBTUSDTM  /  ETHUSDT → ETHUSDTM"""
    base = symbol.replace("USDT", "")
    if base == "BTC":
        base = "XBT"
    return f"{base}USDTM"


def get_oi_and_funding(symbol: str) -> dict:
    """
    מחזיר:
    {
        "oi":            float,   # Open Interest בדולרים
        "oi_change_pct": float,   # % שינוי מהשעה הקודמת
        "funding_rate":  float,   # Funding Rate (% per 8h)
        "funding_signal": str,    # "long_heavy" / "short_heavy" / "neutral"
        "flow_score":    float,   # 0–100
        "available":     bool,    # False אם אין futures לסימבול הזה
    }
    """
    result = {
        "oi": 0.0, "oi_change_pct": 0.0,
        "funding_rate": 0.0, "funding_signal": "neutral",
        "flow_score": 50.0, "available": False,
    }

    fut_sym = _kucoin_futures_symbol(symbol)

    # ── Funding Rate ──────────────────────────────────────────────────────────
    try:
        r = requests.get(
            f"{_BASE}/api/v1/funding-rate/{fut_sym}/current",
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            funding = float(data.get("value", 0)) * 100   # המר ל-%
            result["funding_rate"]  = round(funding, 5)
            result["available"]     = True

            if funding > 0.05:
                result["funding_signal"] = "long_heavy"
            elif funding < -0.01:
                result["funding_signal"] = "short_heavy"
            else:
                result["funding_signal"] = "neutral"
    except Exception as e:
        log.debug(f"Funding rate failed {symbol}: {e}")

    # ── Open Interest ─────────────────────────────────────────────────────────
    try:
        r = requests.get(
            f"{_BASE}/api/v1/contracts/{fut_sym}",
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            oi   = float(data.get("openInterest", 0))
            multiplier = float(data.get("multiplier", 1))
            mark_price = float(data.get("markPrice", 1))
            result["oi"] = round(oi * multiplier * mark_price, 0)
            result["available"] = True
    except Exception as e:
        log.debug(f"OI failed {symbol}: {e}")

    # ── Flow Score ────────────────────────────────────────────────────────────
    if result["available"]:
        score = 50.0
        fr    = result["funding_rate"]

        # Funding שלילי = שורטים כבדים = potential squeeze = בוליש
        if fr < -0.01:   score += 20
        elif fr < 0:     score += 10
        elif fr > 0.05:  score -= 15   # לונגים קיצוניים = מסוכן
        elif fr > 0.02:  score -= 5

        result["flow_score"] = round(max(0, min(100, score)), 1)

    return result
