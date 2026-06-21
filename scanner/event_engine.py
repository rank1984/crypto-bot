"""
CRYPTO-BOT Elite — Event Engine

מזהה Catalysts שמניעים מהלכים גדולים:
    OI Spike           — כסף גדול נכנס פתאום
    Funding Squeeze    — שורטים בלחץ → squeeze potential
    Liquidation Cluster — הצטברות של פוזיציות ממונפות
    Volume Anomaly     — נפח חריג לחלוטין
    Social Spike       — עלייה פתאומית בתשומת לב
    Whale Accumulation — קנייה גדולה בדיסקרטיות

מקורות חינמיים:
    KuCoin Futures API — OI, Funding, Liquidations
    CoinGecko          — Social/trend data
    חישוב מקומי        — Volume anomaly, Whale detection
"""
import requests
import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

_KUCOIN_FUT = "https://api-futures.kucoin.com"
_COINGECKO  = "https://api.coingecko.com/api/v3"
_HEADERS    = {"User-Agent": "crypto-bot/1.0"}
_TIMEOUT    = 8


def _kucoin_fut_sym(sym: str) -> str:
    base = sym.replace("USDT","")
    if base == "BTC": base = "XBT"
    return f"{base}USDTM"


# ─── A. OI Spike ──────────────────────────────────────────────────────────────

