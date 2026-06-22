"""
CRYPTO-BOT Elite — Ranking Engine
מריץ pipeline מלא על כל מטבע ומחזיר Top N.
"""
import pandas as pd
from typing import Optional

from scanner.market_data       import get_all_timeframes
from scanner.momentum          import calc_momentum
from scanner.volume            import calc_volume
from scanner.indicators        import calc_indicators
from scanner.scoring           import (
    freshness_score, momentum_score, breakout_score, final_score,
    passes_hard_filters, apply_trader_overrides,
)
from scanner.relative_strength import calc_relative_strength, set_btc_reference
from scanner.sympathy          import find_leaders, find_sympathy_plays, sympathy_bonus
from scanner.flow_engine       import calc_flow_score
from scanner.pre_breakout      import calc_pre_breakout_score
from scanner.regime            import detect_regime, get_min_threshold
from scanner.entry_engine      import evaluate_entry, EntrySignal
from storage.sqlite_db         import init_db, save_signal
from utils.config import TOP_N
from utils.logger import get_logger

log = get_logger(__name__)


def _recent_high_stats(df_5m, lookback=20):
    if df_5m is None or len(df_5m) < 2:
        return 0.0, 0.0, 0.0
    window      = df_5m["high"].iloc[-lookback:]
    idx_of_high = window.idxmax()
    high_price  = float(window.max())
    last_price  = float(df_5m["close"].iloc[-1])
    high_age    = len(df_5m) - 1 - df_5m.index.get_loc(idx_of_high)
    pullback    = (high_price - last_price) / high_price * 100 if high_price > 0 else 0.0
    return high_price, float(high_age), round(pullback, 3)


def scan_coin(symbol: str, end_time: Optional[int] = None) -> Optional[dict]:
    dfs = get_all_timeframes(symbol, end_time=end_time) # מעביר את הזמן ההיסטורי הלאה
    if not all(tf in dfs for tf in ["1min","5min","15min","1hour"]):
        return None

    df_1m  = dfs["1min"]
    df_5m  = dfs["5min"]
    df_15m = dfs["15min"]
    df_1h  = dfs["1hour"]

    last_price = float(df_5m["close"].iloc[-1])

    mom = calc_momentum(df_1m, df_5m, df_15m, df_1h)
    vol = calc_volume(df_5m)
    ind = calc_indicators(df_5m, df_1h)
    rs  = calc_relative_strength(df_1h)

    # RVOL filter
    if vol["rvol"] < 1.5:
        return None

    # Hard filters
    passed, reason = passes_hard_filters(
        rsi_14=ind["rsi_14"], vwap_dist=ind["vwap_dist"],
        momentum_5m=mom["momentum_5m"], momentum_15m=mom["momentum_15m"],
        rvol=vol["rvol"], rs_1h=rs["rs_1h"], momentum_1h=mom["momentum_1h"],
    )
    if not passed:
        log.debug(f"{symbol}: {reason}")
        return None

    high_price, high_age, pullback = _recent_high_stats(df_5m)
    proximity = (high_price - last_price) / high_price * 100 if high_price > 0 else 0.0

    fs = freshness_score(high_age, pullback, mom["momentum_5m"], ind["vwap_dist"], vol["vol_accel"])
    ms = momentum_score(vol["rvol"], vol["dollar_volume"], ind["rsi_14"], mom["momentum_5m"], mom["momentum_15m"])
    bs = breakout_score(proximity, vol["vol_accel"], ind["vwap_dist"], mom["momentum_5m"], mom["momentum_15m"], ind["atr_14"], last_price)
    score = final_score(fs, ms, bs, rvol=vol["rvol"], vol_accel=vol["vol_accel"], vwap_dist=ind["vwap_dist"])
    score = apply_trader_overrides(score, {**mom, **vol, **ind, "rs_1h": rs["rs_1h"], "rs_4h": rs["rs_4h"]})

    # RS bonus
    if rs["rs_1h"] > 1.0: score = min(100.0, score + 4)
    if rs["rs_4h"] > 2.0: score = min(100.0, score + 4)
    score = round(score, 1)

    # Flow Engine
    flow = calc_flow_score(symbol, df_5m, rs_btc_1h=rs["rs_1h"])

    # Pre-Breakout Score
    pre = calc_pre_breakout_score(
        df_5m=df_5m, df_1h=df_1h,
        oi_change_pct=flow.get("oi_change", 0),
        funding_rate=flow.get("funding_rate", 0),
        rs_1h=rs["rs_1h"], rs_4h=rs["rs_4h"],
        mom_15m=mom["momentum_15m"], mom_1h=mom["momentum_1h"],
        ema20=ind["ema20"], ema50=ind["ema50"], price=last_price,
    )

    # Entry Engine
    entry_signal = evaluate_entry(
        coin={**mom, **vol, **ind, "rs_1h": rs["rs_1h"], "rs_4h": rs["rs_4h"],
              "vwap": ind["vwap"], "ema20": ind["ema20"], "rsi_14": ind["rsi_14"], "rvol": vol["rvol"]},
        df_5m=df_5m, btc_mom_5m=0.0,
    )

    return {
        "symbol":       symbol,
        "price":        last_price,
        "momentum_3m":  mom["momentum_3m"],
        "momentum_5m":  mom["momentum_5m"],
        "momentum_15m": mom["momentum_15m"],
        "momentum_1h":  mom["momentum_1h"],
        "rvol":         vol["rvol"],
        "vol_accel":    vol["vol_accel"],
        "dollar_volume": vol["dollar_volume"],
        "vwap":         ind["vwap"],
        "vwap_dist":    ind["vwap_dist"],
        "ema20":        ind["ema20"],
        "ema50":        ind["ema50"],
        "rsi_14":       ind["rsi_14"],
        "atr_14":       ind["atr_14"],
        "rs_1h":        rs["rs_1h"],
        "rs_4h":        rs["rs_4h"],
        "freshness_score": fs,
        "momentum_score":  ms,
        "breakout_score":  bs,
        "final_score":     score,
        # flow
        "flow_score":       flow["flow_score"],
        "flow_components":  flow["components"],
        "is_compressed":    flow["is_compressed"],
        "whale_detected":   flow["whale_detected"],
        "cvd_trend":        flow["cvd_trend"],
        "oi_change":        flow["oi_change"],
        "funding_rate":     flow["funding_rate"],
        # pre-breakout
        "pre_score":        pre["pre_score"],
        "phase":            pre["phase"],
        "phase_label":      pre["phase_label"],
        "pre_components":   pre["components"],
        # entry
        "entry_decision":  entry_signal.decision,
        "entry_setup":     entry_signal.setup_type,
        "entry_price":     entry_signal.entry,
        "entry_sl":        entry_signal.sl,
        "entry_tp1":       entry_signal.tp1,
        "entry_tp2":       entry_signal.tp2,
        "entry_rr":        entry_signal.rr,
        "entry_reason":    entry_signal.reason,
        "is_sympathy":     False,
        "leader":          "",
        "regime":          "",
    }


