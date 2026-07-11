"""
CRYPTO-BOT Elite — Flow Engine

"כסף חכם מסתכל על זרימת כסף, לא על מחיר."

Flow Score 0–100 מבוסס על:
    A. OI Expansion     (20 נק') — כסף חדש נכנס
    B. CVD              (20 נק') — קונים תוקפים באגרסיביות
    C. Funding Rate     (10 נק') — מצב הפוזיציות
    D. RS vs BTC + ETH  (20 נק') — מוביל את השוק
    E. Volume Accel     (10 נק') — קצב ההאצה
    F. Compression      (10 נק') — שקט לפני סערה
    G. Whale Activity   (10 נק') — כסף גדול נכנס

מקור: KuCoin Futures API (חינמי, ללא הרשמה)
"""
import requests
import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

_BASE    = "https://api-futures.kucoin.com"
_SPOT    = "https://api.kucoin.com"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_TIMEOUT = 8


def _kucoin_fut_sym(symbol: str) -> str:
    """BTCUSDT → XBTUSDTM"""
    base = symbol.replace("USDT", "")
    if base == "BTC": base = "XBT"
    return f"{base}USDTM"


# ─── A. OI Expansion ──────────────────────────────────────────────────────────

def _oi_expansion(symbol: str, df_5m=None) -> tuple[float, float]:
    """
    מחזיר (oi_change_pct_1h, score_0_20).
    Fallback: proxy מ-volume אם KuCoin Futures לא זמין.
    """
    try:
        sym = _kucoin_fut_sym(symbol)
        r = requests.get(
            f"{_BASE}/api/v1/contract/stats",
            headers=_HEADERS,
            params={"symbol": sym},
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            oi_now = float(data.get("openInterestChange24h", 0) or 0)
            score  = min(20.0, max(0.0, oi_now * 2)) if oi_now > 0 else 0.0
            return round(oi_now, 2), round(score, 1)
    except Exception as e:
        log.debug(f"OI expansion failed {symbol}: {e}")

    # Fallback: proxy מ-volume acceleration
    if df_5m is not None and len(df_5m) >= 10:
        try:
            import numpy as np
            vol   = df_5m["volume"].values
            avg   = float(np.mean(vol[-10:-3]))
            last3 = float(np.mean(vol[-3:]))
            if avg > 0:
                ratio = (last3 - avg) / avg * 100
                proxy_score = min(10.0, max(0.0, ratio))   # מקסימום 10 (חצי מ-OI אמיתי)
                return round(ratio, 2), round(proxy_score, 1)
        except Exception:
            pass
    return 0.0, 0.0


# ─── B. CVD (Cumulative Volume Delta) ────────────────────────────────────────

def _cvd_score(df_5m: pd.DataFrame) -> tuple[float, float]:
    """
    מחשב CVD על נרות 5m.
    CVD = סכום (buy_vol - sell_vol) לכל נר.

    אומדן: נר ירוק = buy pressure, נר אדום = sell pressure.
    טכניקה פשוטה אבל יעילה בלי Level 2 data.

    מחזיר (cvd_trend_pct, score_0_20).
    """
    if df_5m is None or len(df_5m) < 10:
        return 0.0, 0.0

    close = df_5m["close"]
    open_ = df_5m["open"]
    vol   = df_5m["volume"]

    # Buy volume אומדן: אם נר ירוק → כל הנפח הוא buy, אם אדום → sell
    # שיטה מדויקת יותר: (close-low)/(high-low) * volume
    high  = df_5m["high"]
    low   = df_5m["low"]
    hl    = (high - low).replace(0, np.nan)

    buy_vol  = ((close - low) / hl * vol).fillna(vol * 0.5)
    sell_vol = vol - buy_vol
    delta    = buy_vol - sell_vol

    cvd = delta.cumsum()

    # טרנד: האם CVD עולה ב-10 הנרות האחרונים?
    cvd_recent = cvd.iloc[-10:]
    slope = float(np.polyfit(range(10), cvd_recent.values, 1)[0])
    cvd_trend_pct = slope / (abs(float(cvd_recent.mean())) + 1e-10) * 100

    score = min(20.0, max(0.0, cvd_trend_pct * 2)) if cvd_trend_pct > 0 else 0.0
    return round(cvd_trend_pct, 2), round(score, 1)


# ─── C. Funding Rate ──────────────────────────────────────────────────────────

def _funding_score(symbol: str) -> tuple[float, float]:
    """
    Funding חיובי מתון = לונגים משלמים = שוק בריא.
    Funding קיצוני = penalty.
    Funding שלילי = שורטים כבדים = potential squeeze.

    מחזיר (funding_rate_pct, score_0_10).
    """
    try:
        sym = _kucoin_fut_sym(symbol)
        r = requests.get(
            f"{_BASE}/api/v1/funding-rate/{sym}/current",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return 0.0, 5.0  # ניטרלי
        data  = r.json().get("data", {})
        rate  = float(data.get("value", 0) or 0) * 100  # המר ל-%

        if -0.005 < rate < 0.01:     # ניטרלי-בריא
            score = 8.0
        elif 0.01 <= rate < 0.03:    # חיובי מתון
            score = 10.0
        elif rate >= 0.03:           # קיצוני — penalty
            score = max(0.0, 10 - (rate - 0.03) * 200)
        elif rate < -0.01:           # שורטים כבדים → squeeze potential
            score = 9.0
        else:
            score = 5.0

        return round(rate, 5), round(score, 1)
    except Exception as e:
        log.debug(f"Funding failed {symbol}: {e}")
        return 0.0, 5.0


# ─── D. Relative Strength vs BTC + ETH ───────────────────────────────────────

def _rs_score(rs_btc_1h: float, rs_eth_1h: float) -> float:
    """
    מטבע שמכה גם BTC וגם ETH = score מלא 20.
    מחזיר score_0_20.
    """
    score = 0.0
    if rs_btc_1h > 0: score += 10
    if rs_btc_1h > 2: score += 3    # bonus לחוזק חריג
    if rs_eth_1h > 0: score += 7
    return min(20.0, score)


# ─── E. Volume Acceleration ───────────────────────────────────────────────────

def _vol_accel_score(df_5m: pd.DataFrame) -> tuple[float, float]:
    """
    volume_15m / volume_60m — לא רק RVOL, אלא קצב ההאצה.
    מחזיר (accel_ratio, score_0_10).
    """
    if df_5m is None or len(df_5m) < 15:
        return 1.0, 0.0

    vol_15m = float(df_5m["volume"].iloc[-3:].sum())    # 3 נרות × 5m = 15m
    vol_60m = float(df_5m["volume"].iloc[-12:].sum())   # 12 נרות × 5m = 60m

    if vol_60m == 0:
        return 1.0, 0.0

    # נורמל: vol_15m צפוי להיות ~25% מ-vol_60m (1/4 מהשעה)
    expected_15m = vol_60m * 0.25
    accel = vol_15m / expected_15m if expected_15m > 0 else 1.0

    # 1x = נורמלי, 2x = האצה, 3x+ = חריג
    score = min(10.0, (accel - 1.0) * 5) if accel > 1.0 else 0.0
    return round(accel, 2), round(score, 1)


# ─── F. Compression (ATR Squeeze) ────────────────────────────────────────────

def _compression_score(df_5m: pd.DataFrame) -> tuple[bool, float]:
    """
    ATR יורד = שקט לפני סערה.
    ATR_5 < ATR_20 = קומפרסיה אמיתית.
    מחזיר (is_compressed, score_0_10).
    """
    if df_5m is None or len(df_5m) < 25:
        return False, 0.0

    high  = df_5m["high"]
    low   = df_5m["low"]
    close = df_5m["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr_5  = float(tr.iloc[-5:].mean())
    atr_20 = float(tr.iloc[-20:].mean())

    if atr_20 == 0:
        return False, 0.0

    compression_ratio = atr_5 / atr_20
    is_compressed     = compression_ratio < 0.7   # ATR ירד ב-30%+

    score = 0.0
    if compression_ratio < 0.5:   score = 10.0   # קומפרסיה חזקה מאוד
    elif compression_ratio < 0.7: score = 7.0
    elif compression_ratio < 0.85: score = 3.0

    return is_compressed, round(score, 1)


# ─── G. Whale Activity ────────────────────────────────────────────────────────

def _whale_score(df_5m: pd.DataFrame) -> tuple[bool, float]:
    """
    עסקאות גדולות חריגות = whale activity.
    אומדן: כאשר dollar_volume של נר בודד >> ממוצע × 5.
    מחזיר (whale_detected, score_0_10).
    """
    if df_5m is None or len(df_5m) < 10:
        return False, 0.0

    dv     = df_5m["volume"] * df_5m["close"]
    avg_dv = float(dv.iloc[:-3].mean())
    max_dv = float(dv.iloc[-5:].max())

    if avg_dv == 0:
        return False, 0.0

    ratio = max_dv / avg_dv
    whale = ratio > 5.0

    score = min(10.0, (ratio - 1) * 2) if ratio > 3 else 0.0
    return whale, round(score, 1)


# ─── Main Entry ───────────────────────────────────────────────────────────────

def calc_flow_score(
    symbol:     str,
    df_5m:      pd.DataFrame,
    rs_btc_1h:  float = 0.0,
    rs_eth_1h:  float = 0.0,
) -> dict:
    """
    מחשב את ה-Flow Score המלא.

    Returns
    -------
    {
        "flow_score":        float,  # 0–100
        "oi_change":         float,
        "cvd_trend":         float,
        "funding_rate":      float,
        "vol_accel":         float,
        "is_compressed":     bool,
        "whale_detected":    bool,
        "components": {
            "oi":          float,
            "cvd":         float,
            "funding":     float,
            "rs":          float,
            "vol_accel":   float,
            "compression": float,
            "whale":       float,
        }
    }
    """
    oi_chg,  oi_s   = _oi_expansion(symbol, df_5m)
    cvd_t,   cvd_s  = _cvd_score(df_5m)
    fund_r,  fund_s = _funding_score(symbol)
    rs_s            = _rs_score(rs_btc_1h, rs_eth_1h)
    vol_a,   vol_s  = _vol_accel_score(df_5m)
    compressed, cmp_s = _compression_score(df_5m)
    whale,   whl_s  = _whale_score(df_5m)

    total = oi_s + cvd_s + fund_s + rs_s + vol_s + cmp_s + whl_s

    return {
        "flow_score":     round(total, 1),
        "oi_change":      oi_chg,
        "cvd_trend":      cvd_t,
        "funding_rate":   fund_r,
        "vol_accel":      vol_a,
        "is_compressed":  compressed,
        "whale_detected": whale,
        "components": {
            "oi":          oi_s,
            "cvd":         cvd_s,
            "funding":     fund_s,
            "rs":          rs_s,
            "vol_accel":   vol_s,
            "compression": cmp_s,
            "whale":       whl_s,
        },
    }