def _oi_spike(symbol: str) -> tuple[bool, float, str]:
    """
    OI קפץ בחדות בזמן קצר = כסף גדול נכנס פתאום.
    מחזיר (detected, magnitude, description).
    """
    try:
        r = requests.get(
            f"{_KUCOIN_FUT}/api/v1/contract/stats",
            headers=_HEADERS,
            params={"symbol": _kucoin_fut_sym(symbol)},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return False, 0.0, ""

        data   = r.json().get("data", {})
        oi_chg = float(data.get("openInterestChange24h", 0) or 0)

        if oi_chg > 20:
            return True, oi_chg, f"OI Spike: +{oi_chg:.0f}% ב-24h"
        if oi_chg > 10:
            return True, oi_chg, f"OI Surge: +{oi_chg:.0f}% ב-24h"
        return False, oi_chg, ""
    except Exception:
        return False, 0.0, ""


# ─── B. Funding Squeeze ───────────────────────────────────────────────────────

def _funding_squeeze(symbol: str) -> tuple[bool, float, str]:
    """
    Funding שלילי חזק = שורטים בלחץ → squeeze potential.
    """
    try:
        r = requests.get(
            f"{_KUCOIN_FUT}/api/v1/funding-rate/{_kucoin_fut_sym(symbol)}/current",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return False, 0.0, ""

        rate = float(r.json().get("data", {}).get("value", 0) or 0) * 100

        if rate < -0.05:
            return True, abs(rate), f"Funding Squeeze: {rate:.3f}% — שורטים בלחץ כבד"
        if rate < -0.02:
            return True, abs(rate), f"Negative Funding: {rate:.3f}% — squeeze potential"
        return False, abs(rate), ""
    except Exception:
        return False, 0.0, ""


# ─── C. Volume Anomaly ────────────────────────────────────────────────────────

def _volume_anomaly(df_5m: pd.DataFrame) -> tuple[bool, float, str]:
    """
    נפח חריג לחלוטין — פי 5+ מהממוצע ב-20 נרות.
    """
    if df_5m is None or len(df_5m) < 20:
        return False, 0.0, ""

    vol     = df_5m["volume"]
    avg_vol = float(vol.iloc[-20:-3].mean())
    max_recent = float(vol.iloc[-3:].max())

    if avg_vol == 0:
        return False, 0.0, ""

    ratio = max_recent / avg_vol

    if ratio > 10:
        return True, ratio, f"Volume Explosion: {ratio:.0f}x הממוצע"
    if ratio > 5:
        return True, ratio, f"Volume Anomaly: {ratio:.0f}x הממוצע"
    return False, ratio, ""


# ─── D. Liquidation Cluster ───────────────────────────────────────────────────

def _liquidation_cluster(symbol: str) -> tuple[bool, float, str]:
    """
    הצטברות של פוזיציות ממונפות ליד המחיר = potential big move.
    אומדן: Funding קיצוני + OI גבוה = לחץ רב.
    """
    try:
        r = requests.get(
            f"{_KUCOIN_FUT}/api/v1/contracts/{_kucoin_fut_sym(symbol)}",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return False, 0.0, ""

        data        = r.json().get("data", {})
        oi          = float(data.get("openInterest", 0) or 0)
        mark_price  = float(data.get("markPrice", 1) or 1)
        multiplier  = float(data.get("multiplier", 1) or 1)
        oi_usd      = oi * multiplier * mark_price

        # OI גבוה ביחס למחיר = לחץ גדול
        if oi_usd > 50_000_000:  # $50M+
            return True, oi_usd, f"OI גבוה: ${oi_usd/1e6:.0f}M — cluster אפשרי"
        return False, oi_usd, ""
    except Exception:
        return False, 0.0, ""


# ─── E. Whale Accumulation ────────────────────────────────────────────────────

def _whale_accumulation(df_5m: pd.DataFrame) -> tuple[bool, int, str]:
    """
    קנייה גדולה בדיסקרטיות: נרות ירוקים גדולים עם volume גבוה.
    """
    if df_5m is None or len(df_5m) < 15:
        return False, 0, ""

    recent   = df_5m.iloc[-10:]
    avg_vol  = float(df_5m["volume"].iloc[-20:-10].mean()) if len(df_5m) >= 20 else float(df_5m["volume"].mean())
    if avg_vol == 0:
        return False, 0, ""

    whale_candles = 0
    for _, row in recent.iterrows():
        is_green   = float(row["close"]) > float(row["open"])
        high_vol   = float(row["volume"]) > avg_vol * 3
        big_body   = abs(float(row["close"]) - float(row["open"])) > (float(row["high"]) - float(row["low"])) * 0.6
        if is_green and high_vol and big_body:
            whale_candles += 1

    if whale_candles >= 3:
        return True, whale_candles, f"Whale Accumulation: {whale_candles} נרות ירוקים גדולים"
    if whale_candles >= 2:
        return True, whale_candles, f"Whale Activity: {whale_candles} נרות חריגים"
    return False, whale_candles, ""


# ─── F. Social Spike (CoinGecko) ──────────────────────────────────────────────

_trending_cache: list = []
_trending_ts: float = 0

def _social_spike(symbol: str) -> tuple[bool, str]:
    """
    מטבע ב-trending של CoinGecko = עלייה בתשומת לב.
    Cache לדקה.
    """
    import time
    global _trending_cache, _trending_ts

    if time.time() - _trending_ts > 300:   # רענון כל 5 דקות
        try:
            r = requests.get(f"{_COINGECKO}/search/trending",
                             headers=_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 200:
                _trending_cache = [c["item"]["symbol"].upper() for c in r.json().get("coins",[])]
                _trending_ts = time.time()
        except Exception:
            pass

    base = symbol.replace("USDT","").upper()
    if base in _trending_cache:
        return True, f"Trending ב-CoinGecko #{_trending_cache.index(base)+1}"
    return False, ""


# ─── Main Entry ───────────────────────────────────────────────────────────────

def calc_event_score(
    symbol: str,
    df_5m:  pd.DataFrame,
) -> dict:
    """
    מחשב Event Score ומחזיר קטלוגי Catalysts.

    Returns
    -------
    {
        "event_score":  float,   # 0–100
        "catalysts":    [str],   # רשימת אירועים שזוהו
        "has_catalyst": bool,
        "components":   {...}
    }
    """
    oi_spike,   oi_mag,   oi_desc   = _oi_spike(symbol)
    fund_sq,    fund_mag, fund_desc = _funding_squeeze(symbol)
    vol_anom,   vol_mag,  vol_desc  = _volume_anomaly(df_5m)
    liq_clust,  liq_mag,  liq_desc  = _liquidation_cluster(symbol)
    whale_acc,  whl_cnt,  whl_desc  = _whale_accumulation(df_5m)
    social,                soc_desc  = _social_spike(symbol)

    # ציונים
    oi_s   = min(30.0, oi_mag * 1.2) if oi_spike else 0.0
    fund_s = min(25.0, fund_mag * 400) if fund_sq else 0.0
    vol_s  = min(20.0, (vol_mag - 5) * 3) if vol_anom else 0.0
    liq_s  = 15.0 if liq_clust else 0.0
    whl_s  = min(20.0, whl_cnt * 7) if whale_acc else 0.0
    soc_s  = 10.0 if social else 0.0

    total = round(min(100.0, oi_s + fund_s + vol_s + liq_s + whl_s + soc_s), 1)

    catalysts = []
    for detected, desc in [
        (oi_spike, oi_desc), (fund_sq, fund_desc), (vol_anom, vol_desc),
        (liq_clust, liq_desc), (whale_acc, whl_desc), (social, soc_desc),
    ]:
        if detected and desc:
            catalysts.append(desc)

    return {
        "event_score":  total,
        "catalysts":    catalysts,
        "has_catalyst": len(catalysts) > 0,
        "components": {
            "oi_spike":   oi_s,
            "funding":    fund_s,
            "volume":     vol_s,
            "liquidity":  liq_s,
            "whale":      whl_s,
            "social":     soc_s,
        },
    }
