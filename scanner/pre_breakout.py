"""
CRYPTO-BOT Elite — Pre-Breakout Engine

הפילוסופיה החדשה:
    לא "מי הכי חזק עכשיו?"
    אלא "מי נמצא רגע לפני Expansion גדול?"

מזהה 4 מצבים:
    ACCUMULATION      — צבירה שקטה, OI עולה, מחיר לא זז
    COMPRESSION       — ATR יורד, squeeze מתהדק
    MOMENTUM_IGNITION — ניצת מומנטום — הרגע הראשון של המהלך
    SHORT_SQUEEZE     — Funding שלילי + מחיר עולה

Pre-Score 0–100:
    25 — OI Expansion (כסף נכנס בלי שהמחיר זז)
    20 — CVD Divergence (קונים תוקפים בשקט)
    15 — Compression (ATR squeeze)
    15 — Multi-TF Alignment (15m+1h+4h מיושרים)
    15 — Relative Strength Early Signal
    10 — Funding Setup (squeeze potential)
"""
import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Phase Labels ─────────────────────────────────────────────────────────────

PHASES = {
    "EXPLOSION_IMMINENT": (80, "⚡ פריצה קרובה — מהלך גדול אפשרי"),
    "WATCH_CLOSELY":      (60, "👀 מעקב צמוד — בנייה מתקדמת"),
    "EARLY_BUILDUP":      (40, "🟡 התחלת בנייה — עוד מוקדם"),
    "TOO_EARLY":          (0,  "😴 מוקדם מדי"),
}

def get_phase(pre_score: float) -> tuple[str, str]:
    for name, (threshold, label) in PHASES.items():
        if pre_score >= threshold:
            return name, label
    return "TOO_EARLY", "😴 מוקדם מדי"


# ─── A. OI Expansion with Price Stillness ─────────────────────────────────────
# הסימן הכי חזק: כסף נכנס אבל מחיר עדיין לא זז

def _oi_accumulation(
    oi_change_pct: float,
    price_change_1h: float,
) -> float:
    """
    OI עולה + מחיר לא זז = צבירה שקטה = 25 נקודות מקס.
    OI עולה + מחיר זז = פחות מעניין (כבר קרה).
    """
    if oi_change_pct <= 0:
        return 0.0

    # ככל שהמחיר פחות זז ביחס ל-OI — הציון גבוה יותר
    price_move = abs(price_change_1h)
    if price_move < 0.5:    # מחיר כמעט לא זז — צבירה אמיתית
        score = min(25.0, oi_change_pct * 3)
    elif price_move < 2.0:  # זז קצת
        score = min(15.0, oi_change_pct * 2)
    else:                   # מחיר כבר זז — פחות מעניין
        score = min(8.0, oi_change_pct)

    return round(score, 1)


# ─── B. CVD Divergence ────────────────────────────────────────────────────────
# קונים תוקפים בשקט — CVD עולה אבל מחיר עדיין שטוח

def _cvd_divergence(df_5m: pd.DataFrame) -> float:
    """
    CVD עולה + מחיר שטוח = Divergence חיובי = עד 20 נק'.
    זה אחד הסימנים הכי מוקדמים לפני מהלך.
    """
    if df_5m is None or len(df_5m) < 20:
        return 0.0

    close = df_5m["close"]
    high  = df_5m["high"]
    low   = df_5m["low"]
    vol   = df_5m["volume"]

    hl = (high - low).replace(0, np.nan)
    buy_vol  = ((close - low) / hl * vol).fillna(vol * 0.5)
    delta    = (buy_vol - (vol - buy_vol)).cumsum()

    # CVD slope ב-10 הנרות האחרונים
    cvd_recent = delta.iloc[-10:].values
    price_recent = close.iloc[-10:].values

    if len(cvd_recent) < 5:
        return 0.0

    x = np.arange(len(cvd_recent))
    cvd_slope   = np.polyfit(x, cvd_recent / (abs(cvd_recent.mean()) + 1e-10), 1)[0]
    price_slope = np.polyfit(x, price_recent / (price_recent.mean() + 1e-10), 1)[0]

    # Divergence: CVD עולה בזמן שמחיר שטוח/יורד
    divergence = cvd_slope - price_slope

    if divergence > 0.1:   # קונים נכנסים בשקט
        score = min(20.0, divergence * 100)
    elif divergence > 0:
        score = min(10.0, divergence * 50)
    else:
        score = 0.0

    return round(score, 1)


