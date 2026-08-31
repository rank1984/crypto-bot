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
CACHE_DIR = "cache"

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
