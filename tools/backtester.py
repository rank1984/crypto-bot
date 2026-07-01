"""
CRYPTO-BOT Elite — Backtester

בודק את האסטרטגיה על נתוני עבר.
שואל: אם הריצה סריקה לפני X שעות — מה היה קורה?

שאלות שעונה:
    - RVOL 0.8 vs 1.5 — מה עדיף?
    - Flow ≥55 vs ≥65 — מה עדיף?
    - Quality Gate ON/OFF — כמה משפיע?
    - SL 2% vs 3% — מה האחוז הנכון?

שיטה:
    1. KuCoin candles היסטוריים (endAt param)
    2. מריץ scoring על כל חלון זמן
    3. בודק מה קרה אחר כך (forward returns)
    4. מחשב Win Rate, Profit Factor, Max Drawdown
"""
import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

_KUCOIN  = "https://api.kucoin.com"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}


# ─── Data Fetch ───────────────────────────────────────────────────────────────

def _get_candles_at(symbol: str, interval: str, end_ts: int, limit: int = 100) -> pd.DataFrame | None:
    """נרות היסטוריים עד end_ts."""
    kucoin_sym = symbol.replace("USDT", "-USDT")
    try:
        r = requests.get(
            f"{_KUCOIN}/api/v1/market/candles",
            headers=_HEADERS,
            params={"symbol": kucoin_sym, "type": interval, "endAt": end_ts},
            timeout=10,
        )
        if r.status_code != 200 or r.json().get("code") != "200000":
            return None
        raw = r.json().get("data", [])
        if not raw:
            return None
        rows = list(reversed(raw[:limit]))
        df = pd.DataFrame(rows, columns=["ts","open","close","high","low","volume","turnover"])
        for col in ["open","high","low","close","volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["open_time"]    = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
        df["close_time"]   = df["open_time"]
        df["quote_volume"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0)
        df["trades"]       = 0
        return df[["open_time","open","high","low","close","volume","close_time","quote_volume","trades"]].reset_index(drop=True)
    except Exception as e:
        log.debug(f"candles {symbol} {interval}: {e}")
        return None


def _get_forward_return(symbol: str, entry_ts: int, hours: int) -> float | None:
    """כמה % עלה/ירד המטבע X שעות אחרי entry_ts."""
    future_ts = entry_ts + hours * 3600
    df = _get_candles_at(symbol, "1hour", future_ts, limit=hours + 2)
    if df is None or len(df) < 2:
        return None
    entry_price  = float(df["close"].iloc[0])
    future_price = float(df["close"].iloc[-1])
    if entry_price <= 0:
        return None
    return round((future_price - entry_price) / entry_price * 100, 2)


# ─── Scoring at Time T ────────────────────────────────────────────────────────

def _score_at(symbol: str, end_ts: int, config: dict) -> dict | None:
    """מריץ scoring בנקודת זמן היסטורית."""
    from scanner.volume            import calc_volume
    from scanner.indicators        import calc_indicators
    from scanner.momentum          import calc_momentum
    from scanner.relative_strength import calc_relative_strength
    from scanner.scoring           import (passes_hard_filters, final_score,
                                           freshness_score, momentum_score,
                                           breakout_score, apply_trader_overrides)
    from scanner.flow_engine       import calc_flow_score
    from scanner.pre_breakout      import calc_pre_breakout_score

    dfs = {}
    for tf in ["1min", "5min", "15min", "1hour"]:
        df = _get_candles_at(symbol, tf, end_ts)
        if df is not None and len(df) >= 5:
            dfs[tf] = df
        else:
            # proxy מ-5min אם חסר
            if "5min" in dfs:
                dfs[tf] = dfs["5min"].copy()
        time.sleep(0.05)

    if "5min" not in dfs or "1hour" not in dfs:
        return None

    try:
        vol = calc_volume(dfs["5min"])
        rvol_threshold = config.get("rvol_threshold", 0.8)
        if vol["rvol"] < rvol_threshold:
            return {"filtered_by": "rvol", "rvol": vol["rvol"]}

        ind = calc_indicators(dfs["5min"], dfs["1hour"])
        mom = calc_momentum(dfs["1min"], dfs["5min"], dfs["15min"], dfs["1hour"])
        rs  = calc_relative_strength(dfs["1hour"])

        passed, reason = passes_hard_filters(
            rsi_14=ind["rsi_14"], vwap_dist=ind["vwap_dist"],
            momentum_5m=mom["momentum_5m"], momentum_15m=mom["momentum_15m"],
            rvol=vol["rvol"], rs_1h=rs["rs_1h"], momentum_1h=mom["momentum_1h"],
        )
        if not passed:
            return {"filtered_by": "hard", "reason": reason}

        flow = calc_flow_score(symbol, dfs["5min"], rs_btc_1h=rs["rs_1h"])
        if flow["flow_score"] < config.get("flow_threshold", 55):
            return {"filtered_by": "flow", "flow": flow["flow_score"]}

        pre = calc_pre_breakout_score(
            df_5m=dfs["5min"], df_1h=dfs["1hour"],
            oi_change_pct=flow["oi_change"], funding_rate=flow["funding_rate"],
            rs_1h=rs["rs_1h"], rs_4h=rs["rs_4h"],
            mom_15m=mom["momentum_15m"], mom_1h=mom["momentum_1h"],
            ema20=ind["ema20"], ema50=ind["ema50"],
            price=float(dfs["5min"]["close"].iloc[-1]),
        )

        last   = float(dfs["5min"]["close"].iloc[-1])
        high_p = float(dfs["5min"]["high"].iloc[-20:].max())
        prox   = (high_p - last) / high_p * 100 if high_p > 0 else 0
        age    = float(dfs["5min"]["high"].iloc[-20:].idxmax())

        fs  = freshness_score(age, prox, mom["momentum_5m"], ind["vwap_dist"], vol["vol_accel"])
        ms  = momentum_score(vol["rvol"], vol["dollar_volume"], ind["rsi_14"], mom["momentum_5m"], mom["momentum_15m"])
        bs  = breakout_score(prox, vol["vol_accel"], ind["vwap_dist"], mom["momentum_5m"], mom["momentum_15m"], ind["atr_14"], last)
        sc  = final_score(fs, ms, bs, rvol=vol["rvol"], vol_accel=vol["vol_accel"], vwap_dist=ind["vwap_dist"])
        sc  = apply_trader_overrides(sc, {**mom, **vol, **ind, "rs_1h": rs["rs_1h"], "rs_4h": rs["rs_4h"]})

        score_threshold = config.get("score_threshold", 60)
        if sc < score_threshold:
            return {"filtered_by": "score", "score": sc}

        return {
            "filtered_by": None,
            "price": last,
            "score": sc,
            "flow":  flow["flow_score"],
            "pre":   pre["pre_score"],
            "rvol":  vol["rvol"],
            "oi":    flow["oi_change"],
            "compressed": flow["is_compressed"],
            "rs_1h": rs["rs_1h"],
        }
    except Exception as e:
        log.debug(f"score_at {symbol}: {e}")
        return None


# ─── Run Backtest ─────────────────────────────────────────────────────────────

def run_backtest(
    symbols:  list[str],
    hours_back: int  = 24,
    step_hours: int  = 2,
    config:   dict  | None = None,
    forward_hours: int = 8,
) -> dict:
    """
    מריץ backtest על רשימת מטבעות.

    Parameters
    ----------
    symbols:       רשימת מטבעות
    hours_back:    כמה שעות לאחור לבדוק
    step_hours:    גודל צעד בשעות
    config:        ספי סינון (rvol_threshold, flow_threshold, score_threshold)
    forward_hours: כמה שעות קדימה למדוד return

    Returns
    -------
    dict עם תוצאות
    """
    if config is None:
        config = {"rvol_threshold": 0.8, "flow_threshold": 55, "score_threshold": 60}

    now    = int(datetime.now(timezone.utc).timestamp())
    times  = [now - i * 3600 for i in range(0, hours_back, step_hours)]

    signals = []
    filtered = {"rvol": 0, "hard": 0, "flow": 0, "score": 0}

    for sym in symbols[:20]:    # מגביל ל-20 מטבעות לריצה מהירה
        for ts in times[:6]:    # ו-6 נקודות זמן
            result = _score_at(sym, ts, config)
            if result is None:
                continue

            fb = result.get("filtered_by")
            if fb:
                filtered[fb] = filtered.get(fb, 0) + 1
                continue

            # נמצא סיגנל — בדוק forward return
            fwd = _get_forward_return(sym, ts, forward_hours)
            if fwd is not None:
                signals.append({
                    "symbol": sym,
                    "ts":     ts,
                    "score":  result["score"],
                    "flow":   result["flow"],
                    "rvol":   result["rvol"],
                    "return": fwd,
                })
            time.sleep(0.1)

    return {"signals": signals, "filtered": filtered, "config": config}


def format_backtest_report(results: dict) -> str:
    signals  = results["signals"]
    filtered = results["filtered"]
    config   = results["config"]

    lines = [
        "📊 BACKTEST REPORT",
        f"Config: RVOL≥{config['rvol_threshold']} Flow≥{config['flow_threshold']} Score≥{config['score_threshold']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"סינון: rvol={filtered.get('rvol',0)} hard={filtered.get('hard',0)} "
        f"flow={filtered.get('flow',0)} score={filtered.get('score',0)}",
        f"סיגנלים שנמצאו: {len(signals)}",
    ]

    if not signals:
        lines.append("אין סיגנלים לניתוח.")
        return "\n".join(lines)

    returns   = [s["return"] for s in signals]
    wins      = sum(1 for r in returns if r > 0)
    win_rate  = wins / len(returns) * 100
    avg_ret   = np.mean(returns)
    avg_win   = np.mean([r for r in returns if r > 0]) if wins > 0 else 0
    avg_loss  = np.mean([r for r in returns if r <= 0]) if len(returns) > wins else 0
    pf        = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    lines += [
        "",
        f"Win Rate:       {win_rate:.0f}%",
        f"Avg Return:     {avg_ret:+.1f}%",
        f"Avg Win:        {avg_win:+.1f}%",
        f"Avg Loss:       {avg_loss:+.1f}%",
        f"Profit Factor:  {pf:.1f}x",
    ]

    # Top signals
    top = sorted(signals, key=lambda x: x["return"], reverse=True)[:3]
    lines += ["", "Top signals:"]
    for s in top:
        lines.append(f"  {s['symbol']} ret={s['return']:+.1f}% flow={s['flow']:.0f} score={s['score']:.0f}")

    return "\n".join(lines)


# ─── Compare Configs ──────────────────────────────────────────────────────────

def compare_configs(symbols: list[str]) -> str:
    """משווה בין קונפיגורציות שונות."""
    configs = [
        {"rvol_threshold": 0.5, "flow_threshold": 50, "score_threshold": 55, "label": "רגיש"},
        {"rvol_threshold": 0.8, "flow_threshold": 55, "score_threshold": 60, "label": "נוכחי"},
        {"rvol_threshold": 1.5, "flow_threshold": 60, "score_threshold": 65, "label": "מחמיר"},
    ]
    lines = ["🔬 CONFIG COMPARISON", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
             f"{'Config':<12} {'Signals':<10} {'WinRate':<10} {'AvgRet':<10} {'PF':<8}"]

    for cfg in configs:
        label = cfg.pop("label")
        r     = run_backtest(symbols[:10], hours_back=12, step_hours=3, config=cfg, forward_hours=6)
        sigs  = r["signals"]
        if not sigs:
            lines.append(f"{label:<12} {'0':<10} {'—':<10} {'—':<10} {'—':<8}")
            cfg["label"] = label
            continue
        rets     = [s["return"] for s in sigs]
        wins     = sum(1 for r in rets if r > 0)
        win_rate = wins / len(rets) * 100
        avg_ret  = np.mean(rets)
        avg_win  = np.mean([r for r in rets if r > 0]) if wins else 0
        avg_loss = np.mean([r for r in rets if r <= 0]) if len(rets) > wins else -0.01
        pf       = abs(avg_win / avg_loss)
        lines.append(f"{label:<12} {len(sigs):<10} {win_rate:<10.0f} {avg_ret:<+10.1f} {pf:<8.1f}")
        cfg["label"] = label

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT"])
    parser.add_argument("--hours",   type=int, default=24)
    parser.add_argument("--compare", action="store_true", help="השווה קונפיגורציות")
    parser.add_argument("--send",    action="store_true")
    args = parser.parse_args()

    if args.compare:
        report = compare_configs(args.symbols)
    else:
        results = run_backtest(args.symbols, hours_back=args.hours)
        report  = format_backtest_report(results)

    print(report)

    if args.send:
        import requests as req
        from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            req.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": report[:4096]}, timeout=10)
