"""
CRYPTO-BOT Elite — Missed Winners Analyzer

בסוף כל יום:
1. מוצא מטבעות שעלו 30%+ / 50%+ / 100%+
2. בודק באיזה שלב הבוט פספס אותם
3. מוציא דוח עם סיבות

שלבי הסינון (pipeline):
    A. Universe     — האם המטבע היה ב-Universe?
    B. RVOL         — rvol < 0.8
    C. Hard Filters — passes_hard_filters
    D. Ranking      — final_score < min_threshold
    E. Quality Gate — quality_gate downgrade
    F. Signal       — signal_filter → IGNORE
    G. ✅ נבחר      — הגיע לטלגרם
"""
import os
import requests
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger(__name__)

_CG      = "https://api.coingecko.com/api/v3"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}


def get_todays_winners(min_gain_pct: float = 30.0) -> list[dict]:
    try:
        r = requests.get(f"{_CG}/coins/markets", headers=_HEADERS, params={
            "vs_currency": "usd",
            "order": "price_change_percentage_24h_desc",
            "per_page": 250, "page": 1, "sparkline": False,
        }, timeout=15)
        r.raise_for_status()
        return [
            {"symbol": c["symbol"].upper()+"USDT",
             "name": c["name"],
             "gain": round(c.get("price_change_percentage_24h") or 0, 1),
             "volume": c.get("total_volume", 0)}
            for c in r.json()
            if (c.get("price_change_percentage_24h") or 0) >= min_gain_pct
        ]
    except Exception as e:
        log.error(f"get_todays_winners: {e}")
        return []


def trace_coin(symbol: str) -> dict:
    """עוקב אחרי מטבע דרך כל שלב ב-pipeline."""
    from scanner.dynamic_universe  import build_dynamic_universe
    from scanner.universe          import get_coins
    from scanner.market_data       import get_all_timeframes
    from scanner.volume            import calc_volume
    from scanner.indicators        import calc_indicators
    from scanner.momentum          import calc_momentum
    from scanner.relative_strength import calc_relative_strength
    from scanner.scoring           import (passes_hard_filters, final_score,
                                           freshness_score, momentum_score,
                                           breakout_score, apply_trader_overrides)
    from scanner.flow_engine       import calc_flow_score
    from scanner.pre_breakout      import calc_pre_breakout_score
    from scanner.quality_gate      import apply_quality_gate
    from scanner.signal_filter     import classify_signal
    from scanner.regime            import detect_regime, get_min_threshold

    # A. Universe
    try:
        use_dyn = os.getenv("USE_DYNAMIC_UNIVERSE","true").lower() == "true"
        universe = build_dynamic_universe() if use_dyn else [
            c["symbol"] if isinstance(c, dict) else c for c in get_coins()
        ]
        if symbol not in universe:
            return {"stage": "A_UNIVERSE", "reason": "לא היה ב-Universe"}
    except Exception as e:
        return {"stage": "A_UNIVERSE", "reason": f"שגיאה ב-universe: {e}"}

    # B. Data + RVOL
    try:
        dfs = get_all_timeframes(symbol)
        if not all(tf in dfs for tf in ["1min","5min","15min","1hour"]):
            return {"stage": "B_DATA", "reason": "נתוני נרות חסרים"}

        vol = calc_volume(dfs["5min"])
        if vol["rvol"] < 0.8:
            return {"stage": "B_RVOL",
                    "reason": f"RVOL נמוך מדי ({vol['rvol']:.2f} < 0.8)"}

        # C. Hard Filters
        ind = calc_indicators(dfs["5min"], dfs["1hour"])
        mom = calc_momentum(dfs["1min"], dfs["5min"], dfs["15min"], dfs["1hour"])
        rs  = calc_relative_strength(dfs["1hour"])

        passed, reason = passes_hard_filters(
            rsi_14=ind["rsi_14"], vwap_dist=ind["vwap_dist"],
            momentum_5m=mom["momentum_5m"], momentum_15m=mom["momentum_15m"],
            rvol=vol["rvol"], rs_1h=rs["rs_1h"], momentum_1h=mom["momentum_1h"],
        )
        if not passed:
            return {"stage": "C_HARD_FILTER", "reason": f"Hard filter: {reason}"}

        # D. Ranking
        flow = calc_flow_score(symbol, dfs["5min"], rs_btc_1h=rs["rs_1h"])
        pre  = calc_pre_breakout_score(
            df_5m=dfs["5min"], df_1h=dfs["1hour"],
            oi_change_pct=flow["oi_change"], funding_rate=flow["funding_rate"],
            rs_1h=rs["rs_1h"], rs_4h=rs["rs_4h"],
            mom_15m=mom["momentum_15m"], mom_1h=mom["momentum_1h"],
            ema20=ind["ema20"], ema50=ind["ema50"],
            price=float(dfs["5min"]["close"].iloc[-1]),
        )
        last  = float(dfs["5min"]["close"].iloc[-1])
        high_p = float(dfs["5min"]["high"].iloc[-20:].max())
        prox  = (high_p - last) / high_p * 100 if high_p > 0 else 0
        age   = float(dfs["5min"]["high"].iloc[-20:].idxmax())

        fs    = freshness_score(age, prox, mom["momentum_5m"], ind["vwap_dist"], vol["vol_accel"])
        ms    = momentum_score(vol["rvol"], vol["dollar_volume"], ind["rsi_14"], mom["momentum_5m"], mom["momentum_15m"])
        bs    = breakout_score(prox, vol["vol_accel"], ind["vwap_dist"], mom["momentum_5m"], mom["momentum_15m"], ind["atr_14"], last)
        score = final_score(fs, ms, bs, rvol=vol["rvol"], vol_accel=vol["vol_accel"], vwap_dist=ind["vwap_dist"])
        score = apply_trader_overrides(score, {**mom, **vol, **ind, "rs_1h": rs["rs_1h"], "rs_4h": rs["rs_4h"]})

        regime    = detect_regime(0, 0, 0, 0)
        threshold = get_min_threshold(regime)
        if score < threshold:
            return {"stage": "D_RANKING",
                    "reason": f"score נמוך ({score:.0f} < {threshold}) | flow={flow['flow_score']:.0f} pre={pre['pre_score']:.0f}"}

        # E. Quality Gate + F. Signal Filter
        coin = {"entry_decision": "WAIT",
                "flow_score": flow["flow_score"],
                "pre_score":  pre["pre_score"],
                "oi_change":  flow["oi_change"],
                "is_compressed": flow["is_compressed"],
                "flow_components": flow.get("components", {})}
        coin = apply_quality_gate(coin)
        sig  = classify_signal(coin)

        if sig == "IGNORE":
            return {"stage": "F_SIGNAL",
                    "reason": f"IGNORE | flow={flow['flow_score']:.0f} pre={pre['pre_score']:.0f}"}

        return {"stage": "G_SELECTED",
                "reason": f"✅ {sig} | flow={flow['flow_score']:.0f} pre={pre['pre_score']:.0f} score={score:.0f}"}

    except Exception as e:
        return {"stage": "Z_ERROR", "reason": str(e)[:80]}


