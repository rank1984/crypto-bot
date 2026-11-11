"""
CRYPTO-BOT Elite — Configuration (v10.0 — PnL Trust Edition)
Changes from v9.3:
  - ADD: COSTS section (FEE_PCT, SLIPPAGE_PCT, MIN_COST_TO_RISK_RATIO)
  - ADD: TP1_SELL_RATIO, TP2_SELL_RATIO — centralized (no more magic numbers)
  - ADD: TRAILING_ATR_* — centralized ATR multipliers
  - CHANGE: MIN_STOP_PCT raised to 0.012 (was 0.006) — cost/risk was ~0.5R
  - CHANGE: ADVISOR_AI_MIN/MAX range (was ADVISOR_MIN_AI=60 — data shows 20-40 is hot zone)
  - CHANGE: TIMEOUT_HOURS is now imported by tracker (single source)
  - NOTE: All production values preserved in comments for easy rollback
"""
import os

# ============================================================
# SCAN INTERVAL
# ============================================================
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", 3600))

# ============================================================
# UNIVERSE
# ============================================================
USE_DYNAMIC_UNIVERSE = True
MAX_SYMBOLS = 150
MIN_PRICE = 0.001
MIN_DAILY_VOLUME = 1_000_000
TOP_N = 5

MIN_MARKET_CAP_USD = float(os.getenv("MIN_MARKET_CAP_USD", 50_000_000))
MAX_MARKET_CAP_USD = float(os.getenv("MAX_MARKET_CAP_USD", 2_000_000_000))

# ============================================================
# API
# ============================================================
COINGECKO_BASE = os.getenv("COINGECKO_BASE", "https://api.coingecko.com/api/v3")
KUCOIN_BASE = os.getenv("KUCOIN_BASE", "https://api.kucoin.com/api/v1")
KUCOIN_FUTURES_BASE = os.getenv("KUCOIN_FUTURES_BASE", "https://api-futures.kucoin.com/api/v1")

# ============================================================
# MARKET DATA
# ============================================================
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
CANDLES_PER_TF = {
    "1m": 200, "5m": 200, "15m": 200, "30m": 200,
    "1h": 200, "4h": 200, "1d": 200,
}
BAR_DURATION_MIN = 5  # 5m candles — used for ambiguity detection

# ============================================================
# CACHE
# ============================================================
CACHE_DIR = os.getenv("CACHE_DIR", "cache")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))

# ============================================================
# SCORING
# ============================================================
SCORE_WEIGHTS = {
    "ai_score": 0.30, "flow_score": 0.25, "pre_score": 0.15,
    "oi_change": 0.10, "rs_1h": 0.10, "prob_boost": 0.10,
}
FRESHNESS_WEIGHTS = {
    "high_age": 0.25, "pullback": 0.20, "momentum": 0.20,
    "vwap": 0.15, "vol_accel": 0.20,
}

# ============================================================
# SCORING THRESHOLDS
# ============================================================
MIN_AI_SCORE = 50.0
MIN_FLOW_SCORE = 30.0
MIN_PROBABILITY = 45.0
MIN_RS_SCORE = 0.3
MIN_MARKET_HEALTH = 50.0

# ============================================================
# TRADING
# ============================================================
MAX_TRADES = 2
PORTFOLIO_CAPITAL = 500.0
MAX_RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.05

# ============================================================
# COSTS — v10.0 (critical: costs determine if edge is real)
# ============================================================
# Round-trip fee: 0.1% per side (taker) = 0.2% round trip
FEE_PCT = float(os.getenv("FEE_PCT", 0.002))
# Round-trip slippage estimate: entry + exit
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", 0.001))
# Alias kept for backward compat (some code reads EXIT_SLIPPAGE_PCT)
EXIT_SLIPPAGE_PCT = SLIPPAGE_PCT

# Minimum acceptable cost/risk ratio. If (FEE+SLIP)/stop_pct exceeds this,
# the trade is likely unprofitable even with positive gross edge.
MIN_COST_TO_RISK_RATIO = float(os.getenv("MIN_COST_TO_RISK_RATIO", 0.25))

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SILENT_MODE = os.getenv("SILENT_MODE", "true").lower() == "true"

