"""Pipeline Audit — מסך אבחון מלא של הבוט"""
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from utils.logger import get_logger
log = get_logger(__name__)


def run_audit(sample: int = 50) -> str:
    from scanner.dynamic_universe  import build_dynamic_universe
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

    symbols = build_dynamic_universe()
    if sample and len(symbols) > sample:
        import random; random.seed(42)
        symbols = random.sample(symbols, sample)

    regime    = detect_regime(0,0,0,0)
    threshold = get_min_threshold(regime)

    cnt = dict(universe=len(symbols), no_data=0, rvol_fail=0,
               hard_fail=0, score_fail=0, ignore=0, watch=0, prepare=0, buy=0)
    rvol_vals, flow_vals, score_vals = [], [], []
    hard_reasons = {}

    for sym in symbols:
        try:
            dfs = get_all_timeframes(sym)
            if not all(tf in dfs for tf in ["1min","5min","15min","1hour"]):
                cnt["no_data"] += 1; continue

            vol = calc_volume(dfs["5min"])
            rvol_vals.append(vol["rvol"])
            if vol["rvol"] < 0.8:
                cnt["rvol_fail"] += 1; continue

            ind = calc_indicators(dfs["5min"], dfs["1hour"])
            mom = calc_momentum(dfs["1min"], dfs["5min"], dfs["15min"], dfs["1hour"])
            rs  = calc_relative_strength(dfs["1hour"])

            passed, reason = passes_hard_filters(
                rsi_14=ind["rsi_14"], vwap_dist=ind["vwap_dist"],
                momentum_5m=mom["momentum_5m"], momentum_15m=mom["momentum_15m"],
                rvol=vol["rvol"], rs_1h=rs["rs_1h"], momentum_1h=mom["momentum_1h"],
            )
            if not passed:
                cnt["hard_fail"] += 1
                hard_reasons[reason] = hard_reasons.get(reason,0)+1; continue

            flow = calc_flow_score(sym, dfs["5min"], rs_btc_1h=rs["rs_1h"])
            pre  = calc_pre_breakout_score(
                df_5m=dfs["5min"], df_1h=dfs["1hour"],
                oi_change_pct=flow["oi_change"], funding_rate=flow["funding_rate"],
                rs_1h=rs["rs_1h"], rs_4h=rs["rs_4h"],
                mom_15m=mom["momentum_15m"], mom_1h=mom["momentum_1h"],
                ema20=ind["ema20"], ema50=ind["ema50"],
                price=float(dfs["5min"]["close"].iloc[-1]),
            )
            flow_vals.append(flow["flow_score"])

            last   = float(dfs["5min"]["close"].iloc[-1])
            high_p = float(dfs["5min"]["high"].iloc[-20:].max())
            prox   = (high_p-last)/high_p*100 if high_p>0 else 0
            age    = float(dfs["5min"]["high"].iloc[-20:].idxmax())

            fs  = freshness_score(age, prox, mom["momentum_5m"], ind["vwap_dist"], vol["vol_accel"])
            ms  = momentum_score(vol["rvol"], vol["dollar_volume"], ind["rsi_14"], mom["momentum_5m"], mom["momentum_15m"])
            bs  = breakout_score(prox, vol["vol_accel"], ind["vwap_dist"], mom["momentum_5m"], mom["momentum_15m"], ind["atr_14"], last)
            sc  = final_score(fs, ms, bs, rvol=vol["rvol"], vol_accel=vol["vol_accel"], vwap_dist=ind["vwap_dist"])
            sc  = apply_trader_overrides(sc, {**mom,**vol,**ind,"rs_1h":rs["rs_1h"],"rs_4h":rs["rs_4h"]})
            score_vals.append(sc)

            if sc < threshold:
                cnt["score_fail"] += 1; continue

            coin = {"entry_decision":"WAIT","flow_score":flow["flow_score"],
                    "pre_score":pre["pre_score"],"oi_change":flow["oi_change"],
                    "is_compressed":flow["is_compressed"],"flow_components":flow.get("components",{})}
            coin = apply_quality_gate(coin)
            sig  = classify_signal(coin)
            cnt[{"BUY":"buy","PREPARE":"prepare","WATCH":"watch"}.get(sig,"ignore")] += 1
        except Exception as e:
            cnt["no_data"] += 1; log.debug(f"{sym}: {e}")

    n   = cnt["universe"]
    p   = lambda v: f"({v/n*100:.0f}%)" if n>0 else ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"🔬 PIPELINE AUDIT — {now}",
        f"Regime: {regime} | Threshold: {threshold}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Universe:              {n:>4}",
        f"נתונים חסרים:          {cnt['no_data']:>4}  {p(cnt['no_data'])}",
        f"נפסלו RVOL (<0.8):     {cnt['rvol_fail']:>4}  {p(cnt['rvol_fail'])}",
        f"נפסלו Hard Filters:    {cnt['hard_fail']:>4}  {p(cnt['hard_fail'])}",
        f"נפסלו Score (<{threshold}):   {cnt['score_fail']:>4}  {p(cnt['score_fail'])}",
        f"נפסלו Signal (IGNORE): {cnt['ignore']:>4}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"WATCH:                 {cnt['watch']:>4}",
        f"PREPARE:               {cnt['prepare']:>4}",
        f"BUY:                   {cnt['buy']:>4}",
    ]

    # צוואר הבקבוק
    stages = {k: cnt[k] for k in ("rvol_fail","hard_fail","score_fail","no_data")}
    bottleneck = max(stages, key=stages.get)
    if stages[bottleneck] > 0:
        lines += ["", f"🔍 צוואר הבקבוק: {bottleneck} — {stages[bottleneck]} מטבעות ({stages[bottleneck]/n*100:.0f}%)"]

        # המלצת כיול
        if bottleneck == "rvol_fail" and rvol_vals:
            above_05 = sum(1 for v in rvol_vals if v >= 0.5)
            lines.append(f"   💡 אם threshold יורד ל-0.5 → {above_05-sum(1 for v in rvol_vals if v>=0.8)} מטבעות נוספים")
        if bottleneck == "score_fail" and score_vals:
            above_55 = sum(1 for v in score_vals if v >= 55)
            lines.append(f"   💡 אם threshold יורד ל-55 → {above_55} מטבעות נוספים")

    # Hard filter סיבות
    if hard_reasons:
        lines += ["", "Hard Filter סיבות:"]
        for r, c2 in sorted(hard_reasons.items(), key=lambda x:-x[1])[:4]:
            lines.append(f"   {r}: {c2}")

    # RVOL stats
    if rvol_vals:
        lines += ["", f"RVOL (n={len(rvol_vals)}): avg={statistics.mean(rvol_vals):.2f} median={statistics.median(rvol_vals):.2f}",
                  f"   >0.5:{sum(1 for v in rvol_vals if v>=0.5)}  >0.8:{sum(1 for v in rvol_vals if v>=0.8)}  >1.5:{sum(1 for v in rvol_vals if v>=1.5)}"]

    # Flow stats
    if flow_vals:
        lines += [f"Flow (n={len(flow_vals)}): avg={statistics.mean(flow_vals):.1f}",
                  f"   >45:{sum(1 for v in flow_vals if v>=45)}  >55:{sum(1 for v in flow_vals if v>=55)}  >65:{sum(1 for v in flow_vals if v>=65)}"]

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse, requests
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--send",   action="store_true")
    args = parser.parse_args()
    report = run_audit(args.sample)
    print(report)
    if args.send:
        from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id":TELEGRAM_CHAT_ID,"text":report[:4096]},timeout=10)
