"""
CRYPTO-BOT Elite — Exit Simulator v3.0
Single Source of Truth for Exit Logic.
Mirrors scanner/trade_manager.py state machine.

Key fixes (v2 → v3):
  - FIX: TP2 sells 20% of REMAINING position (16% of original) — matches Trade Manager
  - FIX: All exit events include exit_price, qty, bar_time, cumulative_pnl, sl_type
  - FIX: TIMEOUT branch in else-block does not fire based on stale data
  - FIX: SL updates cannot go above current close
  - FIX: TP1 and TP2 cannot trigger on the same bar (conservative rule)
  - FIX: Entry bar with mid-bar entry skips its high/low extremes (avoids look-ahead)
  - FIX: realized_pnl (partial sells) returned separately from final leg
  - ADD: fee_pct and slippage_pct are applied as round-trip pct costs
  - ADD: MFE/MAE exclude entry bar if entry is mid-bar
  - ADD: sl_type_at_exit (INITIAL / BREAKEVEN / TRAILING)
"""
import pandas as pd
from utils.logger import get_logger

log = get_logger("exit_simulator")

try:
    from scanner.exit_engine import update_trailing_stop_atr
except ImportError:
    update_trailing_stop_atr = None

# Candle bar duration (matches candle_cache)
BAR_DURATION_MIN = 5

# TP1 and TP2 sell ratios (of CURRENT position)
TP1_SELL_RATIO = 0.2      # sells 20% of original (position was 1.0)
TP2_SELL_RATIO = 0.2      # sells 20% of REMAINING (= 16% of original)


def _classify_sl_type(current_sl, entry_price, tp1_hit):
    """Determine which kind of stop triggered."""
    if entry_price <= 0:
        return "INITIAL"
    if current_sl >= entry_price * 1.001:
        return "TRAILING"
    if tp1_hit and abs(current_sl - entry_price) / entry_price < 0.001:
        return "BREAKEVEN"
    return "INITIAL"


