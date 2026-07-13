"""
CRYPTO-BOT Elite — Entry Engine v1

מפסיק "לדרג מטבעות" ומתחיל להגיד:
    BUY  — עם מחיר כניסה, SL, TP
    WAIT — setup קיים אבל טריגר עוד לא הופעל
    NO   — אין setup או שוק לא מאפשר
"""
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import pandas as pd
from utils.logger import get_logger
from tools.shadow_mode import record_trade

log = get_logger(__name__)

# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class EntrySignal:
    decision:   str        # "BUY" / "WAIT" / "NO"
    setup_type: str        # "BREAKOUT" / "VWAP_RECLAIM" / "DIP_BUY" / ""
    entry:      float      # מחיר כניסה מדויק
    sl:         float      # Stop Loss
    tp1:        float      # Take Profit 1
    tp2:        float      # Take Profit 2
    rr:         float      # Risk:Reward ratio
    reason:     str        # הסבר קצר

# ─── 1. Market Filter ─────────────────────────────────────────────────────────

def market_allows_trade(
    btc_mom_1h:  float,
    btc_mom_5m:  float,
    rs_1h:       float,
) -> tuple[bool, str]:
    if btc_mom_5m < -1.5:
        return False, f"BTC dumping {btc_mom_5m:.1f}% in 5m"
    if btc_mom_1h < -2.0:
        return False, f"BTC 1h bearish {btc_mom_1h:.1f}%"
    if rs_1h < 0 and btc_mom_1h < 0:
        return False, f"Weak vs BTC ({rs_1h:.1f}%) + BTC negative"
    return True, ""

# ─── 2. Setup Engine ──────────────────────────────────────────────────────────

def _consolidation_range(df_5m: pd.DataFrame, lookback: int = 12) -> tuple[float, float]:
    window = df_5m.iloc[-lookback:]
    return float(window["low"].min()), float(window["high"].max())

def detect_setup(
    df_5m:    pd.DataFrame,
    vwap:     float,
    rsi:      float,
    rvol:     float,
    mom_5m:   float,
    mom_15m:  float,
    mom_1h:   float,
    ema20:    float,
) -> tuple[str, dict]:
    if df_5m is None or len(df_5m) < 15:
        return "", {}

    last    = df_5m.iloc[-1]
    prev    = df_5m.iloc[-2]
    price   = float(last["close"])
    vwap_dist_pct = (price - vwap) / vwap * 100 if vwap > 0 else 0

    if (0 <= vwap_dist_pct <= 3.0 and rvol >= 1.5 and 55 <= rsi <= 80):
        cons_low, cons_high = _consolidation_range(df_5m, lookback=12)
        cons_range_pct = (cons_high - cons_low) / cons_low * 100 if cons_low > 0 else 99
        if cons_range_pct < 4.0:
            return "BREAKOUT", {"cons_low": cons_low, "cons_high": cons_high, "vwap": vwap, "price": price}

    prev_price = float(prev["close"])
    was_below  = prev_price < vwap
    now_above  = price > vwap
    vol_rising = float(last["volume"]) > float(prev["volume"])

    if (was_below and now_above and vol_rising and 45 <= rsi <= 70):
        return "VWAP_RECLAIM", {"vwap": vwap, "price": price}

    all_aligned = mom_1h > 0 and mom_15m > 0
    near_vwap   = abs(vwap_dist_pct) <= 1.0
    near_ema20  = ema20 > 0 and abs(price - ema20) / ema20 * 100 <= 1.0
    green_candle = float(last["close"]) > float(last["open"])

    if all_aligned and (near_vwap or near_ema20) and green_candle:
        return "DIP_BUY", {"vwap": vwap, "ema20": ema20, "price": price}

    return "", {}

# ─── 3. Trigger Check ─────────────────────────────────────────────────────────

def check_trigger(
    setup_type: str,
    ctx:        dict,
    df_5m:      pd.DataFrame,
) -> tuple[bool, float]:
    if df_5m is None or len(df_5m) < 3:
        return False, 0.0

    last  = df_5m.iloc[-1]
    close = float(last["close"])
    high  = float(last["high"])
    low   = float(last["low"])
    vol   = float(last["volume"])
    avg_vol = float(df_5m["volume"].iloc[-20:-1].mean())

    if setup_type == "BREAKOUT":
        cons_high = ctx.get("cons_high", 0)
        if cons_high <= 0:
            return False, 0.0

        breakout = close > cons_high
        candle_range = high - low
        upper_wick   = high - close
        no_rejection = (upper_wick / candle_range < 0.5) if candle_range > 0 else True
        vol_surge = vol > avg_vol * 1.2

        if breakout and no_rejection and vol_surge:
            entry = round(cons_high * 1.001, 8)
            return True, entry
        
        # תיקון: פריצה כמעט מושלמת - תן BUY
        if breakout and no_rejection:
            entry = round(cons_high * 1.001, 8)
            return True, entry

    elif setup_type == "VWAP_RECLAIM":
        vwap = ctx.get("vwap", 0)
        # תיקון: VWAP reclaim - הסר דרישת ווליום
        if close > vwap:
            return True, close

    elif setup_type == "DIP_BUY":
        green = close > float(last["open"])
        if green:
            return True, close

    return False, 0.0

