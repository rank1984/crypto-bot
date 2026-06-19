"""
CRYPTO-BOT Elite — Scoring Engine (V4–V6)

freshness_score  :얼마나 "טרי" הסיגנל (High Age, Pullback, Momentum, VWAP, Vol Accel)
momentum_score   : עוצמת המומנטום (RVOL, Dollar Volume, RSI, Trend)
breakout_score   : כמה קרוב לפריצה (proximity to high, vol accel, VWAP reclaim, momentum)
final_score      : weighted average של השלושה (+ pattern_score מ-V7)

כל ציון: 0–100
"""
import math
from utils.config import FRESHNESS_WEIGHTS, SCORE_WEIGHTS
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid(x: float, center: float, steepness: float = 1.0) -> float:
    """Maps any float to [0, 100] with a sigmoid centred at `center`."""
    return 100 / (1 + math.exp(-steepness * (x - center)))


# ─── Freshness Score (V4) ─────────────────────────────────────────────────────

def freshness_score(
    high_age_candles: float,   # how many candles ago was the recent high (5m candles)
    pullback_pct: float,       # % pullback from that high (positive = pulled back)
    momentum_5m: float,        # 5m momentum %
    vwap_dist: float,          # % above VWAP (positive = above)
    vol_accel: float,          # last_5m_vol / prev_5m_vol
) -> float:
    """
    Scores how "fresh" the setup is.
    A fresh setup: recent high, small pullback, accelerating, above VWAP.

    High Age  → the newer the high the better (0–3 candles = great, 20+ = stale)
    Pullback  → 1–5% pullback = ideal, 0% = no room, 10%+ = too deep
    Momentum  → positive = good
    VWAP      → above VWAP = good
    Vol Accel → > 1.5x = strong
    """
    # High Age: 0 candles old → 100, 20 candles old → ~5
    age_score = _clamp(100 * math.exp(-0.15 * max(high_age_candles, 0)))

    # Pullback: sweet spot 1–5%; 0% or >10% both score low
    pb = _clamp(pullback_pct, 0, 20)
    pullback_score = _clamp(100 * math.exp(-0.5 * (pb - 2.5) ** 2 / 4))

    # Momentum: sigmoid centred at 0%, full 100 at +5%
    mom_score = _sigmoid(momentum_5m, center=0, steepness=0.6)

    # VWAP distance: above = good, below = bad
    vwap_score = _sigmoid(vwap_dist, center=0, steepness=0.5)

    # Vol Acceleration: sigmoid centred at 1.0x, 100 at ~3x
    accel_score = _sigmoid(vol_accel, center=1.0, steepness=1.2)

    w = FRESHNESS_WEIGHTS
    score = (
        age_score      * w["high_age"]
        + pullback_score * w["pullback"]
        + mom_score      * w["momentum"]
        + vwap_score     * w["vwap"]
        + accel_score    * w["vol_accel"]
    )
    return round(_clamp(score), 1)


# ─── Momentum Score (V5) ──────────────────────────────────────────────────────

def momentum_score(
    rvol: float,           # relative volume
    dollar_volume: float,  # 5m dollar volume
    rsi_14: float,         # 0–100
    momentum_5m: float,    # 5m momentum %
    momentum_15m: float,   # 15m momentum %
) -> float:
    """
    Scores the strength of the momentum.
    Optimum: RVOL > 2x, RSI 55–70 (not overbought), rising momentum.
    """
    # RVOL: 1x → 20pts, 3x → ~80pts, 5x+ → ~100pts
    rvol_score   = _clamp(_sigmoid(rvol, center=2.0, steepness=0.8) * 1.1)

    # Dollar Volume: log-scaled so small coins still score well
    # $100k per 5m = 50pts, $1M+ = ~90pts
    dv_score = _clamp(math.log10(max(dollar_volume, 1)) * 15 - 15)

    # RSI: sweet spot 50–70; overbought (>75) and oversold (<45) penalised
    rsi_score = _clamp(100 - abs(rsi_14 - 62) * 2.5)

    # Trend alignment: both 5m and 15m positive = strong
    trend_bonus = 0
    if momentum_5m  > 0: trend_bonus += 25
    if momentum_15m > 0: trend_bonus += 25
    if momentum_5m  > 1: trend_bonus += 15   # extra for strong 5m
    if momentum_15m > 2: trend_bonus += 10   # extra for strong 15m

    score = (
        rvol_score  * 0.35
        + dv_score  * 0.25
        + rsi_score * 0.15
        + _clamp(trend_bonus, 0, 100) * 0.25
    )
    return round(_clamp(score), 1)


# ─── Breakout Score (V6) ──────────────────────────────────────────────────────

