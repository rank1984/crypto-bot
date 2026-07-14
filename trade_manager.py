"""
CRYPTO-BOT Elite — Trade Manager (v2)

- Trade State Machine
- Trade Health Score
- Exit Confidence integration
- Better logging & Telegram
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from utils.logger import get_logger
from scanner.exit_engine import calc_exit_score

log = get_logger(__name__)

# ─── Trade State Machine ──────────────────────────────────────────────────────
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
    position_size: float
    initial_capital: float
    state: str = "NEW"                     # NEW, ACTIVE, TP1_HIT, BREAKEVEN, TP2_HIT, RUNNER, EXIT, CLOSED
    highest_high: float = 0.0
    tp1_done: bool = False
    tp2_done: bool = False
    exit_reason: str = ""
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    health: float = 0.0                   # 0-100
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
        log.info(f"{self.symbol} | State: {old} → {new_state}")


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
            log.warning("Max trades reached")
            return None

        symbol = signal.get("symbol", "UNK")
        entry = signal.get("entry", price)
        sl = signal.get("sl", entry * 0.98)
        tp1 = signal.get("tp1", entry * 1.04)
        tp2 = signal.get("tp2", entry * 1.10)
        setup_type = signal.get("setup_type", "")

        # Risk-based position sizing (1% risk, dynamic stop distance)
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
            position_size=position_size,
            initial_capital=capital_to_allocate,
            highest_high=entry,
        )
        trade.set_state("NEW")
        trade.set_state("ACTIVE")   # immediately active

        self.trades[symbol] = trade
        log.info(
            f"Trade opened: {symbol} | Entry={entry:.4f} | SL={sl:.4f} | "
            f"TP1={tp1:.4f} | TP2={tp2:.4f} | Size={position_size:.4f} | "
            f"Capital={capital_to_allocate:.2f}$"
        )
        trade.log.append({"time": datetime.now(), "event": "OPEN", "price": entry})
        return trade

    def _calc_trade_health(self, trade: Trade, coin_data: dict, current_price: float) -> float:
        """
        Trade Health 0-100:
        - Flow Score (40%): current flow / max typical (80)
        - OI Change (25%): positive/negative
        - RS vs BTC (20%): rs_1h
        - Distance from VWAP (15%): closer to VWAP = better
        """
        flow = coin_data.get("flow_score", 50)
        oi = coin_data.get("oi_change", 0)
        rs = coin_data.get("rs_1h", 0)
        vwap = coin_data.get("vwap", 0)
        price = current_price

        # Flow (0-100)
        flow_score = min(100, max(0, (flow / 80) * 100)) if flow > 0 else 50

        # OI (positive = good, negative = penalty)
        if oi > 0:
            oi_score = min(100, 50 + oi * 2)  # +2% -> 54, +10% -> 70
        else:
            oi_score = max(0, 50 + oi * 2)   # -5% -> 40

        # RS (positive = good)
        rs_score = min(100, 50 + rs * 5) if rs > -10 else 0

        # VWAP distance (closer = better, assume bullish if above VWAP? we want healthy trend)
        if vwap and price:
            vwap_dist_pct = (price - vwap) / vwap * 100
            if 0 <= vwap_dist_pct <= 3:
                vwap_score = 100
            elif vwap_dist_pct < 0:
                vwap_score = max(0, 100 + vwap_dist_pct * 10)  # below VWAP penalize
            else:
                vwap_score = max(0, 100 - vwap_dist_pct * 5)   # too far above, risk of reversal
        else:
            vwap_score = 50

        # Weighted sum
        health = (
            flow_score * 0.40 +
            oi_score * 0.25 +
            rs_score * 0.20 +
            vwap_score * 0.15
        )
        # PnL bonus: if in profit, slight boost
        pnl_pct = ((price - trade.entry_price) / trade.entry_price) * 100
        if pnl_pct > 0:
            health = min(100, health + pnl_pct * 0.5)  # +10% profit = +5 health

        return round(health, 1)

    def update(self, symbol: str, current_price: float, coin_data: Dict[str, Any],
               df_5m=None, df_1h=None, btc_momentum_5m: float = 0.0) -> Optional[Dict[str, Any]]:
        trade = self.trades.get(symbol)
        if not trade or trade.state in ("EXIT", "CLOSED"):
            return None

        # Update highest high
        if current_price > trade.highest_high:
            trade.highest_high = current_price

        # Compute Trade Health
        trade.health = self._calc_trade_health(trade, coin_data, current_price)

        # ── State-based actions ──────────────────────────────────────────────
        # Stop Loss first
        if current_price <= trade.sl:
            return self._close_trade(trade, current_price, "Stop Loss")

        # TP1
        if not trade.tp1_done and current_price >= trade.tp1:
            trade.tp1_done = True
            trade.set_state("TP1_HIT")
            # Partial sell 30%
            sell_ratio = 0.3
            sell_amount = trade.position_size * sell_ratio
            trade.position_size *= (1 - sell_ratio)
            # Move SL to breakeven
            trade.sl = trade.entry_price
            trade.set_state("BREAKEVEN")
            log.info(f"{symbol} TP1 hit: Sold {sell_ratio*100:.0f}%, SL moved to BE, Runner active")
            trade.log.append({"time": datetime.now(), "event": "TP1", "price": current_price, "sold_ratio": sell_ratio})
            return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price, "ratio": sell_ratio, "reason": "TP1"}

        # Trailing stop (only after TP1, state == BREAKEVEN or RUNNER)
        if trade.state in ("BREAKEVEN", "RUNNER"):
            trailing_sl = trade.highest_high * 0.97
            if trailing_sl > trade.sl:
                trade.sl = trailing_sl
            if current_price <= trade.sl:
                return self._close_trade(trade, current_price, "Trailing Stop")

        # TP2
        if not trade.tp2_done and current_price >= trade.tp2:
            trade.tp2_done = True
            trade.set_state("TP2_HIT")
            # Close full position (or leave runner)
            # Here we close everything, runner logic could be added later
            return self._close_trade(trade, current_price, "TP2")

        # Exit Score (Smart Exit Engine)
        try:
            rs_1h = coin_data.get("rs_1h", 0)
            rs_4h = coin_data.get("rs_4h", 0)
            oi_change_pct = coin_data.get("oi_change", 0)
            current_gain_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100

            exit_result = calc_exit_score(
                df_5m=df_5m,
                df_1h=df_1h,
                rs_1h=rs_1h,
                rs_4h=rs_4h,
                oi_change_pct=oi_change_pct,
                current_gain_pct=current_gain_pct
            )
            exit_score = exit_result["exit_score"]
            exit_conf = exit_result["confidence"]
            reasons = exit_result.get("reasons", [])

            if exit_result["exit_signal"] == "EXIT" and exit_conf >= 80:
                return self._close_trade(trade, current_price, f"Exit Score {exit_score}: {', '.join(reasons)}")
            elif exit_result["exit_signal"] == "TRIM" and trade.state == "RUNNER":
                # Trim 20% more
                sell_ratio = 0.2
                trade.position_size *= (1 - sell_ratio)
                log.info(f"{symbol} TRIM signal: Sold 20%, reasons: {reasons}")
                trade.log.append({"time": datetime.now(), "event": "TRIM", "price": current_price, "ratio": sell_ratio, "reasons": reasons})
                return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price, "ratio": sell_ratio, "reason": "TRIM"}
        except Exception as e:
            log.error(f"Exit Score error for {symbol}: {e}")

        return None

    def _close_trade(self, trade: Trade, exit_price: float, reason: str) -> Dict[str, Any]:
        pnl = (exit_price - trade.entry_price) * trade.position_size
        pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.exit_time = datetime.now()
        trade.exit_reason = reason
        trade.set_state("EXIT")
        trade.set_state("CLOSED")
        trade.log.append({"time": trade.exit_time, "event": "CLOSE", "price": exit_price, "reason": reason, "pnl": pnl})

        log.info(f"Trade closed: {trade.symbol} | Exit={exit_price:.4f} | PnL={pnl:.2f}$ ({pnl_pct:.2f}%) | Reason: {reason}")
        self.closed_trades.append(trade)
        if trade.symbol in self.trades:
            del self.trades[trade.symbol]

        return {
            "symbol": trade.symbol,
            "action": "SELL_ALL",
            "price": exit_price,
            "reason": reason,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

    def get_active_trades(self) -> List[Trade]:
        return [t for t in self.trades.values() if t.state not in ("EXIT", "CLOSED")]

    def get_closed_trades(self) -> List[Trade]:
        return self.closed_trades

    def get_summary(self) -> Dict[str, Any]:
        active = self.get_active_trades()
        closed = self.get_closed_trades()
        total_pnl = sum(t.pnl for t in closed)
        win_trades = [t for t in closed if t.pnl > 0]
        return {
            "active_count": len(active),
            "closed_count": len(closed),
            "total_pnl": total_pnl,
            "win_rate": len(win_trades) / len(closed) if closed else 0,
            "active_symbols": [t.symbol for t in active],
        }