# ─── C. Compression (ATR + Bollinger Squeeze) ─────────────────────────────────

def _compression(df_5m: pd.DataFrame) -> tuple[float, bool]:
    """
    ATR + Bollinger squeeze = שקט לפני סערה.
    מחזיר (score_0_15, is_squeezed).
    """
    if df_5m is None or len(df_5m) < 25:
        return 0.0, False

    close = df_5m["close"]
    high  = df_5m["high"]
    low   = df_5m["low"]

    # ATR compression
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr_5  = float(tr.iloc[-5:].mean())
    atr_20 = float(tr.iloc[-20:].mean())
    atr_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0

    # Bollinger Band width
    bb_mean = close.rolling(20).mean()
    bb_std  = close.rolling(20).std()
    bb_width_now  = float(bb_std.iloc[-1] / bb_mean.iloc[-1] * 100) if float(bb_mean.iloc[-1]) > 0 else 0
    bb_width_prev = float(bb_std.iloc[-10] / bb_mean.iloc[-10] * 100) if float(bb_mean.iloc[-10]) > 0 else 0

    bb_squeeze = bb_width_now < bb_width_prev * 0.7   # רוחב BB ירד ב-30%+
    atr_squeeze = atr_ratio < 0.7

    is_squeezed = atr_squeeze or bb_squeeze

    score = 0.0
    if atr_ratio < 0.4:   score = 15.0
    elif atr_ratio < 0.6: score = 12.0
    elif atr_ratio < 0.7: score = 8.0
    elif atr_ratio < 0.85: score = 4.0

    if bb_squeeze:         score = min(15.0, score + 5)

    return round(score, 1), is_squeezed


# ─── D. Multi-Timeframe Alignment ────────────────────────────────────────────
# מטבע שמיושר ב-15m + 1h + 4h יכול לתת מהלכים גדולים בהרבה

def _mtf_alignment(
    mom_15m: float,
    mom_1h:  float,
    mom_4h:  float,   # 4 נרות של 1h
    ema20_5m: float,
    ema50_5m: float,
    price:    float,
) -> float:
    """
    כל הטיימפריימים מיושרים כלפי מעלה = עד 15 נק'.
    """
    score = 0.0

    # מומנטום חיובי בכל הטיימפריימים
    if mom_15m > 0: score += 3
    if mom_1h  > 0: score += 5
    if mom_4h  > 0: score += 5

    # מחיר מעל EMA20 ו-EMA50
    if price > ema20_5m > 0: score += 1
    if price > ema50_5m > 0: score += 1

    # bonus: כל הטיימפריימים חיוביים + מחיר מעל EMAs
    if mom_15m > 0 and mom_1h > 0 and mom_4h > 0:
        score += 3

    return min(15.0, round(score, 1))


# ─── E. Early RS Signal ───────────────────────────────────────────────────────
# מתחיל להכות BTC עוד לפני שפורץ

def _early_rs(rs_1h: float, rs_4h: float, mom_1h: float) -> float:
    """
    RS חיובי קטן + מחיר עדיין לא זז הרבה = Early signal = עד 15 נק'.
    """
    score = 0.0

    # RS חיובי אבל מחיר לא פרץ עדיין (mom_1h < 5%)
    if rs_1h > 0 and mom_1h < 5.0:
        score += min(10.0, rs_1h * 2)

    if rs_4h > 0:
        score += min(5.0, rs_4h)

    return min(15.0, round(score, 1))