def simulate_trade_path(df, entry_price, sl, tp1, tp2, entry_ts, now_ts,
                        timeout_hours=48, fee_pct=0.0, slippage_pct=0.0):
    """
    Simulate trade path. Mirrors Trade Manager.

    Rules:
      - Entry: 100% at entry_price, initial SL
      - TP1: sell TP1_SELL_RATIO of CURRENT position, move SL to entry
      - TP2: sell TP2_SELL_RATIO of REMAINING position, enter runner mode
      - After TP1: trailing stop active
      - After TP2: tighter trailing stop
      - SL priority over TP on ambiguous bar
      - TP1 and TP2 cannot trigger on the same bar (conservative)
      - TIMEOUT only fires when we have bar data at/past timeout
      - SL cannot be set above current close
      - Entry bar with mid-bar entry: skip its high/low extremes

    Returns dict with:
        pnl_pct (gross), pnl_pct_net,
        realized_pnl_partial (TP1+TP2 only),
        exit_events (list of dicts),
        ambiguous_bar, entry_bar_ambiguous,
        mfe_pct, mae_pct, is_closed,
        final_exit_price, final_exit_time,
        sl_type_at_exit, state
    """
    empty_result = {
        "pnl_pct": 0.0, "pnl_pct_net": 0.0, "realized_pnl_partial": 0.0,
        "exit_events": [], "ambiguous_bar": 0, "entry_bar_ambiguous": 0,
        "mfe_pct": 0.0, "mae_pct": 0.0, "is_closed": False,
        "final_exit_price": None, "final_exit_time": None,
        "sl_type_at_exit": "N/A", "state": "ACTIVE",
    }

    if df is None or df.empty:
        return empty_result

    if entry_price <= 0:
        log.warning(f"simulate_trade_path: invalid entry_price={entry_price}")
        return empty_result

    df = df.sort_values("time").reset_index(drop=True)

    # ── Entry bar ambiguity detection ────────────────────────
    # If first bar time is within BAR_DURATION_MIN of entry_ts,
    # its high/low may reflect prices before entry → skip extremes.
    first_bar_time = df.iloc[0]["time"]
    try:
        gap_min = abs((first_bar_time - entry_ts).total_seconds()) / 60.0
    except Exception:
        gap_min = 999.0
    entry_bar_ambiguous = 1 if gap_min < BAR_DURATION_MIN else 0

    # ── State ─────────────────────────────────────────────────
    position = 1.0
    current_sl = sl
    state = "ACTIVE"
    tp1_done = False
    tp2_done = False

    realized_pnl_weighted = 0.0    # total (partial + final)
    realized_pnl_partial = 0.0     # TP1 + TP2 only

    highest_since_entry = entry_price
    lowest_since_entry = entry_price

    ambiguous_bar = 0
    exit_events = []
    is_closed = False
    final_exit_price = None
    final_exit_time = None
    sl_type_at_exit = "N/A"

    for idx, bar in df.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        bar_time = bar["time"]

        is_entry_bar = (idx == 0 and entry_bar_ambiguous == 1)

        # ── Update MFE/MAE (skip ambiguous entry bar) ────────
        if not is_entry_bar:
            if high > highest_since_entry:
                highest_since_entry = high
            if low < lowest_since_entry:
                lowest_since_entry = low

        # ── Exit checks (skip ambiguous entry bar) ────────────
        if not is_entry_bar:
            hit_sl_now = current_sl > 0 and low <= current_sl
            hit_tp1_now = (not tp1_done) and tp1 > 0 and high >= tp1
            hit_tp2_now = tp1_done and (not tp2_done) and tp2 > 0 and high >= tp2

            # Ambiguity: both SL and TP on same bar → SL wins
            if hit_sl_now and (hit_tp1_now or hit_tp2_now):
                ambiguous_bar = 1
                hit_tp1_now = False
                hit_tp2_now = False

            # ── SL ──────────────────────────────────────────
            if hit_sl_now:
                sl_pct = (current_sl - entry_price) / entry_price * 100
                realized_pnl_weighted += sl_pct * position
                exit_events.append({
                    "type": "SL",
                    "pct": round(sl_pct, 4),
                    "qty": round(position, 6),
                    "time": bar_time,
                    "price": round(current_sl, 8),
                    "sl_type": _classify_sl_type(current_sl, entry_price, tp1_done),
                    "cumulative_pnl": round(realized_pnl_weighted, 4),
                })
                final_exit_price = current_sl
                final_exit_time = bar_time
                sl_type_at_exit = _classify_sl_type(current_sl, entry_price, tp1_done)
                position = 0.0
                state = "CLOSED"
                is_closed = True
                break

            # ── TP1 ─────────────────────────────────────────
            if hit_tp1_now:
                qty_sold = position * TP1_SELL_RATIO
                tp1_pct = (tp1 - entry_price) / entry_price * 100
                leg_pnl = tp1_pct * qty_sold
                realized_pnl_weighted += leg_pnl
                realized_pnl_partial += leg_pnl
                exit_events.append({
                    "type": "TP1",
                    "pct": round(tp1_pct, 4),
                    "qty": round(qty_sold, 6),
                    "time": bar_time,
                    "price": round(tp1, 8),
                    "sl_type": "BREAKEVEN",
                    "cumulative_pnl": round(realized_pnl_weighted, 4),
                })
                position -= qty_sold
                tp1_done = True
                current_sl = entry_price
                state = "BREAKEVEN"

            # ── TP2 (only if TP1 was hit on a PREVIOUS bar) ──
            if hit_tp2_now:
                qty_sold = position * TP2_SELL_RATIO   # 20% of REMAINING
                tp2_pct = (tp2 - entry_price) / entry_price * 100
                leg_pnl = tp2_pct * qty_sold
                realized_pnl_weighted += leg_pnl
                realized_pnl_partial += leg_pnl
                exit_events.append({
                    "type": "TP2",
                    "pct": round(tp2_pct, 4),
                    "qty": round(qty_sold, 6),
                    "time": bar_time,
                    "price": round(tp2, 8),
                    "sl_type": "TRAILING",
                    "cumulative_pnl": round(realized_pnl_weighted, 4),
                })
                position -= qty_sold
                tp2_done = True
                state = "RUNNER"

        # ── Trailing stop update (for NEXT bar) ───────────────
        current_pnl_pct = (close - entry_price) / entry_price * 100
        atr_multiplier = 3.0
        if state in ("TP2_HIT", "RUNNER"):
            atr_multiplier = 1.5
        elif state == "BREAKEVEN":
            atr_multiplier = 1.8
        elif tp1_done:
            atr_multiplier = 2.5
        elif current_pnl_pct >= 20:
            atr_multiplier = 1.5
        elif current_pnl_pct >= 10:
            atr_multiplier = 2.0

        if update_trailing_stop_atr is not None and idx >= 15:
            df_window = df.iloc[max(0, idx - 15): idx + 1]
            new_sl = update_trailing_stop_atr(df_window, current_sl, atr_multiplier)
            if new_sl and new_sl > current_sl and new_sl < close:
                current_sl = new_sl
        elif state == "RUNNER":
            trail_level = highest_since_entry * (1 - (atr_multiplier * 0.01))
            if trail_level > current_sl and trail_level < close:
                current_sl = trail_level

        # ── TIMEOUT (bar-based, definite) ────────────────────
        hours_elapsed = (bar_time - entry_ts).total_seconds() / 3600
        if hours_elapsed >= timeout_hours:
            timeout_pct = (close - entry_price) / entry_price * 100
            realized_pnl_weighted += timeout_pct * position
            exit_events.append({
                "type": "TIMEOUT",
                "pct": round(timeout_pct, 4),
                "qty": round(position, 6),
                "time": bar_time,
                "price": round(close, 8),
                "sl_type": "N/A",
                "cumulative_pnl": round(realized_pnl_weighted, 4),
            })
            final_exit_price = close
            final_exit_time = bar_time
            position = 0.0
            state = "CLOSED"
            is_closed = True
            break

    # ── Post-loop: still open? ───────────────────────────────
    else:
        if position > 0:
            last_bar_time = df.iloc[-1]["time"]
            last_close = float(df.iloc[-1]["close"])
            unrealized_pct = (last_close - entry_price) / entry_price * 100
            hours_since_entry = (last_bar_time - entry_ts).total_seconds() / 3600

            # Only close if we have data PAST timeout — otherwise stale
            if hours_since_entry >= timeout_hours:
                realized_pnl_weighted += unrealized_pct * position
                exit_events.append({
                    "type": "TIMEOUT",
                    "pct": round(unrealized_pct, 4),
                    "qty": round(position, 6),
                    "time": last_bar_time,
                    "price": round(last_close, 8),
                    "sl_type": "N/A",
                    "cumulative_pnl": round(realized_pnl_weighted, 4),
                })
                final_exit_price = last_close
                final_exit_time = last_bar_time
                position = 0.0
                state = "CLOSED"
                is_closed = True
            else:
                exit_events.append({
                    "type": "STILL_OPEN",
                    "pct": round(unrealized_pct, 4),
                    "qty": round(position, 6),
                    "time": last_bar_time,
                    "price": round(last_close, 8),
                    "sl_type": "N/A",
                    "cumulative_pnl": round(
                        realized_pnl_weighted + unrealized_pct * position, 4
                    ),
                })
                final_exit_price = last_close
                final_exit_time = last_bar_time
                is_closed = False

    # ── MFE / MAE ────────────────────────────────────────────
    mfe_pct = (highest_since_entry - entry_price) / entry_price * 100
    mae_pct = (lowest_since_entry - entry_price) / entry_price * 100

    # ── Costs (round-trip, pct of original notional) ─────────
    total_cost_pct = float(fee_pct or 0.0) + float(slippage_pct or 0.0)
    pnl_pct_net = realized_pnl_weighted - total_cost_pct

    return {
        "pnl_pct": round(realized_pnl_weighted, 4),
        "pnl_pct_net": round(pnl_pct_net, 4),
        "realized_pnl_partial": round(realized_pnl_partial, 4),
        "exit_events": exit_events,
        "ambiguous_bar": ambiguous_bar,
        "entry_bar_ambiguous": entry_bar_ambiguous,
        "mfe_pct": round(mfe_pct, 4),
        "mae_pct": round(mae_pct, 4),
        "is_closed": is_closed,
        "final_exit_price": round(final_exit_price, 8) if final_exit_price is not None else None,
        "final_exit_time": final_exit_time,
        "sl_type_at_exit": sl_type_at_exit,
        "state": state,
    }