# ============================================================
# PATHS
# ============================================================
DATA_DIR = "data"
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ============================================================
# MULTI-DAY (disabled for stress test)
# ============================================================
MULTIDAY_ENABLED = os.getenv("MULTIDAY_ENABLED", "false").lower() == "true"
MIN_1D_CANDLES = 60
MIN_4H_CANDLES = 30

# ============================================================
# EXIT / SIMULATION — single source of truth for exit logic
# ============================================================
TIMEOUT_HOURS = 48

# TP sell ratios (of CURRENT position at the time of the sell)
# TP1 sells 20% of original position
TP1_SELL_RATIO = float(os.getenv("TP1_SELL_RATIO", 0.20))
# TP2 sells 20% of REMAINING position (≈16% of original)
TP2_SELL_RATIO = float(os.getenv("TP2_SELL_RATIO", 0.20))

# ATR multipliers for trailing stop, by state
TRAILING_ATR_BASE = float(os.getenv("TRAILING_ATR_BASE", 3.0))       # ACTIVE, pre-TP1
TRAILING_ATR_BREAKEVEN = float(os.getenv("TRAILING_ATR_BREAKEVEN", 1.8))
TRAILING_ATR_RUNNER = float(os.getenv("TRAILING_ATR_RUNNER", 1.5))    # post-TP2
TRAILING_ATR_AFTER_TP1 = float(os.getenv("TRAILING_ATR_AFTER_TP1", 2.5))

# Exit engine thresholds (spec → execution)
EXIT_SCORE_EXIT = 61.0
EXIT_SCORE_TRIM = 36.0
EXIT_MIN_CONFIDENCE_TO_ACT = 61.0   # aligned with EXIT_SCORE_EXIT (was 80 in manager — 66.7 actual)

# ============================================================
# LIQUIDITY
# ============================================================
MIN_LIQUIDITY_USD = 500_000
MAX_SPREAD_PCT = 0.02

# ============================================================
# FEATURE FLAGS
# ============================================================
ENABLE_TRAILING_STOP = True
ENABLE_PARTIAL_TAKE_PROFIT = True
ENABLE_SYMPATHY_TRADES = True

# ============================================================
# BACKTEST
# ============================================================
REPLAY_START_DATE = "2025-01-01"
REPLAY_END_DATE = "2025-12-31"

# ============================================================
# STRESS TEST 7-DAY — v10.0 revised
# ============================================================
# Production values (for future):
#   MIN_STOP_PCT = 0.008
#   MIN_TP_PCT = 0.015
#   MIN_RR_RATIO = 1.8
#
# v9.3 stress test (0.6% stop) → cost/risk ≈ 0.5R — destructive.
# v10.0 stress test (1.2% stop) → cost/risk ≈ 0.25R — survivable.
MIN_STOP_PCT = float(os.getenv("MIN_STOP_PCT", 0.012))   # 1.2%
MIN_TP_PCT = float(os.getenv("MIN_TP_PCT", 0.024))       # 2.4% (RR ≥ 2.0)
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", 2.0))

# Kill switches
BLOCK_VWAP_RECLAIM = os.getenv("BLOCK_VWAP_RECLAIM", "1") == "1"
BLOCK_REGIME_BAD_RS_LOW = os.getenv("BLOCK_REGIME_BAD_RS_LOW", "1") == "1"

# Shadow tags
TAG_REGIME_BAD = "shadow_regime_bad"
TAG_RS_LOW = "shadow_rs_low"

# ============================================================
# INVESTMENT ADVISOR
# ============================================================
# v10.0: data-driven. The 51-trade sample showed:
#   AI 0-20  (n=25) → AvgR -0.13  ← loss zone
#   AI 20-40 (n=12) → AvgR +0.67  ← ONLY positive zone
#   AI 40-60 (n=13) → AvgR +0.15  ← weak
#   AI 60-80 (n=1)  → structural dead zone (no DIP_BUYs)
ADVISOR_AI_MIN = int(os.getenv("ADVISOR_AI_MIN", 20))
ADVISOR_AI_MAX = int(os.getenv("ADVISOR_AI_MAX", 40))
ADVISOR_MIN_AI = ADVISOR_AI_MIN          # legacy alias
ADVISOR_TOP_N = 3
ADVISOR_RECENCY_DAYS = 90
ADVISOR_MIN_SAMPLE = int(os.getenv("ADVISOR_MIN_SAMPLE", 20))
ADVISOR_MIN_AVG_R = 0.0
ADVISOR_MIN_TP1_RATE = 0.25
