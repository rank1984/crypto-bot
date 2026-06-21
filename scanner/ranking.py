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
    passes_hard_filters, apply_trader_overrides,
)
from scanner.relative_strength import calc_relative_strength, set_btc_reference
from scanner.sympathy          import find_leaders, find_sympathy_plays, sympathy_bonus
from scanner.open_interest     import get_oi_and_funding
from scanner.regime            import detect_regime, get_regime_weights, get_min_threshold
from scanner.flow_engine          import calc_flow_score
from scanner.pre_explosion_engine import calc_pre_explosion
from scanner.fakeout_engine       import detect_fakeout
from scanner.alignment_engine     import calc_alignment, alignment_summary
from scanner.alpha_engine         import calc_alpha_score, alpha_bonus
from scanner.liquidity_engine     import calc_liquidity_score
from scanner.entry_engine         import evaluate_entry, EntrySignal
from storage.sqlite_db            import init_db, save_signal
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

    # ── Flow Engine ───────────────────────────────────────────────────────────
    flow = calc_flow_score(
        symbol=symbol, df_5m=df_5m,
        rs_btc_1h=rs["rs_1h"], rs_eth_1h=0.0,
    )

    # ── Alignment Engine ──────────────────────────────────────────────────────
    df_4h = dfs.get("4hour")   # KuCoin: "4hour"
    align = calc_alignment(df_5m, df_15m, df_1h, df_4h)

    # ── Fakeout Detector — פסילה מוחלטת ──────────────────────────────────────
    fakeout = detect_fakeout(
        df_5m=df_5m,
        rvol=vol["rvol"],
        momentum_15m=mom["momentum_15m"],
        momentum_5m=mom["momentum_5m"],
        rs_btc_1h=rs["rs_1h"],
        vwap_dist=ind["vwap_dist"],
        rsi_14=ind["rsi_14"],
    )
    if fakeout["is_fakeout"]:
        log.debug(f"{symbol}: fakeout {fakeout['fakeout_score']:.0f} — {fakeout['penalties'][:1]}")
        return None

    # ── Hard Filters — פסילה מוחלטת ──────────────────────────────────────────
    passed, reason = passes_hard_filters(
        rsi_14=ind["rsi_14"],
        vwap_dist=ind["vwap_dist"],
        momentum_5m=mom["momentum_5m"],
        momentum_15m=mom["momentum_15m"],
        rvol=vol["rvol"],
        rs_1h=rs["rs_1h"],
        momentum_1h=mom["momentum_1h"],
    )
    if not passed:
        log.debug(f"{symbol}: filtered out — {reason}")
        return None

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

    # ── Trader Overrides — בונוסים וקנסות ────────────────────────────────────
    score = apply_trader_overrides(score, {
        **mom, **vol, **ind,
        "rs_1h": rs["rs_1h"],
        "rs_4h": rs["rs_4h"],
    })

    # RS bonus: מטבע חזק מ-BTC מקבל עד +8 נקודות
    rs_bonus = 0.0
    if rs["rs_1h"] > 1.0: rs_bonus += 4
    if rs["rs_4h"] > 2.0: rs_bonus += 4
    score = round(min(score + rs_bonus, 100.0), 1)

    # ── Pre-Explosion Engine ──────────────────────────────────────────────────
    pre_exp = calc_pre_explosion(
        flow_score=flow["flow_score"],
        final_score=score,
        breakout_score=bs,
        is_compressed=flow["is_compressed"],
        whale_detected=flow["whale_detected"],
        cvd_trend=flow["cvd_trend"],
        oi_change=flow["oi_change"],
        rs_btc_1h=rs["rs_1h"],
        momentum_15m=mom["momentum_15m"],
        vol_accel=flow["vol_accel"],
    )

    # Flow bonus: flow_score גבוה מוסיף עד +8 לציון הסופי
    flow_bonus = min(8.0, flow["flow_score"] / 100 * 8)
    score = round(min(score + flow_bonus, 100.0), 1)

    # ── Alpha Engine ──────────────────────────────────────────────────────────
    alpha = calc_alpha_score(
        flow_components=flow["components"],
        alignment_score=align["alignment_score"],
        regime=regime if "regime" in dir() else "RANGE",
        rs_btc_1h=rs["rs_1h"],
        rs_btc_4h=rs["rs_4h"],
    )
    score = round(min(score + alpha_bonus(alpha["alpha_score"]), 100.0), 1)

    # ── Liquidity Engine ──────────────────────────────────────────────────────
    liquidity = calc_liquidity_score(symbol)

    # ── Entry Engine ──────────────────────────────────────────────────────────
    entry_signal = evaluate_entry(
        coin={
            **mom, **vol, **ind,
            "rs_1h": rs["rs_1h"], "rs_4h": rs["rs_4h"],
            "vwap": ind["vwap"], "ema20": ind["ema20"],
            "rsi_14": ind["rsi_14"], "rvol": vol["rvol"],
        },
        df_5m=df_5m,
        btc_mom_5m=0.0,   # מתעדכן ב-rank_universe
    )

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
        # flow engine
        "flow_score":      flow["flow_score"],
        "flow_components": flow["components"],
        "is_compressed":   flow["is_compressed"],
        "whale_detected":  flow["whale_detected"],
        "cvd_trend":       flow["cvd_trend"],
        "oi_change":       flow["oi_change"],
        "funding_rate":    flow["funding_rate"],
        # pre-explosion
        "pre_exp_score":   pre_exp["score"],
        "pre_exp_phase":   pre_exp["phase"],
        "pre_exp_emoji":   pre_exp["emoji"],
        "pre_exp_dir":     pre_exp["direction"],
        # alignment
        "alignment_score":   align["alignment_score"],
        "aligned_count":     align["aligned_count"],
        "alignment_summary": alignment_summary(align["details"]),
        # alpha
        "alpha_score":       alpha["alpha_score"],
        "signal_quality":    alpha["signal_quality"],
        "edge_factors":      alpha["edge_factors"],
        # liquidity
        "liquidity_score":   liquidity["liquidity_score"],
        "bid_ask_ratio":     liquidity["bid_ask_ratio"],
        # entry engine
        "entry_decision":  entry_signal.decision,
        "entry_setup":     entry_signal.setup_type,
        "entry_price":     entry_signal.entry,
        "entry_sl":        entry_signal.sl,
        "entry_tp1":       entry_signal.tp1,
        "entry_tp2":       entry_signal.tp2,
        "entry_rr":        entry_signal.rr,
        "entry_reason":    entry_signal.reason,
    }


