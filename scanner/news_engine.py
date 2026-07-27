"""
CRYPTO-BOT Elite — News & Sentiment Engine v2
"""
import requests
import time
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

_cache = {
    "market_health": {"value": 50, "ts": 0},
    "news_score": {"value": 50, "ts": 0},
    "fear_greed": {"value": 50, "ts": 0},
}
CACHE_TTL = 600  # 10 דקות


def _from_cache(key):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["value"]
    return None


def _to_cache(key, value):
    _cache[key] = {"value": value, "ts": time.time()}


def get_fear_greed() -> int:
    cached = _from_cache("fear_greed")
    if cached is not None:
        return cached
    try:
        resp = requests.get("https://api.alternative.me/fng/", timeout=5)
        data = resp.json()
        value = int(data["data"][0]["value"])
        _to_cache("fear_greed", value)
        return value
    except Exception as e:
        log.warning(f"Fear&Greed error: {e}")
        return 50


def get_news_score() -> int:
    cached = _from_cache("news_score")
    if cached is not None:
        return cached

    try:
        url = "https://cryptopanic.com/news/rss/"
        r = requests.get(url, timeout=10)

        # נסיון פרסור עם defusedxml (אם מותקן), אחרת fallback
        try:
            import defusedxml.ElementTree as ET
        except ImportError:
            import xml.etree.ElementTree as ET

        root = ET.fromstring(r.content)

        positive_count = 0
        total_count = 0

        for item in root.iter("item"):
            title = item.find("title").text.lower() if item.find("title") is not None else ""
            description = item.find("description").text.lower() if item.find("description") is not None else ""

            positive_words = ["bull", "surge", "rally", "jump", "green", "buy", "long", "profit", "gain", "adoption"]
            negative_words = ["bear", "crash", "dump", "red", "sell", "short", "loss", "ban", "hack", "scam"]

            pos = sum(1 for w in positive_words if w in title or w in description)
            neg = sum(1 for w in negative_words if w in title or w in description)

            if pos > neg:
                positive_count += 1
            total_count += 1

        if total_count == 0:
            score = 50
        else:
            score = int((positive_count / total_count) * 100)

        _to_cache("news_score", score)
        log.info(f"News Score (CryptoPanic RSS): {score}")
        return score

    except Exception as e:
        log.warning(f"CryptoPanic RSS error: {e}")
        score = min(100, max(0, get_fear_greed() + 10))
        _to_cache("news_score", score)
        return score


def get_market_health(btc_change_1h: float,
                      oi_change_pct: float,
                      funding_rate: float = 0.0,
                      liquidations: float = 0.0,
                      news_score: int = None,
                      fear_greed: int = None,
                      regime: str = "RANGE") -> float:
    if news_score is None:
        news_score = get_news_score()
    if fear_greed is None:
        fear_greed = get_fear_greed()

    btc_score = 50
    if btc_change_1h > 1.0:
        btc_score = 80
    elif btc_change_1h > 0.5:
        btc_score = 65
    elif btc_change_1h < -1.0:
        btc_score = 20
    elif btc_change_1h < -0.5:
        btc_score = 35

    if regime == "TRENDING_BULL":
        btc_score = min(100, btc_score + 15)
    elif regime == "TRENDING_BEAR":
        btc_score = max(0, btc_score - 15)
    elif regime == "RISK_OFF":
        btc_score = max(0, btc_score - 25)

    if oi_change_pct > 5:
        oi_score = 85
    elif oi_change_pct > 2:
        oi_score = 65
    elif oi_change_pct < -5:
        oi_score = 15
    elif oi_change_pct < -2:
        oi_score = 35
    else:
        oi_score = 50

    if funding_rate < -0.01:
        funding_score = 75
    elif funding_rate > 0.05:
        funding_score = 25
    else:
        funding_score = 50

    if liquidations > 100_000_000:
        liq_score = 90
    elif liquidations > 50_000_000:
        liq_score = 70
    else:
        liq_score = 50

    news_component = news_score
    fg_component = fear_greed

    health = (btc_score * 0.30 + oi_score * 0.20 + funding_score * 0.15 +
              liq_score * 0.15 + news_component * 0.10 + fg_component * 0.10)

    _to_cache("market_health", health)
    return round(health, 1)


def log_news(headline, sentiment, impact, btc_price):
    pass
