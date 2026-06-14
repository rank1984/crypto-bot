"""
CRYPTO-BOT Elite — Configuration
כל ההגדרות במקום אחד.
"""

# ─── Binance ───────────────────────────────────────────────────────────────────
BINANCE_BASE_URL = "https://api.binance.com"

# Universe filters
QUOTE_ASSET       = "USDT"
MIN_DAILY_VOLUME  = 5_000_000   # $5M
MIN_PRICE         = 0.0001
MAX_SYMBOLS       = 1000        # upper cap on universe size

# Candle timeframes to download
TIMEFRAMES = ["1m", "5m", "15m", "1h"]
CANDLES_PER_TF = 100            # last N candles per timeframe

# ─── Caching ───────────────────────────────────────────────────────────────────
CACHE_DIR         = "data"
CACHE_TTL_SECONDS = 60          # re-use cached candles if fresher than this

# ─── Scoring weights ───────────────────────────────────────────────────────────
SCORE_WEIGHTS = {
    "freshness": 0.30,
    "momentum":  0.25,
    "breakout":  0.25,
    "pattern":   0.20,
}

# Freshness sub-weights
FRESHNESS_WEIGHTS = {
    "high_age":    0.25,
    "pullback":    0.20,
    "momentum":    0.20,
    "vwap":        0.15,
    "vol_accel":   0.20,
}

# ─── Ranking ───────────────────────────────────────────────────────────────────
TOP_N = 5                       # coins to send to Telegram

# ─── Telegram ──────────────────────────────────────────────────────────────────
# Set these via environment variables — never hardcode tokens.
import os
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Scanner loop ──────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 300     # 5 minutes
