"""
CRYPTO-BOT Elite — Ranking Engine (V9)
מקבל רשימת מטבעות, מריץ את כל המחשובים, ומחזיר Top N.
"""
import pandas as pd
from typing import Optional

from scanner.market_data import get_all_timeframes
from scanner.momentum   import calc_momentum
from scanner.volume     import calc_volume
from scanner.indicators import calc_indicators
from scanner.scoring    import (
    freshness_score, momentum_score, breakout_score, final_score,
)
from scanner.relative_strength import calc_relative_strength, set_btc_reference
from utils.config import TOP_N
from utils.logger import get_logger

log = get_logger(__name__)


def _recent_high_stats(df_5m: pd.DataFrame,
                       lookback: int = 20) -> tuple[float, float, float]:
    """
    Returns (high_price, high_age_candles, pullback_pct)
    from the last `lookback` 5m candles.
    """
    if df_5m is None or len(df_5m) < 2:
        return 0.0, 0.0, 0.0

    window = df_5m["high"].iloc[-lookback:]
    idx_of_high = window.idxmax()
    high_price  = float(window.max())
    last_price  = float(df_5m["close"].iloc[-1])

    # age in candles from end of DataFrame
    high_age = len(df_5m) - 1 - df_5m.index.get_loc(idx_of_high)

    pullback = (high_price - last_price) / high_price * 100 if high_price > 0 else 0.0
    return high_price, float(high_age), round(pullback, 3)


def scan_coin(symbol: str) -> Optional[dict]:
    """
    Full pipeline for one coin.
    Returns a result dict or None if data is unavailable.
    """
    dfs = get_all_timeframes(symbol)
    if not all(tf in dfs for tf in ["1min", "5min", "15min", "1hour"]):
        log.debug(f"{symbol}: missing timeframes, skipping")
        return None

    df_1m, df_5m, df_15m, df_1h = dfs["1min"], dfs["5min"], dfs["15min"], dfs["1hour"]

    # ── Basic data ────────────────────────────────────────────────────────────
    last_price = float(df_5m["close"].iloc[-1])

    mom   = calc_momentum(df_1m, df_5m, df_15m, df_1h)
    vol   = calc_volume(df_5m)
    ind   = calc_indicators(df_5m, df_1h)

    # ── RVOL minimum filter — מסלק מטבעות עם נפח חלש ────────────────────────
    if vol["rvol"] < 1.5:
        log.debug(f"{symbol}: RVOL {vol['rvol']:.2f} < 1.5 — skipped")
        return None

    rs    = calc_relative_strength(df_1h)

    high_price, high_age, pullback = _recent_high_stats(df_5m)
    proximity = (high_price - last_price) / high_price * 100 if high_price > 0 else 0.0

    # ── Scores ────────────────────────────────────────────────────────────────
    fs = freshness_score(
        high_age_candles=high_age,
        pullback_pct=pullback,
        momentum_5m=mom["momentum_5m"],
        vwap_dist=ind["vwap_dist"],
        vol_accel=vol["vol_accel"],
    )
    ms = momentum_score(
        rvol=vol["rvol"],
        dollar_volume=vol["dollar_volume"],
        rsi_14=ind["rsi_14"],
        momentum_5m=mom["momentum_5m"],
        momentum_15m=mom["momentum_15m"],
    )
    bs = breakout_score(
        proximity_to_high_pct=proximity,
        vol_accel=vol["vol_accel"],
        vwap_dist=ind["vwap_dist"],
        momentum_5m=mom["momentum_5m"],
        momentum_15m=mom["momentum_15m"],
        atr_14=ind["atr_14"],
        last_price=last_price,
    )
    score = final_score(
        freshness=fs, momentum=ms, breakout=bs,
        rvol=vol["rvol"],
        vol_accel=vol["vol_accel"],
        vwap_dist=ind["vwap_dist"],
    )

    # RS bonus: מטבע חזק מ-BTC מקבל עד +8 נקודות
    rs_bonus = 0.0
    if rs["rs_1h"] > 1.0: rs_bonus += 4
    if rs["rs_4h"] > 2.0: rs_bonus += 4
    score = round(min(score + rs_bonus, 100.0), 1)

    return {
        "symbol":       symbol,
        "price":        last_price,
        # momentum
        "momentum_3m":  mom["momentum_3m"],
        "momentum_5m":  mom["momentum_5m"],
        "momentum_15m": mom["momentum_15m"],
        "momentum_1h":  mom["momentum_1h"],
        # volume
        "rvol":         vol["rvol"],
        "vol_accel":    vol["vol_accel"],
        "dollar_volume": vol["dollar_volume"],
        # indicators
        "vwap":         ind["vwap"],
        "vwap_dist":    ind["vwap_dist"],
        "ema20":        ind["ema20"],
        "ema50":        ind["ema50"],
        "rsi_14":       ind["rsi_14"],
        "atr_14":       ind["atr_14"],
        # relative strength
        "rs_1h":        rs["rs_1h"],
        "rs_4h":        rs["rs_4h"],
        "rs_score":     rs["rs_score"],
        # scores
        "freshness_score": fs,
        "momentum_score":  ms,
        "breakout_score":  bs,
        "final_score":     score,
    }


def rank_universe(symbols: list[str]) -> list[dict]:
    """
    Scans all symbols, scores them, returns Top N sorted by final_score.
    """
    # ── טען BTC reference פעם אחת לפני הסריקה ────────────────────────────────
    log.info("Loading BTC reference for relative strength...")
    btc_dfs = get_all_timeframes("BTCUSDT")
    if "1hour" in btc_dfs:
        set_btc_reference(btc_dfs["1hour"])

    results = []
    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i % 50 == 0:
            log.info(f"Scanning {i}/{total}...")
        try:
            r = scan_coin(sym)
            if r:
                results.append(r)
        except Exception as e:
            log.warning(f"{sym}: unexpected error — {e}")

    results.sort(key=lambda x: x["final_score"], reverse=True)
    top = results[:TOP_N]

    log.info(f"Ranking complete: {len(results)} coins scored, top {TOP_N} selected")
    return top