def run_analysis(min_gain: float = 30.0, top_n: int = 20) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"🔍 MISSED WINNERS — {today}",
        f"🎯 מחפש מטבעות שעלו {min_gain}%+ ב-24h",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    winners = get_todays_winners(min_gain)[:top_n]
    if not winners:
        lines.append("❌ לא נמצאו מטבעות עם עלייה מספקת.")
        return "\n".join(lines)

    lines.append(f"נמצאו {len(winners)} מטבעות:")
    stage_counts: dict[str, int] = {}

    for w in winners:
        result = trace_coin(w["symbol"])
        stage  = result["stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        icon = "✅" if stage == "G_SELECTED" else "❌"
        lines.append(f"\n{icon} {w['symbol']} (+{w['gain']}%)")
        lines.append(f"   {result['reason']}")

    # סיכום
    names = {
        "A_UNIVERSE":    "לא ב-Universe",
        "B_DATA":        "נתונים חסרים",
        "B_RVOL":        "RVOL נמוך",
        "C_HARD_FILTER": "Hard Filters",
        "D_RANKING":     "Score נמוך",
        "F_SIGNAL":      "Signal Filter",
        "G_SELECTED":    "✅ נבחר",
        "Z_ERROR":       "שגיאה",
    }
    lines += ["", "━━━━━━━━━━━━━━━━━━━━━━", "📊 פירוט שלבי פספוס:"]
    for stage, cnt in sorted(stage_counts.items(), key=lambda x: -x[1]):
        lines.append(f"   {names.get(stage, stage)}: {cnt}")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Missed Winners Analyzer")
    parser.add_argument("--min-gain", type=float, default=30.0)
    parser.add_argument("--top",      type=int,   default=20)
    parser.add_argument("--send",     action="store_true")
    args = parser.parse_args()

    report = run_analysis(args.min_gain, args.top)
    print(report)

    if args.send:
        from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": report[:4096]},
                timeout=10,
            )
            print("✅ נשלח לטלגרם")
