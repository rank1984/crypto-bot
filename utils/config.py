"""
CRYPTO-BOT Elite — Configuration
"""

import os

# ============================================================
# SCAN INTERVAL (seconds)
# ============================================================
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", 3600))  # 1 hour

# ============================================================
# UNIVERSE
# ============================================================
USE_DYNAMIC_UNIVERSE = True
MAX_SYMBOLS = 150
MIN_PRICE = 0.001
MIN_DAILY_VOLUME = 1_000_000  # USD

# ============================================================
# API & EXTERNAL SERVICES
# ============================================================
COINGECKO_BASE = os.getenv("COINGECKO_BASE", "https://api.coingecko.com/api/v3")
KUCOIN_BASE = os.getenv("KUCOIN_BASE", "https://api.kucoin.com/api/v1")
KUCOIN_FUTURES_BASE = os.getenv("KUCOIN_FUTURES_BASE", "https://api-futures.kucoin.com/api/v1")

# ============================================================
# MARKET DATA
# ============================================================
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
CANDLES_PER_TF = {
    "1m": 200,
    "5m": 200,
    "15m": 200,
    "30m": 200,
    "1h": 200,
    "4h": 200,
    "1d": 200,
}

# ============================================================
# CACHE
# ============================================================
CACHE_DIR = os.getenv("CACHE_DIR", "cache")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))  # 5 minutes

# ============================================================
# TRADING PARAMETERS
# ============================================================
MAX_TRADES = 2
PORTFOLIO_CAPITAL = 500.0  # USD

# ============================================================
# RISK
# ============================================================
MAX_RISK_PER_TRADE = 0.02  # 2% of portfolio
MAX_DAILY_LOSS = 0.05      # 5% of portfolio

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ============================================================
# PATHS
# ============================================================
DATA_DIR = "data"
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ============================================================
# MULTI-DAY RESEARCH
# ============================================================
MULTIDAY_ENABLED = os.getenv("MULTIDAY_ENABLED", "true").lower() == "true"
MIN_1D_CANDLES = 60
MIN_4H_CANDLES = 30