def breakout_score(
    proximity_to_high_pct: float,   # % below recent high (0 = AT high, 5 = 5% below)
    vol_accel: float,
    vwap_dist: float,
    momentum_5m: float,
    momentum_15m: float,
    atr_14: float,
    last_price: float,
) -> float:
    """
    The key score — how close is the coin to a real breakout?

    Ideal setup: within 1 ATR of high, VWAP reclaim, vol acceleration, momentum.
    """
    # Proximity to high: 0% away → 100pts, 5% → ~50pts, 10%+ → ~5pts
    prox_score = _clamp(100 * math.exp(-0.25 * max(proximity_to_high_pct, 0)))

    # Gate: אם אין מומנטום חיובי — Breakout Score מוגבל ל-40
    avg_mom = (momentum_5m + momentum_15m) / 2
    if avg_mom <= 0:
        return round(_clamp(prox_score * 0.4), 1)

    # VWAP Reclaim: above VWAP strongly preferred
    vwap_reclaim = _sigmoid(vwap_dist, center=0.3, steepness=1.0)

    # Volume surge at breakout point
    vol_score = _clamp(_sigmoid(vol_accel, center=1.5, steepness=0.9) * 1.1)

    # Momentum in right direction
    mom_score = _sigmoid((momentum_5m + momentum_15m) / 2, center=0, steepness=0.5)

    # ATR proximity bonus: price within 1 ATR of high = +15 bonus
    atr_bonus = 0.0
    if atr_14 > 0 and last_price > 0:
        atr_pct = (atr_14 / last_price) * 100
        if proximity_to_high_pct <= atr_pct:
            atr_bonus = 15.0

    score = (
        prox_score    * 0.35
        + vwap_reclaim * 0.20
        + vol_score    * 0.25
        + mom_score    * 0.20
        + atr_bonus
    )
    return round(_clamp(score), 1)


# ─── Final Score (V8) ─────────────────────────────────────────────────────────

def final_score(
    freshness: float,
    momentum: float,
    breakout: float,
    pattern: float = 50.0,
    rvol: float = 1.0,
    vol_accel: float = 1.0,
    vwap_dist: float = 0.0,
) -> float:
    # משקלים מעודכנים — momentum קיבל יותר משקל
    w = SCORE_WEIGHTS
    score = (
        freshness * 0.25
        + momentum * 0.30
        + breakout * 0.25
        + pattern  * 0.20
    )

    # בונוסים שמרחיבים את הסקאלה
    if rvol      > 3.0: score += 5
    if vol_accel > 5.0: score += 5
    if vwap_dist > 1.0: score += 3

    return round(_clamp(score), 1)

# ─── Hard Filters ─────────────────────────────────────────────────────────────

def passes_hard_filters(
    rsi_14: float,
    vwap_dist: float,
    momentum_5m: float,
    momentum_15m: float,
) -> tuple[bool, str]:
    """
    True = עובר. False = בחוץ — תמיד, ללא קשר לציון.

    RSI > 80        → קניית יתר קיצונית
    VWAP dist > 8%  → מחיר מופקע
    mom שלילי כפול  → מומנטום הפוך
    """
    if rsi_14 > 80:
        return False, f"RSI {rsi_14:.0f} > 80"
    if abs(vwap_dist) > 8.0:
        return False, f"VWAP dist {vwap_dist:.1f}% > 8%"
    if momentum_5m < -2.0 and momentum_15m < -1.0:
        return False, f"Negative momentum {momentum_5m:.1f}%/{momentum_15m:.1f}%"
    return True, ""


# ─── Trader Overrides ─────────────────────────────────────────────────────────

def apply_trader_overrides(base_score: float, c: dict) -> float:
    """
    קנסות ובונוסים שמשקפים שיקול דעת של סוחר מומנטום.
    לא פוסלים מטבע — משנים את מיקומו בדירוג.

    קנסות:   RSI 75-80 (-15) | VWAP > 5% (-10)
    בונוסים: RS חיובי (+8) | סטאפ הזהב (+15) | האצה (+5) | RSI אידאלי (+5)
    """
    score     = base_score
    rsi       = c.get("rsi_14",      50.0)
    vwap_dist = c.get("vwap_dist",    0.0)
    rvol      = c.get("rvol",         1.0)
    rs_1h     = c.get("rs_1h",        0.0)
    rs_4h     = c.get("rs_4h",        0.0)
    mom_5m    = c.get("momentum_5m",  0.0)
    mom_15m   = c.get("momentum_15m", 0.0)
    mom_1h    = c.get("momentum_1h",  0.0)

    # קנסות
    if rsi > 75:               score -= 15
    if abs(vwap_dist) > 5.0:   score -= 10

    # בונוס: חוזק יחסי מול BTC בשני טווחים
    if rs_1h > 0 and rs_4h > 0:
        score += 8

    # בונוס: סטאפ הזהב — נפח חריג + מחיר עדיין ליד VWAP
    if rvol > 5.0 and abs(vwap_dist) <= 2.0:
        score += 15

    # בונוס: האצת מומנטום (5m > 15m > 1h)
    if 0 < mom_1h < mom_15m < mom_5m:
        score += 5

    # בונוס: RSI באזור הכניסה האידאלי
    if 50 <= rsi <= 65:
        score += 5

    return round(_clamp(score), 1)
