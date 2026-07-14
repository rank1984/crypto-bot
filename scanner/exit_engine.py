"""
CRYPTO-BOT Elite — Smart Exit Engine v2.0

"הכסף הגדול מגיע מהיכולת להחזיק מנצחים, לא רק למצוא אותם."

Exit Score 0–100:
    CVD התהפך            +20  — קונים הפכו למוכרים
    OI יורד בחדות        +20  — כסף יוצא מהשוק
    RS מול BTC נשבר      +15  — המטבע נחלש ביחס
    EMA20 1H נשבר        +25  — הכי חשוב — שבירת מבנה
    Volume Exhaustion    +10  — נפח מתייבש בשיא
    Whale Distribution   +10  — לווייתנים מוכרים

פלט:
    HOLD  (0–35)  — המהלך ממשיך, תשאר
    TRIM  (36–60) — שקול למכור חלק
    EXIT  (61+)   — צא מהפוזיציה
"""
import pandas as pd
import numpy as np
from utils.logger import get_logger
from typing import Optional, Tuple

log = get_logger(__name__)


# ─── A. CVD Reversal ──────────────────────────────────────────────────────────

def _cvd_reversal(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if df_5m is None or len(df_5m) < 15:
        return False, 0.0

    close = df_5m["close"]
    high  = df_5m["high"]
    low   = df_5m["low"]
    vol   = df_5m["volume"]

    hl      = (high - low).replace(0, np.nan)
    buy_vol = ((close - low) / hl * vol).fillna(vol * 0.5)
    delta   = (buy_vol - (vol - buy_vol))

    recent_cvd = float(delta.iloc[-5:].sum())
    prior_cvd  = float(delta.iloc[-10:-5].sum())

    reversed_ = prior_cvd > 0 and recent_cvd < 0
    score     = 20.0 if reversed_ else max(0.0, (prior_cvd - recent_cvd) / (abs(prior_cvd) + 1e-10) * 10)

    return reversed_, round(min(20.0, score), 1)


# ─── B. OI Drop ───────────────────────────────────────────────────────────────

def _oi_dropping(oi_change_pct: float) -> Tuple[bool, float]:
    if oi_change_pct < -5.0:
        return True, 20.0
    if oi_change_pct < -2.0:
        return True, 12.0
    if oi_change_pct < 0:
        return False, 5.0
    return False, 0.0


# ─── C. RS Breakdown ──────────────────────────────────────────────────────────

def _rs_breakdown(rs_1h: float, rs_4h: float) -> Tuple[bool, float]:
    both_negative = rs_1h < 0 and rs_4h < 0
    one_negative  = rs_1h < -1.0 or rs_4h < -1.0

    if both_negative:
        score = min(15.0, abs(rs_1h + rs_4h) * 2)
        return True, round(score, 1)
    if one_negative:
        return False, 5.0
    return False, 0.0


# ─── D. EMA20 1H Break ────────────────────────────────────────────────────────

def _ema20_break(df_1h: pd.DataFrame) -> Tuple[bool, float]:
    if df_1h is None or len(df_1h) < 22:
        return False, 0.0

    close = df_1h["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()

    last_close  = float(close.iloc[-1])
    last_ema    = float(ema20.iloc[-1])
    prev_close  = float(close.iloc[-2])
    prev_ema    = float(ema20.iloc[-2])

    broke_now  = last_close < last_ema
    was_above  = prev_close > prev_ema

    if broke_now and was_above:   # פריצה ראשונה
        return True, 25.0
    if broke_now:                 # כבר מתחת
        gap_pct = (last_ema - last_close) / last_ema * 100
        return True, min(25.0, 15 + gap_pct * 2)

    return False, 0.0


# ─── E. Volume Exhaustion ─────────────────────────────────────────────────────

def _volume_exhaustion(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if df_5m is None or len(df_5m) < 20:
        return False, 0.0

    vol         = df_5m["volume"]
    peak_vol    = float(vol.iloc[-20:-5].max())
    recent_avg  = float(vol.iloc[-5:].mean())

    if peak_vol == 0:
        return False, 0.0

    ratio = recent_avg / peak_vol

    if ratio < 0.3:    return True,  10.0
    if ratio < 0.5:    return True,   6.0
    if ratio < 0.7:    return False,  2.0
    return False, 0.0


# ─── F. Whale Distribution ────────────────────────────────────────────────────

def _whale_distribution(df_5m: pd.DataFrame) -> Tuple[bool, float]:
    if df_5m is None or len(df_5m) < 10:
        return False, 0.0

    recent   = df_5m.iloc[-5:]
    avg_vol  = float(df_5m["volume"].iloc[-20:-5].mean())

    distribution_score = 0.0
    for _, row in recent.iterrows():
        is_red     = float(row["close"]) < float(row["open"])
        high_vol   = float(row["volume"]) > avg_vol * 2.5
        if is_red and high_vol:
            distribution_score += 5.0

    whale_dist = distribution_score >= 10.0
    return whale_dist, min(10.0, distribution_score)


# ─── G. Trailing Stop (ATR-based) ─────────────────────────────────────────────

def update_trailing_stop_atr(df_5m: pd.DataFrame, current_stop: float, atr_mult: float = 2.0) -> Optional[float]:
    """
    מעדכן Trailing Stop דינמי לפי ATR.
    מחזיר סטופ חדש (אם השתפר) או None.
    """
    if df_5m is None or len(df_5m) < 15:
        return None

    # חישוב ATR פשוט (14 נרות)
    high = df_5m["high"].iloc[-14:]
    low  = df_5m["low"].iloc[-14:]
    close_prev = df_5m["close"].shift(1).iloc[-14:]
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
    atr = float(tr.mean())

    # Highest High
    highest = float(df_5m["high"].iloc[-10:].max())
    new_stop = highest - atr * atr_mult

    if new_stop > current_stop:
        return new_stop
    return None


# ─── Exit Decision ────────────────────────────────────────────────────────────

def _exit_decision(score: float) -> Tuple[str, str, str]:
    """מחזיר (signal, emoji, description)"""
    if score >= 61:
        return "EXIT",  "🔴", "צא מהפוזיציה"
    if score >= 36:
        return "TRIM",  "🟡", "שקול למכור חלק"
    return "HOLD", "🟢", "המהלך ממשיך — תשאר"


# ─── Main Entry ───────────────────────────────────────────────────────────────

def calc_exit_score(
    df_5m:          pd.DataFrame,
    df_1h:          pd.DataFrame,
    rs_1h:          float = 0.0,
    rs_4h:          float = 0.0,
    oi_change_pct:  float = 0.0,
    current_gain_pct: float = 0.0,   # % רווח נוכחי מהכניסה
    flow_score:     float = 50.0,    # current flow score
    market_health:  float = 70.0,    # Market Health 0-100
) -> dict:
    """
    מחשב Exit Score ומחזיר החלטת יציאה.
    """
    cvd_rev,   cvd_s  = _cvd_reversal(df_5m)
    oi_drop,   oi_s   = _oi_dropping(oi_change_pct)
    rs_break,  rs_s   = _rs_breakdown(rs_1h, rs_4h)
    ema_break, ema_s  = _ema20_break(df_1h)
    vol_exh,   vol_s  = _volume_exhaustion(df_5m)
    whale_dist, whl_s = _whale_distribution(df_5m)

    total = cvd_s + oi_s + rs_s + ema_s + vol_s + whl_s

    # Flow weak → תוספת
    if flow_score < 40:
        total += 10
    if flow_score < 25:
        total += 15

    # Market Health רע → תוספת
    if market_health < 50:
        total += 10
    if market_health < 30:
        total += 20  # Emergency Exit

    # רווח גדול → החמרה
    if current_gain_pct >= 30 and total >= 25:
        total += 10
    if current_gain_pct >= 50 and total >= 20:
        total += 15

    total = round(min(100.0, total), 1)

    signal, emoji, desc = _exit_decision(total)
    confidence = round(min(100.0, total * 1.2), 1)

    reasons = []
    if cvd_rev:   reasons.append("CVD התהפך — מוכרים השתלטו")
    if oi_drop:   reasons.append("OI יורד — כסף יוצא")
    if rs_break:  reasons.append("RS מול BTC נשבר")
    if ema_break: reasons.append("EMA20 1H נשבר — שינוי מבנה")
    if vol_exh:   reasons.append("Volume מתייבש")
    if whale_dist: reasons.append("Whale Distribution מזוהה")
    if flow_score < 40: reasons.append("Flow נחלש")
    if market_health < 50: reasons.append("Market Health ירוד")

    return {
        "exit_signal":   signal,
        "exit_emoji":    emoji,
        "exit_desc":     desc,
        "exit_score":    total,
        "confidence":    confidence,
        "reasons":       reasons,
        "components": {
            "cvd_reversal":   cvd_s,
            "oi_drop":        oi_s,
            "rs_breakdown":   rs_s,
            "ema20_break":    ema_s,
            "vol_exhaustion": vol_s,
            "whale_dist":     whl_s,
        },
    }