def rank_universe(symbols: list[str]) -> list[dict]:
    """
    Scans all symbols, scores them, returns Top N sorted by final_score.
    """
    # ── Init DB ───────────────────────────────────────────────────────────────
    init_db()

    # ── BTC reference ─────────────────────────────────────────────────────────
    log.info("Loading BTC reference...")
    btc_dfs = get_all_timeframes("BTCUSDT")
    btc_1h  = btc_dfs.get("1hour")
    if btc_1h is not None:
        set_btc_reference(btc_1h)

    # ── Regime Detection ──────────────────────────────────────────────────────
    btc_1h_move  = 0.0
    btc_4h_move  = 0.0
    btc_24h_move = 0.0
    if btc_1h is not None and len(btc_1h) > 24:
        close = btc_1h["close"]
        btc_1h_move  = round((float(close.iloc[-1]) - float(close.iloc[-2]))  / float(close.iloc[-2])  * 100, 2)
        btc_4h_move  = round((float(close.iloc[-1]) - float(close.iloc[-5]))  / float(close.iloc[-5])  * 100, 2)
        btc_24h_move = round((float(close.iloc[-1]) - float(close.iloc[-25])) / float(close.iloc[-25]) * 100, 2)

    regime = detect_regime(btc_1h_move, btc_4h_move, btc_24h_move, alt_avg_1h=0.0)
    min_threshold = get_min_threshold(regime)
    log.info(f"Regime: {regime} | BTC 1h={btc_1h_move:+.1f}% 4h={btc_4h_move:+.1f}% | Min score: {min_threshold}")

    # ── Sympathy Engine ───────────────────────────────────────────────────────
    log.info("Finding sympathy plays...")
    leaders       = find_leaders(symbols)
    sympathy_plays = find_sympathy_plays(leaders, symbols)
    if sympathy_plays:
        log.info(f"Sympathy plays found: {[p['symbol'] for p in sympathy_plays[:3]]}")

    # ── Scan ──────────────────────────────────────────────────────────────────
    results = []
    total   = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i % 50 == 0:
            log.info(f"Scanning {i}/{total}...")
        try:
            r = scan_coin(sym)
            if r is None:
                continue

            # Sympathy bonus
            s_bonus = sympathy_bonus(sym, sympathy_plays)
            if s_bonus > 0:
                r["final_score"]    = round(min(r["final_score"] + s_bonus, 100.0), 1)
                r["is_sympathy"]    = True
                r["sympathy_bonus"] = s_bonus
                leader_info = next((p for p in sympathy_plays if p["symbol"] == sym), {})
                r["leader"] = leader_info.get("leader", "")
            else:
                r["is_sympathy"] = False
                r["leader"]      = ""

            r["regime"] = regime
            results.append(r)

        except Exception as e:
            log.warning(f"{sym}: unexpected error — {e}")

    # ── Sort & filter by regime threshold ─────────────────────────────────────
    results.sort(key=lambda x: x["final_score"], reverse=True)
    top = [r for r in results if r["final_score"] >= min_threshold][:TOP_N]

    # ── Save to DB ────────────────────────────────────────────────────────────
    for coin in top:
        try:
            save_signal(
                coin, regime=regime,
                is_sympathy=coin.get("is_sympathy", False),
                leader=coin.get("leader", ""),
            )
        except Exception as e:
            log.warning(f"DB save failed for {coin['symbol']}: {e}")

    log.info(f"Ranking complete: {len(results)} scored | regime={regime} | top={len(top)}")
    return top

    log.info(f"Ranking complete: {len(results)} coins scored, top {TOP_N} selected")
    return top
