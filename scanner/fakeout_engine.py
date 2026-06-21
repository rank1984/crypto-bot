"""
CRYPTO-BOT Elite — False Breakout Detector

מונע כניסה לפריצות מזויפות.

Penalties:
    Upper Wick גדול    → wick rejection
    RVOL בלי מומנטום   → volume spike ריק
    Divergence vs BTC  → מטבע עולה אבל BTC שלילי
    VWAP extension     → קנייה מרוחקת מדי
    RSI > 75           → קניית יתר

מחזיר:
    {
        "is_fakeout":    bool,
        "confidence":    float,  # כמה בטוחים שזה fakeout (0-100)
        "penalties":     list,   # סיבות
        "fakeout_score": float,  # 0 = נקי, 100 = fakeout ברור
    }
"""
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)


def detect_fakeout(
    df_5m:       pd.DataFrame,
    rvol:        float,
    momentum_15m: float,
    momentum_5m:  float,
    rs_btc_1h:   float,
    vwap_dist:   float,
    rsi_14:      float,
    btc_mom_1h:  float = 0.0,
) -> dict:
    """
    מחזיר ניתוח fakeout מלא.

    fakeout_score:
        0–30   = ירוק — סיגנל נקי
        31–60  = צהוב — זהירות
        61–100 = אדום — fakeout סביר
    """
    penalties = []
    score     = 0.0

    # ── 1. Upper Wick Rejection ───────────────────────────────────────────────
    if df_5m is not None and len(df_5m) >= 2:
        last  = df_5m.iloc[-1]
        body  = abs(float(last["close"]) - float(last["open"]))
        upper = float(last["high"]) - max(float(last["close"]), float(last["open"]))
        if body > 0 and upper > body * 2:
            score += 30
            penalties.append(f"Upper wick rejection ({upper/body:.1f}x body)")
        elif body > 0 and upper > body * 1.5:
            score += 15
            penalties.append(f"Large upper wick ({upper/body:.1f}x body)")

    # ── 2. RVOL Spike בלי מומנטום (AGT pattern) ──────────────────────────────
    if rvol > 8.0 and momentum_15m < 0.5:
        score += 25
        penalties.append(f"RVOL spike {rvol:.1f}x without momentum ({momentum_15m:.1f}%)")
    elif rvol > 5.0 and momentum_15m < 0.3:
        score += 15
        penalties.append(f"High RVOL {rvol:.1f}x, weak momentum")

    # ── 3. Divergence vs BTC ──────────────────────────────────────────────────
    coin_rising = momentum_5m > 0.5
    btc_falling = btc_mom_1h < -0.5 or rs_btc_1h < -1.0
    if coin_rising and btc_falling:
        score += 20
        penalties.append(f"Divergence: coin up but BTC weak (RS={rs_btc_1h:.1f}%)")

    # ── 4. VWAP Extension ─────────────────────────────────────────────────────
    if abs(vwap_dist) > 6.0:
        score += 20
        penalties.append(f"VWAP extension {vwap_dist:.1f}%")
    elif abs(vwap_dist) > 4.0:
        score += 10
        penalties.append(f"VWAP distance {vwap_dist:.1f}%")

    # ── 5. RSI Overbought ─────────────────────────────────────────────────────
    if rsi_14 > 80:
        score += 20
        penalties.append(f"RSI overbought {rsi_14:.0f}")
    elif rsi_14 > 75:
        score += 10
        penalties.append(f"RSI high {rsi_14:.0f}")

    score = min(100.0, score)

    # Confidence: כמה בטוחים שזה fakeout
    is_fakeout  = score >= 50
    confidence  = round(score, 1)

    if penalties:
        log.debug(f"Fakeout signals: {penalties}")

    return {
        "is_fakeout":    is_fakeout,
        "confidence":    confidence,
        "fakeout_score": score,
        "penalties":     penalties,
    }
