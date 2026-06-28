"""
CRYPTO-BOT Elite — Volume Engine (V3)
RVOL, Volume Acceleration, Dollar Volume, Volume Explosion.

RVOL  = current 5m volume / avg 5m volume (last 20 candles)
vol_accel = last_5m_volume / prev_5m_volume
vol_explosion = האם ה-3 נרות האחרונים כולם מעל 3x הממוצע (בנייה של נפח)
"""
import pandas as pd
import numpy as np

from utils.logger import get_logger

log = get_logger(__name__)

_RVOL_WINDOW     = 20
_RVOL_SKIP_LAST  = 1


def calc_volume(df_5m: pd.DataFrame) -> dict[str, float]:
    result = {
        "rvol":            1.0,
        "vol_accel":       1.0,
        "dollar_volume":   0.0,
        "vol_explosion":   False,   # פיצוץ נפח: 3 נרות רצופים מעל 3x
        "vol_surge_score": 0.0,     # 0-100: עוצמת פיצוץ הנפח
    }

    if df_5m is None or len(df_5m) < _RVOL_WINDOW + 2:
        return result

    vol = df_5m["volume"]

    last_close = float(df_5m["close"].iloc[-1])
    last_vol   = float(vol.iloc[-1])
    result["dollar_volume"] = round(last_close * last_vol, 2)

    prev_vol = float(vol.iloc[-2])
    if prev_vol > 0:
        result["vol_accel"] = round(min(last_vol / prev_vol, 20.0), 3)

    baseline = vol.iloc[-(1 + _RVOL_WINDOW):-1]
    avg_vol  = float(baseline.mean())
    if avg_vol > 0:
        result["rvol"] = round(last_vol / avg_vol, 3)

    # Volume Explosion: האם נבנה נפח בנרות האחרונים?
    if avg_vol > 0 and len(vol) >= 5:
        recent_3 = [float(vol.iloc[-i]) / avg_vol for i in range(1, 4)]
        # כל 3 נרות מעל 2x — נפח בנייה
        if all(r >= 2.0 for r in recent_3):
            result["vol_explosion"] = True
        # surge score: ממוצע ה-3 נרות מחולק לציון
        avg_surge = np.mean(recent_3)
        result["vol_surge_score"] = round(min(100.0, avg_surge * 20), 1)

    return result
