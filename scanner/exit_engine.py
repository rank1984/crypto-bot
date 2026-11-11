"""
CRYPTO-BOT Elite — Smart Exit Engine v3.0

Exit Score 0–100:
    CVD התהפך            +20
    OI יורד בחדות        +20
    RS מול BTC נשבר      +15
    EMA20 1H נשבר        +25
    Volume Exhaustion    +10
    Whale Distribution   +10

Output:
    HOLD  (0–35)
    TRIM  (36–60)
    EXIT  (61+)

v3.0 fixes:
  - FIX: update_trailing_stop_atr accepts current_price and trade_high;
         never returns a stop >= current_price
  - FIX: _exit_decision uses confidence == total (was × 1.2 — created
         61→73.2 mismatch against manager's >=80 check). Manager should now
         trust exit_signal directly, or check confidence >= EXIT_MIN_CONFIDENCE.
  - FIX: TRIM is a first-class signal — manager MUST act on it
  - FIX: document that CVD/Whale are proxies, not real order-flow
  - ADD: robust None/NaN handling in every component
  - ADD: _sanity_check helper
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict, Any

from utils.logger import get_logger
from utils import config

log = get_logger(__name__)


# ── Sanity helpers ────────────────────────────────────────────
def _df_ok(df: pd.DataFrame, min_len: int) -> bool:
    return df is not None and not df.empty and len(df) >= min_len


def _safe_float(x, default=0.0) -> float:
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


# ─── A. CVD Reversal ──────────────────────────────────────────
# NOTE: This is a PROXY for CVD, estimated from where close sits within the
# bar's range. It is NOT true order-flow CVD. Treat as a heuristic, not data.

def _cvd_reversal(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if not _df_ok(df_5m, 15):
        return False, 0.0

    close = df_5m["close"]
    high  = df_5m["high"]
    low   = df_5m["low"]
    vol   = df_5m["volume"]

    hl = (high - low).replace(0, np.nan)
    buy_vol = ((close - low) / hl * vol).fillna(vol * 0.5)
    delta = buy_vol - (vol - buy_vol)

    recent_cvd = float(delta.iloc[-5:].sum())
    prior_cvd  = float(delta.iloc[-10:-5].sum())

    reversed_ = prior_cvd > 0 and recent_cvd < 0
    if reversed_:
        score = 20.0
    else:
        denom = abs(prior_cvd) + 1e-10
        score = max(0.0, (prior_cvd - recent_cvd) / denom * 10)

    return reversed_, round(min(20.0, score), 1)


# ─── B. OI Drop ───────────────────────────────────────────────
def _oi_dropping(oi_change_pct: float) -> Tuple[bool, float]:
    oi = _safe_float(oi_change_pct)
    if oi < -5.0:
        return True, 20.0
    if oi < -2.0:
        return True, 12.0
    if oi < 0:
        return False, 5.0
    return False, 0.0


# ─── C. RS Breakdown ──────────────────────────────────────────
def _rs_breakdown(rs_1h: float, rs_4h: float) -> Tuple[bool, float]:
    r1 = _safe_float(rs_1h)
    r4 = _safe_float(rs_4h)
    if r1 < 0 and r4 < 0:
        return True, round(min(15.0, abs(r1 + r4) * 2), 1)
    if r1 < -1.0 or r4 < -1.0:
        return False, 5.0
    return False, 0.0


# ─── D. EMA20 1H Break ────────────────────────────────────────
def _ema20_break(df_1h: pd.DataFrame) -> Tuple[bool, float]:
    if not _df_ok(df_1h, 22):
        return False, 0.0

    close = df_1h["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()

    last_close = float(close.iloc[-1])
    last_ema   = float(ema20.iloc[-1])
    prev_close = float(close.iloc[-2])
    prev_ema   = float(ema20.iloc[-2])

    if last_ema <= 0:
        return False, 0.0

    broke_now = last_close < last_ema
    was_above = prev_close > prev_ema

    if broke_now and was_above:
        return True, 25.0
    if broke_now:
        gap_pct = (last_ema - last_close) / last_ema * 100
        return True, min(25.0, 15.0 + gap_pct * 2.0)
    return False, 0.0


# ─── E. Volume Exhaustion ─────────────────────────────────────
def _volume_exhaustion(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if not _df_ok(df_5m, 20):
        return False, 0.0

    vol = df_5m["volume"]
    peak_vol = float(vol.iloc[-20:-5].max())
    recent_avg = float(vol.iloc[-5:].mean())

    if peak_vol <= 0:
        return False, 0.0

    ratio = recent_avg / peak_vol
    if ratio < 0.3:  return True, 10.0
    if ratio < 0.5:  return True, 6.0
    if ratio < 0.7:  return False, 2.0
    return False, 0.0


# ─── F. Whale Distribution ────────────────────────────────────
# NOTE: This is a PROXY — red bars with high volume. NOT real whale detection.

def _whale_distribution(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if not _df_ok(df_5m, 10):
        return False, 0.0

    recent = df_5m.iloc[-5:]
    avg_vol = float(df_5m["volume"].iloc[-20:-5].mean())
    if avg_vol <= 0:
        return False, 0.0

    distribution_score = 0.0
    for _, row in recent.iterrows():
        is_red = float(row["close"]) < float(row["open"])
        high_vol = float(row["volume"]) > avg_vol * 2.5
        if is_red and high_vol:
            distribution_score += 5.0

    return distribution_score >= 10.0, min(10.0, distribution_score)


# ─── G. Trailing Stop (ATR-based) — v3.0 ──────────────────────
def update_trailing_stop_atr(
    df_5m: pd.DataFrame,
    current_stop: float,
    atr_mult: float = 2.0,
    current_price: Optional[float] = None,
    trade_high: Optional[float] = None,
) -> Optional[float]:
    """
    Returns a new stop if it's an improvement AND safe, else None.

    Safety guarantees (v3.0):
      - Never returns a stop <= current_stop (only ratchets up)
      - Never returns a stop >= current_price (would trigger instantly)
      - Never returns NaN/inf

    Args:
        df_5m: recent 5m bars (used for ATR)
        current_stop: current stop level
        atr_mult: ATR multiplier for this state
        current_price: latest close — if provided, enforces stop < current_price
        trade_high: highest price since entry — if provided, used as the
                    trailing anchor instead of df['high'].max() (which only
                    covers the passed window and misses the trade's peak)
    """
    if not _df_ok(df_5m, 15):
        return None

    high = df_5m["high"].iloc[-14:]
    low = df_5m["low"].iloc[-14:]
    close_prev = df_5m["close"].shift(1).iloc[-14:]
    tr = pd.concat(
        [high - low, (high - close_prev).abs(), (low - close_prev).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(tr.mean())

    if np.isnan(atr) or np.isinf(atr) or atr <= 0:
        return None

    if trade_high is not None and trade_high > 0:
        anchor_high = float(trade_high)
    else:
        anchor_high = float(df_5m["high"].max())

    new_stop = anchor_high - atr * atr_mult

    # Ratchet up only
    if new_stop <= current_stop:
        return None

    # Safety: never above market
    if current_price is not None and current_price > 0 and new_stop >= current_price:
        return None

    if np.isnan(new_stop) or np.isinf(new_stop):
        return None

    return float(new_stop)


# ─── Decision ─────────────────────────────────────────────────
def _exit_decision(score: float) -> Tuple[str, str, str]:
    if score >= config.EXIT_SCORE_EXIT:
        return "EXIT", "🔴", "צא מהפוזיציה"
    if score >= config.EXIT_SCORE_TRIM:
        return "TRIM", "🟡", "שקול למכור חלק"
    return "HOLD", "🟢", "המהלך ממשיך — תשאר"


# ─── Main Entry ───────────────────────────────────────────────
def calc_exit_score(
    df_5m: pd.DataFrame,
    df_1h: pd.DataFrame,
    rs_1h: float = 0.0,
    rs_4h: float = 0.0,
    oi_change_pct: float = 0.0,
    current_gain_pct: float = 0.0,
    flow_score: float = 50.0,
    market_health: float = 70.0,
) -> Dict[str, Any]:
    """
    Returns:
        exit_signal:   "HOLD" | "TRIM" | "EXIT"
        exit_score:    0–100
        confidence:    0–100 (== exit_score, no multiplier)
        is_actionable: True if manager should act (EXIT/TRIM + confidence threshold)
        reasons:       list[str]
        components:    dict of per-factor scores
    """
    cvd_rev,   cvd_s = _cvd_reversal(df_5m)
    oi_drop,   oi_s  = _oi_dropping(oi_change_pct)
    rs_break,  rs_s  = _rs_breakdown(rs_1h, rs_4h)
    ema_break, ema_s = _ema20_break(df_1h)
    vol_exh,   vol_s = _volume_exhaustion(df_5m)
    whale_dist, whl_s = _whale_distribution(df_5m)

    total = cvd_s + oi_s + rs_s + ema_s + vol_s + whl_s

    flow_score = _safe_float(flow_score, 50.0)
    market_health = _safe_float(market_health, 70.0)
    current_gain_pct = _safe_float(current_gain_pct, 0.0)

    if flow_score < 40:
        total += 10
    if flow_score < 25:
        total += 15

    if market_health < 50:
        total += 10
    if market_health < 30:
        total += 20

    if current_gain_pct >= 30 and total >= 25:
        total += 10
    if current_gain_pct >= 50 and total >= 20:
        total += 15

    total = round(min(100.0, total), 1)

    signal, emoji, desc = _exit_decision(total)

    # confidence == total (was ×1.2 — broke manager's EXIT gate)
    confidence = total
    is_actionable = (
        signal in ("EXIT", "TRIM")
        and confidence >= config.EXIT_MIN_CONFIDENCE_TO_ACT
    )

    reasons = []
    if cvd_rev:     reasons.append("CVD התהפך — מוכרים השתלטו (proxy)")
    if oi_drop:     reasons.append("OI יורד — כסף יוצא")
    if rs_break:    reasons.append("RS מול BTC נשבר")
    if ema_break:   reasons.append("EMA20 1H נשבר — שינוי מבנה")
    if vol_exh:     reasons.append("Volume מתייבש")
    if whale_dist:  reasons.append("Whale Distribution מזוהה (proxy)")
    if flow_score < 40: reasons.append("Flow נחלש")
    if market_health < 50: reasons.append("Market Health ירוד")

    return {
        "exit_signal": signal,
        "exit_emoji": emoji,
        "exit_desc": desc,
        "exit_score": total,
        "confidence": confidence,
        "is_actionable": is_actionable,
        "reasons": reasons,
        "components": {
            "cvd_reversal":   cvd_s,
            "oi_drop":        oi_s,
            "rs_breakdown":   rs_s,
            "ema20_break":    ema_s,
            "vol_exhaustion": vol_s,
            "whale_dist":     whl_s,
        },
    }
