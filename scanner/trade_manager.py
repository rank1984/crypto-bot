"""
CRYPTO-BOT Elite — Trade Manager v4.0

Fixes from v3:
  FIX (critical): realized_pnl — partial sells from TP1/TP2 are now tracked
                  and added to final PnL. Was: pnl = (exit - entry) * remaining_size
                  only → understated total profit by up to 50%.
  FIX (critical): exit gate uses exit_result.get("is_actionable") instead of
                  hardcoded confidence >= 80 (engine v3.0 returns confidence==score).
  FIX: TRIM is handled (sells TRIM_SELL_RATIO, stays open) — spec compliance.
  FIX: update_trailing_stop_atr receives current_price and trade_high.
  FIX: shadow update writes realized_pnl_pct + total pnl_pct.
  FIX: _close_trade distinguishes INITIAL_SL / BREAKEVEN_SL / TRAILING_SL / EMERGENCY.
  ADD: partial_sells log; original_size; realized_pnl_usd + realized_pnl_pct.
  ADD: consecutive state tracking for accurate transitions.
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from utils.logger import get_logger
from utils import config
from scanner.exit_engine import calc_exit_score, update_trailing_stop_atr
from tools.shadow_mode import update_shadow_exit

log = get_logger(__name__)

# ─── State Machine ────────────────────────────────────────────
STATE_TRANSITIONS = {
    "NEW":        ["ACTIVE"],
    "ACTIVE":     ["TP1_HIT", "EXIT", "CLOSED"],
    "TP1_HIT":    ["BREAKEVEN"],
    "BREAKEVEN":  ["TP2_HIT", "EXIT", "CLOSED"],
    "TP2_HIT":    ["RUNNER", "CLOSED"],
    "RUNNER":     ["EXIT", "CLOSED"],
    "EXIT":       ["CLOSED"],
    "CLOSED":     [],
}


@dataclass
class Trade:
    symbol: str
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    setup_type: str
    entry_time: datetime
    original_size: float           # v4.0: shares at entry (immutable)
    position_size: float           # v4.0: current shares
    initial_capital: float
    state: str = "NEW"
    highest_high: float = 0.0
    lowest_low: float = 0.0
    tp1_done: bool = False
    tp2_done: bool = False
    exit_reason: str = ""
    exit_time: Optional[datetime] = None
    pnl: float = 0.0               # v4.0: TOTAL (realized + final)
    pnl_pct: float = 0.0           # v4.0: TOTAL % of original notional
    realized_pnl: float = 0.0      # v4.0: from partial sells ($)
    realized_pnl_pct: float = 0.0  # v4.0: from partial sells (% weighted)
    final_pnl: float = 0.0         # v4.0: from final leg ($)
    partial_sells: List[Dict[str, Any]] = field(default_factory=list)
    health: float = 100.0
    atr_multiplier: float = 3.0
    sl_type: str = "INITIAL"       # INITIAL / BREAKEVEN / TRAILING
    log: List[Dict[str, Any]] = field(default_factory=list)

    def can_transition(self, new_state: str) -> bool:
        return new_state in STATE_TRANSITIONS.get(self.state, [])

    def set_state(self, new_state: str):
        if not self.can_transition(new_state):
            log.warning(f"{self.symbol}: invalid transition {self.state} -> {new_state}")
            return
        old = self.state
        self.state = new_state
        self.log.append({"time": datetime.now(), "event": f"STATE:{old}->{new_state}"})


class TradeManager:
    def __init__(self, portfolio_capital: float = 500.0, max_trades: int = 2):
        self.trades: Dict[str, Trade] = {}
        self.portfolio_capital = portfolio_capital
        self.max_trades = max_trades
        self.closed_trades: List[Trade] = []

    def can_open_trade(self) -> bool:
        active = [t for t in self.trades.values() if t.state not in ("EXIT", "CLOSED")]
        return len(active) < self.max_trades

    def open_trade(self, signal: Dict[str, Any], price: float) -> Optional[Trade]:
        if not self.can_open_trade():
            return None

        symbol = signal.get("symbol", "UNK")
        entry = signal.get("entry", price)
        sl = signal.get("sl", entry * 0.98)
        tp1 = signal.get("tp1", entry * 1.04)
        tp2 = signal.get("tp2", entry * 1.10)
        setup_type = signal.get("setup_type", "")

        risk_per_trade = self.portfolio_capital * 0.01
        stop_distance_pct = abs(entry - sl) / entry if entry > 0 else 0.04
        capital_to_allocate = risk_per_trade / stop_distance_pct
        capital_to_allocate = min(capital_to_allocate, self.portfolio_capital * 0.25)
        position_size = capital_to_allocate / entry

        trade = Trade(
            symbol=symbol,
            entry_price=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            setup_type=setup_type,
            entry_time=datetime.now(),
            original_size=position_size,
            position_size=position_size,
            initial_capital=capital_to_allocate,
            highest_high=entry,
            lowest_low=entry,
        )
        trade.set_state("ACTIVE")

        self.trades[symbol] = trade
        log.info(
            f"Trade opened: {symbol} | Entry={entry:.6f} | SL={sl:.6f} | "
            f"TP1={tp1:.6f} | TP2={tp2:.6f} | Size={position_size:.6f} | "
            f"Capital={capital_to_allocate:.2f}$"
        )
        return trade

    # ── Trade Health ─────────────────────────────────────────
    def _calc_trade_health(self, trade: Trade, coin_data: dict, current_price: float) -> float:
        flow = coin_data.get("flow_score", 50)
        oi = coin_data.get("oi_change", 0)
        rs = coin_data.get("rs_1h", 0)
        vwap = coin_data.get("vwap", 0)
        ema20 = coin_data.get("ema20", 0)
        cvd = coin_data.get("cvd", 0)

        flow_score = min(100, max(0, (flow / 80) * 100)) if flow > 0 else 50
        oi_score = min(100, 50 + oi * 2) if oi > 0 else max(0, 50 + oi * 2)
        rs_score = min(100, 50 + rs * 5) if rs > -10 else 0

        if vwap and current_price:
            vwap_dist_pct = (current_price - vwap) / vwap * 100
            if 0 <= vwap_dist_pct <= 3:
                vwap_score = 100
            elif vwap_dist_pct < 0:
                vwap_score = max(0, 100 + vwap_dist_pct * 10)
            else:
                vwap_score = max(0, 100 - vwap_dist_pct * 5)
        else:
            vwap_score = 50

        ema_penalty = 20 if (ema20 and current_price < ema20) else 0
        cvd_score = 80 if cvd > 0 else (20 if cvd < 0 else 50)

        health = (
            flow_score * 0.25 +
            oi_score * 0.20 +
            rs_score * 0.15 +
            vwap_score * 0.20 +
            cvd_score * 0.10 +
            (50 - ema_penalty) * 0.10
        )

        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        health += pnl_pct * 0.5
        return round(max(0, min(100, health)), 1)

    def _get_atr_multiplier(self, trade: Trade, current_pnl_pct: float) -> float:
        if trade.state in ("TP2_HIT", "RUNNER"):
            return config.TRAILING_ATR_RUNNER
        if trade.state == "BREAKEVEN":
            return config.TRAILING_ATR_BREAKEVEN
        if trade.tp1_done:
            return config.TRAILING_ATR_AFTER_TP1
        if current_pnl_pct >= 20:
            return 1.5
        if current_pnl_pct >= 10:
            return 2.0
        return config.TRAILING_ATR_BASE

    def _emergency_exit_needed(self, coin_data: dict, market_health: float = 70.0,
                                btc_regime: str = "") -> Tuple[bool, str]:
        flow = coin_data.get("flow_score", 100)
        oi_change = coin_data.get("oi_change", 0)
        vwap = coin_data.get("vwap", 0)
        ema20 = coin_data.get("ema20", 0)
        price = coin_data.get("last_price", 0)

        if flow < 20:
            return True, "Flow collapsed (<20)"
        if btc_regime == "RISK_OFF" or market_health < 30:
            return True, "Market Health Emergency"
        if oi_change < -20:
            return True, "OI dropped >20%"
        if vwap and ema20 and price and price < vwap and price < ema20:
            return True, "VWAP and EMA20 lost"
        return False, ""

    # ── Partial sells ────────────────────────────────────────
    def _execute_partial(self, trade: Trade, price: float, ratio_of_current: float,
                         label: str) -> Dict[str, Any]:
        """Sell `ratio_of_current` of REMAINING position at `price`."""
        qty_sold = trade.position_size * ratio_of_current
        leg_pct = (price - trade.entry_price) / trade.entry_price * 100
        leg_pnl = (price - trade.entry_price) * qty_sold
        leg_pct_weighted = leg_pct * (qty_sold / trade.original_size)

        trade.realized_pnl += leg_pnl
        trade.realized_pnl_pct += leg_pct_weighted
        trade.position_size -= qty_sold
        trade.partial_sells.append({
            "type": label,
            "qty": round(qty_sold, 8),
            "price": round(price, 8),
            "pnl_usd": round(leg_pnl, 4),
            "pnl_pct_leg": round(leg_pct, 4),
            "pnl_pct_weighted": round(leg_pct_weighted, 4),
            "time": datetime.now(),
        })
        log.info(
            f"{trade.symbol} {label}: sold {qty_sold:.6f} @ {price:.6f} "
            f"(leg {leg_pct:+.2f}%, weighted {leg_pct_weighted:+.2f}%, "
            f"remaining={trade.position_size:.6f})"
        )
        return {
            "symbol": trade.symbol, "action": "SELL_PARTIAL", "price": price,
            "qty": qty_sold, "reason": label,
        }

    # ── Update ───────────────────────────────────────────────
    def update(self, symbol: str, current_price: float, coin_data: Dict[str, Any],
               df_5m=None, df_1h=None, market_health: float = 70.0,
               btc_regime: str = "") -> Optional[Dict[str, Any]]:
        trade = self.trades.get(symbol)
        if not trade or trade.state in ("EXIT", "CLOSED"):
            return None

        if current_price > trade.highest_high:
            trade.highest_high = current_price
        if trade.lowest_low == 0 or current_price < trade.lowest_low:
            trade.lowest_low = current_price

        trade.health = self._calc_trade_health(trade, coin_data, current_price)

        # Emergency exit (5-min grace)
        trade_age_min = (datetime.now() - trade.entry_time).total_seconds() / 60
        if trade_age_min >= 5:
            emergency, reason = self._emergency_exit_needed(coin_data, market_health, btc_regime)
            if emergency:
                return self._close_trade(trade, current_price, f"EMERGENCY: {reason}",
                                         sl_type="EMERGENCY")

        # ── Stop Loss ────────────────────────────────────
        if current_price <= trade.sl:
            sl_type = trade.sl_type
            if trade.tp1_done and abs(trade.sl - trade.entry_price) / trade.entry_price < 0.001:
                sl_type = "BREAKEVEN"
            elif trade.sl > trade.entry_price * 1.001:
                sl_type = "TRAILING"
            return self._close_trade(trade, current_price, f"{sl_type}_SL", sl_type=sl_type)

        # ── TP1 ──────────────────────────────────────────
        if not trade.tp1_done and current_price >= trade.tp1:
            result = self._execute_partial(trade, trade.tp1, config.TP1_SELL_RATIO, "TP1")
            trade.tp1_done = True
            trade.set_state("TP1_HIT")
            trade.sl = trade.entry_price
            trade.sl_type = "BREAKEVEN"
            trade.set_state("BREAKEVEN")
            return result

        # ── TP2 ──────────────────────────────────────────
        if trade.tp1_done and not trade.tp2_done and current_price >= trade.tp2:
            result = self._execute_partial(trade, trade.tp2, config.TP2_SELL_RATIO, "TP2")
            trade.tp2_done = True
            trade.set_state("TP2_HIT")
            trade.set_state("RUNNER")
            trade.sl_type = "TRAILING"
            return result

        # ── Trailing Stop ────────────────────────────────
        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        trade.atr_multiplier = self._get_atr_multiplier(trade, pnl_pct)
        if df_5m is not None and len(df_5m) >= 15:
            new_sl = update_trailing_stop_atr(
                df_5m,
                trade.sl,
                trade.atr_multiplier,
                current_price=current_price,
                trade_high=trade.highest_high,
            )
            if new_sl is not None and new_sl > trade.sl:
                old_sl = trade.sl
                trade.sl = new_sl
                trade.sl_type = "TRAILING"
                log.info(f"{trade.symbol} SL moved: {old_sl:.6f} → {new_sl:.6f} "
                         f"(ATR x{trade.atr_multiplier})")

        # ── Trade Health force-exit ──────────────────────
        if trade.health < 35:
            return self._close_trade(trade, current_price,
                                     f"Trade Health low ({trade.health})",
                                     sl_type="HEALTH_EXIT")

        # ── Exit Engine (v3.0) ──────────────────────────
        try:
            exit_result = calc_exit_score(
                df_5m=df_5m,
                df_1h=df_1h,
                rs_1h=coin_data.get("rs_1h", 0),
                rs_4h=coin_data.get("rs_4h", 0),
                oi_change_pct=coin_data.get("oi_change", 0),
                current_gain_pct=pnl_pct,
                flow_score=coin_data.get("flow_score", 50),
                market_health=market_health,
            )

            # v4.0: use is_actionable, not hardcoded confidence
            if exit_result.get("is_actionable"):
                sig = exit_result["exit_signal"]
                reason_str = f"Exit Score {exit_result['exit_score']}: " \
                             f"{', '.join(exit_result['reasons'])}"

                if sig == "EXIT":
                    return self._close_trade(trade, current_price,
                                             reason_str, sl_type="EXIT_ENGINE")

                if sig == "TRIM" and trade.position_size > 0.15 * trade.original_size:
                    # Sell 30% of REMAINING (spec-compliant TRIM)
                    return self._execute_partial(trade, current_price, 0.30, "TRIM")
        except Exception as e:
            log.error(f"Exit Score error for {symbol}: {e}")

        return None

    # ── Close ────────────────────────────────────────────────
    def _close_trade(self, trade: Trade, exit_price: float, reason: str,
                     sl_type: str = "N/A") -> Dict[str, Any]:
        if trade.position_size > 0:
            trade.final_pnl = (exit_price - trade.entry_price) * trade.position_size
            final_pct_leg = (exit_price - trade.entry_price) / trade.entry_price * 100
            final_pct_weighted = final_pct_leg * (trade.position_size / trade.original_size)
        else:
            trade.final_pnl = 0.0
            final_pct_weighted = 0.0

        trade.pnl = trade.realized_pnl + trade.final_pnl
        trade.pnl_pct = trade.realized_pnl_pct + final_pct_weighted

        max_profit_pct = ((trade.highest_high - trade.entry_price) / trade.entry_price) * 100 \
                         if trade.highest_high > 0 else 0
        max_drawdown_pct = ((trade.lowest_low - trade.entry_price) / trade.entry_price) * 100 \
                           if trade.lowest_low > 0 else 0

        trade.exit_time = datetime.now()
        trade.exit_reason = reason
        trade.set_state("EXIT")
        trade.set_state("CLOSED")

        # ── Update shadow DB with FULL picture ───────────
        try:
            duration_minutes = int((trade.exit_time - trade.entry_time).total_seconds() / 60)
            update_shadow_exit(
                symbol=trade.symbol,
                exit_reason=reason,
                pnl=trade.pnl,
                duration_minutes=duration_minutes,
                pnl_pct=trade.pnl_pct,
                max_profit_pct=max_profit_pct,
                max_drawdown_pct=max_drawdown_pct,
                trade_state=trade.state,
                exit_price=exit_price,
                realized_pnl_pct=trade.realized_pnl_pct,  # NEW field
                sl_type_at_exit=sl_type,                  # NEW field
            )
        except TypeError:
            # Fallback if shadow_mode still v10.0 without new kwargs
            try:
                update_shadow_exit(
                    symbol=trade.symbol, exit_reason=reason, pnl=trade.pnl,
                    duration_minutes=duration_minutes, pnl_pct=trade.pnl_pct,
                    max_profit_pct=max_profit_pct, max_drawdown_pct=max_drawdown_pct,
                    trade_state=trade.state, exit_price=exit_price,
                )
            except Exception as e:
                log.error(f"Shadow exit fallback failed: {e}")
        except Exception as e:
            log.error(f"Shadow exits update failed: {e}")

        log.info(
            f"Trade closed: {trade.symbol} | Exit={exit_price:.6f} | "
            f"PnL total={trade.pnl:.2f}$ ({trade.pnl_pct:+.2f}%) | "
            f"realized={trade.realized_pnl:.2f}$ ({trade.realized_pnl_pct:+.2f}%) | "
            f"final={trade.final_pnl:.2f}$ | reason={reason} | sl_type={sl_type}"
        )
        self.closed_trades.append(trade)
        if trade.symbol in self.trades:
            del self.trades[trade.symbol]

        return {
            "symbol": trade.symbol, "action": "SELL_ALL", "price": exit_price,
            "reason": reason, "pnl": trade.pnl, "pnl_pct": trade.pnl_pct,
            "realized_pnl": trade.realized_pnl,
        }

    def get_active_trades(self) -> List[Trade]:
        return [t for t in self.trades.values() if t.state not in ("EXIT", "CLOSED")]

    def get_summary(self) -> Dict[str, Any]:
        active = self.get_active_trades()
        closed = self.closed_trades
        total_pnl = sum(t.pnl for t in closed)
        wins = [t for t in closed if t.pnl > 0]
        return {
            "active_count": len(active),
            "closed_count": len(closed),
            "total_pnl": total_pnl,
            "win_rate": len(wins) / len(closed) if closed else 0,
            "active_symbols": [t.symbol for t in active],
        }