def rank_universe(symbols: list[str]) -> list[dict]:
    init_db()

    # BTC reference
    log.info("Loading BTC reference...")
    btc_dfs = get_all_timeframes("BTCUSDT")
    btc_1h  = btc_dfs.get("1hour")
    if btc_1h is not None:
        set_btc_reference(btc_1h)

    # BTC moves for regime
    btc_1h_move = btc_4h_move = btc_24h_move = 0.0
    if btc_1h is not None and len(btc_1h) > 24:
        c = btc_1h["close"]
        btc_1h_move  = round((float(c.iloc[-1])-float(c.iloc[-2]))/float(c.iloc[-2])*100, 2)
        btc_4h_move  = round((float(c.iloc[-1])-float(c.iloc[-5]))/float(c.iloc[-5])*100, 2)
        btc_24h_move = round((float(c.iloc[-1])-float(c.iloc[-25]))/float(c.iloc[-25])*100, 2)

    regime        = detect_regime(btc_1h_move, btc_4h_move, btc_24h_move, 0.0)
    min_threshold = get_min_threshold(regime)
    log.info(f"Regime: {regime} | BTC 1h={btc_1h_move:+.1f}% | Min: {min_threshold}")

    # Sympathy
    leaders        = find_leaders(symbols)
    sympathy_plays = find_sympathy_plays(leaders, symbols)

    results = []
    for i, sym in enumerate(symbols, 1):
        if i % 50 == 0:
            log.info(f"Scanning {i}/{len(symbols)}...")
        try:
            r = scan_coin(sym)
            if r is None:
                continue
            s_bonus = sympathy_bonus(sym, sympathy_plays)
            if s_bonus > 0:
                r["final_score"] = round(min(r["final_score"] + s_bonus, 100.0), 1)
                r["is_sympathy"] = True
                info = next((p for p in sympathy_plays if p["symbol"] == sym), {})
                r["leader"] = info.get("leader","")
            r["regime"] = regime
            results.append(r)
        except Exception as e:
            log.warning(f"{sym}: {e}")

    results.sort(key=lambda x: x["final_score"], reverse=True)
    top = [r for r in results if r["final_score"] >= min_threshold][:TOP_N]

    for coin in top:
        try:
            save_signal(coin, regime=regime,
                        is_sympathy=coin.get("is_sympathy",False),
                        leader=coin.get("leader",""))
        except Exception as e:
            log.warning(f"DB save: {e}")

    log.info(f"Done: {len(results)} scored | {len(top)} selected | regime={regime}")
    return top