# ─── 4. Risk Manager ──────────────────────────────────────────────────────────

def calc_risk(
    setup_type:  str,
    entry:       float,
    ctx:         dict,
    df_5m:       pd.DataFrame,
) -> tuple[float, float, float]:
    if entry <= 0:
        return 0.0, 0.0, 0.0

    if setup_type == "BREAKOUT":
        cons_high = ctx.get("cons_high", entry)
        sl  = round(cons_high * 0.99, 8)
        tp1 = round(entry * 1.04, 8)
        tp2 = round(entry * 1.10, 8)

    elif setup_type == "VWAP_RECLAIM":
        vwap = ctx.get("vwap", entry * 0.99)
        sl   = round(vwap * 0.99, 8)
        tp1  = round(entry * 1.035, 8)
        tp2  = round(entry * 1.08, 8)

    elif setup_type == "DIP_BUY":
        swing_low = float(df_5m["low"].iloc[-10:].min()) if df_5m is not None else entry * 0.98
        sl  = round(swing_low * 0.995, 8)
        tp1 = round(entry * 1.05, 8)
        tp2 = round(entry * 1.15, 8)

    else:
        sl  = round(entry * 0.98, 8)
        tp1 = round(entry * 1.04, 8)
        tp2 = round(entry * 1.10, 8)

    return sl, tp1, tp2

# ─── Main Logic ───────────────────────────────────────────────────────────────

def _run_core_logic(
    coin:        dict,
    df_5m:       pd.DataFrame,
    btc_mom_1h:  float = 0.0,
    btc_mom_5m:  float = 0.0,
) -> EntrySignal:
    no_trade = EntrySignal("NO", "", 0, 0, 0, 0, 0, "")

    allowed, reason = market_allows_trade(btc_mom_1h=btc_mom_1h, btc_mom_5m=btc_mom_5m, rs_1h=coin.get("rs_1h", 0))
    if not allowed:
        no_trade.reason = f"Market filter: {reason}"
        return no_trade

    setup_type, ctx = detect_setup(df_5m=df_5m, vwap=coin.get("vwap", 0), rsi=coin.get("rsi_14", 50), rvol=coin.get("rvol", 1), mom_5m=coin.get("momentum_5m", 0), mom_15m=coin.get("momentum_15m", 0), mom_1h=coin.get("momentum_1h", 0), ema20=coin.get("ema20", 0))
    if not setup_type:
        no_trade.reason = "No valid setup"
        return no_trade

    triggered, entry_price = check_trigger(setup_type, ctx, df_5m)
    if not triggered:
        return EntrySignal(decision="WAIT", setup_type=setup_type, entry=0, sl=0, tp1=0, tp2=0, rr=0, reason=f"{setup_type} setup — waiting for trigger")

    sl, tp1, tp2 = calc_risk(setup_type, entry_price, ctx, df_5m)
    risk   = entry_price - sl
    reward = tp1 - entry_price
    rr     = round(reward / risk, 2) if risk > 0 else 0

    if rr < 1.5:
        no_trade.reason = f"R:R too low ({rr})"
        return no_trade

    return EntrySignal(decision="BUY", setup_type=setup_type, entry=entry_price, sl=sl, tp1=tp1, tp2=tp2, rr=rr, reason=f"{setup_type} trigger confirmed")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def evaluate_entry(
    coin:        dict,
    df_5m:       pd.DataFrame,
    btc_mom_1h:  float = 0.0,
    btc_mom_5m:  float = 0.0,
) -> EntrySignal:
    
    result = _run_core_logic(coin, df_5m, btc_mom_1h, btc_mom_5m)
    
    log.info(
        f"{coin.get('symbol', 'UNK')} | "
        f"flow={coin.get('flow_score', 0):.1f} | "
        f"pre={coin.get('pre_score', 0):.1f} | "
        f"decision={result.decision} | "
        f"setup={result.setup_type} | "
        f"reason='{result.reason}'"
    )
    
    # שימוש ב-Shadow Tracker החדש ששומר את כל המשתנים למסד הנתונים
    record_trade(coin, result)
    
    return result
