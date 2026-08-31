"""
scanner/multiday_engine.py
Multi-Day Strategy Engine – Shadow/Research mode only.
Identifies EARLY/DEVELOPING setups on 1D/4H timeframes.
"""

import pandas as pd
from datetime import datetime, timezone
from typing import List, Dict, Optional

from scanner.market_data import get_candles
from scanner.dynamic_universe import build_dynamic_universe
from scanner.multiday_features import compute_all_features
from scanner.multiday_risk import build_risk_params
from utils.logger import get_logger
from storage.sqlite_db import get_conn

log = get_logger("multiday_engine")

# Minimum history requirements
MIN_1D_CANDLES = 60
MIN_4H_CANDLES = 30

# Timeframes
TIMEFRAME_1D = "1d"
TIMEFRAME_4H = "4h"


def ensure_multiday_table():
    """Create multiday_signals table if it doesn't exist."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS multiday_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                signal_timestamp TEXT NOT NULL,
                data_timestamp TEXT NOT NULL,
                price REAL,
                setup_type TEXT,
                stage TEXT,
                score REAL,
                entry REAL,
                stop REAL,
                tp1 REAL,
                tp2 REAL,
                strategy_type TEXT,
                strategy_version TEXT,
                mode TEXT,
                return_4h REAL,
                return_24h REAL,
                return_48h REAL,
                return_72h REAL,
                exhaustion_score REAL,
                trend_strength REAL,
                rs_1d REAL,
                volume_expansion REAL,
                distance_from_breakout REAL,
                pullback_depth REAL,
                mfe_24h REAL,
                mae_24h REAL,
                pnl_24h REAL,
                mfe_48h REAL,
                mae_48h REAL,
                pnl_48h REAL,
                mfe_72h REAL,
                mae_72h REAL,
                pnl_72h REAL,
                mfe_7d REAL,
                mae_7d REAL,
                pnl_7d REAL,
                outcome_type TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        log.debug("Multi-day table ensured")
    except Exception as e:
        log.error(f"Error creating multiday_signals table: {e}")


def get_btc_reference():
    """Fetch BTC 1D and 4H candles."""
    btc_1d = get_candles("BTCUSDT", TIMEFRAME_1D, limit=MIN_1D_CANDLES + 30)
    btc_4h = get_candles("BTCUSDT", TIMEFRAME_4H, limit=MIN_4H_CANDLES + 30)
    return btc_1d, btc_4h


def classify_stage(features: dict) -> str:
    """
    Classify as EARLY / DEVELOPING / LATE / EXHAUSTED.
    """
    exhaustion = features.get("exhaustion_score", 0)
    ret_24 = features.get("return_24h", 0)
    dist_breakout = features.get("distance_from_breakout", 0)
    rs_1d = features.get("rs_1d", 0)

    if exhaustion >= 70:
        return "EXHAUSTED"
    elif ret_24 > 10 or dist_breakout > 3:
        return "LATE"
    elif ret_24 > 3 or rs_1d > 5:
        return "DEVELOPING"
    else:
        return "EARLY"


def generate_signals(symbols: List[str], btc_1d: pd.DataFrame, btc_4h: pd.DataFrame) -> List[Dict]:
    """Generate Multi-Day signals for given universe."""
    signals = []
    now = datetime.now(timezone.utc)

    for symbol in symbols:
        try:
            # Fetch data
            df_1d = get_candles(symbol, TIMEFRAME_1D, limit=MIN_1D_CANDLES + 30)
            df_4h = get_candles(symbol, TIMEFRAME_4H, limit=MIN_4H_CANDLES + 30)

            if df_1d is None or df_4h is None:
                log.debug(f"{symbol}: missing data, skipping")
                continue

            if len(df_1d) < MIN_1D_CANDLES or len(df_4h) < MIN_4H_CANDLES:
                log.debug(f"{symbol}: insufficient history (1D={len(df_1d)}, 4H={len(df_4h)})")
                continue

            # Clean timestamps (ensure UTC and closed candles)
            df_1d = df_1d.copy()
            df_4h = df_4h.copy()
            df_1d["time"] = pd.to_datetime(df_1d["time"], utc=True)
            df_4h["time"] = pd.to_datetime(df_4h["time"], utc=True)

            # Ensure last candle is closed (not current incomplete)
            now_floor_1d = pd.Timestamp(now).floor('D')
            now_floor_4h = pd.Timestamp(now).floor('4h')

            # If last candle is not fully closed, drop it
            if df_1d["time"].iloc[-1] >= now_floor_1d:
                df_1d = df_1d.iloc[:-1]
            if df_4h["time"].iloc[-1] >= now_floor_4h:
                df_4h = df_4h.iloc[:-1]

            if len(df_1d) < MIN_1D_CANDLES or len(df_4h) < MIN_4H_CANDLES:
                continue

            # BTC alignment
            btc_1d_aligned = btc_1d[btc_1d["time"] <= now_floor_1d].tail(MIN_1D_CANDLES)
            btc_4h_aligned = btc_4h[btc_4h["time"] <= now_floor_4h].tail(MIN_4H_CANDLES)

            if len(btc_1d_aligned) < MIN_1D_CANDLES or len(btc_4h_aligned) < MIN_4H_CANDLES:
                continue

            # Compute features
            features = compute_all_features(
                df_1d.tail(MIN_1D_CANDLES),
                df_4h.tail(MIN_4H_CANDLES),
                btc_1d_aligned,
                btc_4h_aligned
            )

            # Skip low-quality data
            if features.get("data_quality", 0) < 0.5:
                continue

            # Classify setup type
            last_price = df_4h["close"].iloc[-1]
            ret_24 = features.get("return_24h", 0)
            rs_1d = features.get("rs_1d", 0)
            vol_exp = features.get("volume_expansion", 0)
            dist_breakout = features.get("distance_from_breakout", 0)

            # Determine setup
            if ret_24 < 5 and dist_breakout < 1 and vol_exp > 0.2:
                setup_type = "BREAKOUT"
            elif ret_24 < 10 and rs_1d > 3 and features.get("pullback_depth", 0) > 3:
                setup_type = "PULLBACK"
            else:
                setup_type = "UNKNOWN"

            if setup_type == "UNKNOWN":
                continue

            # Build risk params
            risk = build_risk_params(features, setup_type, last_price)

            # Skip if R:R < 1.5
            if risk["risk_reward"] < 1.5:
                continue

            # Stage
            stage = classify_stage(features)

            # Score (simple weighted average)
            score = (
                features.get("trend_strength", 0) * 20 +
                features.get("rs_1d", 0) / 10 * 15 +
                features.get("volume_expansion", 0) * 30 +
                (1 - features.get("exhaustion_score", 0) / 100) * 20 +
                (risk["risk_reward"] / 3) * 15
            )
            score = max(0, min(100, score))

            if score < 50:
                continue

            # Build signal
            signal = {
                "symbol": symbol,
                "timestamp": now.isoformat(),
                "data_timestamp": df_4h["time"].iloc[-1].isoformat(),
                "price": last_price,
                "setup_type": setup_type,
                "stage": stage,
                "score": round(score, 1),
                "features": features,
                "risk": risk,
                "entry": risk["entry"],
                "stop": risk["stop"],
                "tp1": risk["tp1"],
                "tp2": risk["tp2"],
                "strategy_type": "MULTIDAY",
                "strategy_version": "1.0",
                "mode": "SHADOW",
                "return_4h": features.get("return_4h", 0),
                "return_24h": features.get("return_24h", 0),
                "return_48h": features.get("return_48h", 0),
                "return_72h": features.get("return_72h", 0),
                "exhaustion_score": features.get("exhaustion_score", 0),
            }
            signals.append(signal)

        except Exception as e:
            log.error(f"Error processing {symbol}: {e}")

    return signals


def run_multiday_scan():
    """Main entry point for Multi-Day scanner."""
    log.info("Multi-Day scan started")

    # Ensure table exists before anything else
    ensure_multiday_table()

    # Build universe (use same dynamic universe as Intraday)
    symbols = build_dynamic_universe()
    if not symbols:
        log.warning("No universe available for Multi-Day scan")
        return []

    # BTC reference
    btc_1d, btc_4h = get_btc_reference()
    if btc_1d is None or btc_4h is None:
        log.error("BTC data not available – skipping Multi-Day scan")
        return []

    # Generate signals
    signals = generate_signals(symbols, btc_1d, btc_4h)

    log.info(f"Multi-Day scan complete: {len(signals)} signals generated")

    # Save to database (if signals exist)
    if signals:
        save_multiday_signals(signals)

    return signals


def save_multiday_signals(signals: List[Dict]):
    """Save signals to multiday_signals table."""
    conn = get_conn()
    cur = conn.cursor()

    # Ensure table exists before saving
    ensure_multiday_table()

    for signal in signals:
        # Flatten features into columns
        f = signal["features"]
        r = signal["risk"]
        cur.execute("""
            INSERT INTO multiday_signals (
                symbol, signal_timestamp, data_timestamp, price, setup_type, stage, score,
                entry, stop, tp1, tp2, strategy_type, strategy_version, mode,
                return_4h, return_24h, return_48h, return_72h, exhaustion_score,
                trend_strength, rs_1d, volume_expansion, distance_from_breakout, pullback_depth,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal["symbol"],
            signal["timestamp"],
            signal["data_timestamp"],
            signal["price"],
            signal["setup_type"],
            signal["stage"],
            signal["score"],
            r["entry"],
            r["stop"],
            r["tp1"],
            r["tp2"],
            signal["strategy_type"],
            signal["strategy_version"],
            signal["mode"],
            signal["return_4h"],
            signal["return_24h"],
            signal["return_48h"],
            signal["return_72h"],
            signal["exhaustion_score"],
            f.get("trend_strength", 0),
            f.get("rs_1d", 0),
            f.get("volume_expansion", 0),
            f.get("distance_from_breakout", 0),
            f.get("pullback_depth", 0),
            signal["timestamp"]
        ))

    conn.commit()
    conn.close()
    log.info(f"Saved {len(signals)} signals to multiday_signals")
