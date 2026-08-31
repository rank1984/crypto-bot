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
# MULTI-DAY RESEARCH (optional)
# ============================================================
MULTIDAY_ENABLED = os.getenv("MULTIDAY_ENABLED", "true").lower() == "true"
MIN_1D_CANDLES = 60
MIN_4H_CANDLES = 30
