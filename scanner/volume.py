"""
CRYPTO-BOT Elite — Volume Engine (V2)
השדרוג הכי חשוב: RVOL, Volume Acceleration, Dollar Volume.

RVOL  = current 5m volume / avg 5m volume (last 20 candles)
vol_accel = last_5m_volume / prev_5m_volume
dollar_volume = close × volume of last 5m candle
"""
import pandas as pd

from utils.logger import get_logger

log = get_logger(__name__)

_RVOL_WINDOW     = 20   # candles for average (baseline)
_RVOL_SKIP_LAST  = 1    # skip the in-progress candle when computing avg


def calc_volume(df_5m: pd.DataFrame) -> dict[str, float]:
    """
    Parameters
    ----------
    df_5m : 5m candle DataFrame from market_data.get_candles()

    Returns
    -------
    {
        'rvol':          float,  # relative volume vs rolling avg
        'vol_accel':     float,  # last 5m vol / prev 5m vol
        'dollar_volume': float,  # last 5m close × volume (USD)
    }
    """
    result = {
        "rvol":          1.0,
        "vol_accel":     1.0,
        "dollar_volume": 0.0,
    }

    if df_5m is None or len(df_5m) < _RVOL_WINDOW + 2:
        log.debug("Not enough 5m candles for volume calc")
        return result

    vol = df_5m["volume"]

    # Dollar volume — last completed candle
    last_close  = float(df_5m["close"].iloc[-1])
    last_vol    = float(vol.iloc[-1])
    result["dollar_volume"] = round(last_close * last_vol, 2)

    # Volume Acceleration — last vs prev 5m candle
    prev_vol = float(vol.iloc[-2])
    if prev_vol > 0:
        result["vol_accel"] = round(last_vol / prev_vol, 3)

    # RVOL — last candle vs rolling mean of prior 20 candles
    # (exclude the last candle itself from the baseline)
    baseline_vols = vol.iloc[-(1 + _RVOL_WINDOW):-1]
    avg_vol = float(baseline_vols.mean())
    if avg_vol > 0:
        result["rvol"] = round(last_vol / avg_vol, 3)

    return result