# ─── F. Funding Setup ─────────────────────────────────────────────────────────
# Funding שלילי = שורטים כבדים = squeeze potential

def _funding_setup(funding_rate: float) -> float:
    """
    Funding שלילי חזק = שורטים יצטרכו לכסות = מהלך גדול אפשרי.
    מחזיר score_0_10.
    """
    if funding_rate < -0.03:    return 10.0   # שורטים קיצוניים
    if funding_rate < -0.01:    return 7.0
    if funding_rate < 0:        return 4.0
    if 0 < funding_rate < 0.02: return 3.0    # נורמלי-בריא
    return 0.0


# ─── Runner Mode ──────────────────────────────────────────────────────────────

def get_runner_exits(entry: float, atr: float) -> dict:
    """
    לא למכור ב-TP1 קטן. להישאר בפוזיציה למהלך גדול.

    TP1 = להחזיר סיכון (קטן — סגור חצי)
    TP2 = יעד ביניים
    TP3 = trailing stop עם EMA
    """
    if entry <= 0 or atr <= 0:
        return {}

    atr_pct = atr / entry

    return {
        "tp1":          round(entry * (1 + atr_pct * 2), 8),     # 2 ATR
        "tp2":          round(entry * (1 + atr_pct * 5), 8),     # 5 ATR
        "tp3_target":   round(entry * 1.30, 8),                   # +30%
        "trailing_pct": round(atr_pct * 3 * 100, 2),             # trail 3 ATR
        "sl":           round(entry * (1 - atr_pct * 1.5), 8),   # 1.5 ATR
    }


# ─── Main Entry ───────────────────────────────────────────────────────────────

def calc_pre_breakout_score(
    df_5m:          pd.DataFrame,
    df_1h:          pd.DataFrame,
    oi_change_pct:  float = 0.0,
    funding_rate:   float = 0.0,
    rs_1h:          float = 0.0,
    rs_4h:          float = 0.0,
    mom_15m:        float = 0.0,
    mom_1h:         float = 0.0,
    ema20:          float = 0.0,
    ema50:          float = 0.0,
    price:          float = 0.0,
) -> dict:
    """
    מחשב Pre-Breakout Score 0–100.

    Returns
    -------
    {
        "pre_score":     float,
        "phase":         str,
        "phase_label":   str,
        "is_squeezed":   bool,
        "components": {...}
    }
    """
    # 4h momentum מנרות 1h
    mom_4h = 0.0
    if df_1h is not None and len(df_1h) >= 5:
        c = df_1h["close"]
        mom_4h = round((float(c.iloc[-1]) - float(c.iloc[-5])) / float(c.iloc[-5]) * 100, 2)

    # price change 1h
    price_1h = 0.0
    if df_1h is not None and len(df_1h) >= 2:
        c = df_1h["close"]
        price_1h = round((float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100, 2)

    oi_s   = _oi_accumulation(oi_change_pct, price_1h)
    cvd_s  = _cvd_divergence(df_5m)
    cmp_s, squeezed = _compression(df_5m)
    mtf_s  = _mtf_alignment(mom_15m, mom_1h, mom_4h, ema20, ema50, price)
    rs_s   = _early_rs(rs_1h, rs_4h, mom_1h)
    fund_s = _funding_setup(funding_rate)

    total  = oi_s + cvd_s + cmp_s + mtf_s + rs_s + fund_s
    total  = round(min(100.0, total), 1)

    phase, phase_label = get_phase(total)

    return {
        "pre_score":   total,
        "phase":       phase,
        "phase_label": phase_label,
        "is_squeezed": squeezed,
        "mom_4h":      mom_4h,
        "components": {
            "oi_accumulation": oi_s,
            "cvd_divergence":  cvd_s,
            "compression":     cmp_s,
            "mtf_alignment":   mtf_s,
            "early_rs":        rs_s,
            "funding_setup":   fund_s,
        },
    }
