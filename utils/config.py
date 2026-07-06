"""
CRYPTO-BOT Elite — Configuration
"""
import os

# ─── APIs (הכל חינמי, לא דורש הרשמה) ────────────────────────────────────────
COINGECKO_BASE  = "https://api.coingecko.com/api/v3"
KUCOIN_BASE     = "https://api.kucoin.com"

# Universe filters
QUOTE_ASSET      = "USDT"
MIN_DAILY_VOLUME = float(os.getenv("MIN_DAILY_VOLUME", "5000000"))
MIN_PRICE        = float(os.getenv("MIN_PRICE", "0.0001"))
MAX_SYMBOLS      = int(os.getenv("MAX_SYMBOLS", "200"))

# Candle timeframes
TIMEFRAMES      = ["1min", "5min", "15min", "1hour"]
CANDLES_PER_TF  = 100

# Cache
CACHE_DIR         = "data"
CACHE_TTL_SECONDS = 60

# Scoring weights
SCORE_WEIGHTS = {
    "freshness": 0.30,
    "momentum":  0.25,
    "breakout":  0.25,
    "pattern":   0.20,
}

FRESHNESS_WEIGHTS = {
    "high_age":  0.25,
    "pullback":  0.20,
    "momentum":  0.20,
    "vwap":      0.15,
    "vol_accel": 0.20,
}

# Universe
USE_DYNAMIC_UNIVERSE  = os.getenv("USE_DYNAMIC_UNIVERSE", "true").lower() == "true"

# Telegram
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Scanner loop
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

TOP_N = int(os.getenv("TOP_N", "5"))

TRADE_MODE = os.getenv("TRADE_MODE", "BALANCED")
