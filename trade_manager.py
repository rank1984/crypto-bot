"""
CRYPTO-BOT Elite — Trade Manager v3

- ATR Trailing Stop (dynamic multipliers)
- Emergency Exit
- Trade Health Score
- Full context to Exit Engine
- Telegram integration ready
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from utils.logger import get_logger
from scanner.exit_engine import calc_exit_score, update_trailing_stop_atr

log = get_logger(__name__)

# ─── State Machine ────────────────────────────────────────────────────────────
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
    state: str = "NEW"
    highest_high: float = 0.0
    tp1_done: bool = False
    tp2_done: bool = False
    exit_reason: str = ""
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    health: float = 100.0         # 0-100
    atr_multiplier: float = 3.0   # dynamic
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
            position_size=position_size,
            initial_capital=capital_to_allocate,
            highest_high=entry,
        )
        trade.set_state("NEW")
        trade.set_state("ACTIVE")

        self.trades[symbol] = trade
        log.info(f"Trade opened: {symbol} | Entry={entry:.4f} | SL={sl:.4f} | "
                 f"TP1={tp1:.4f} | TP2={tp2:.4f} | Size={position_size:.4f} | "
                 f"Capital={capital_to_allocate:.2f}$")
        return trade

    # ── Trade Health ────────────────────────────────────────────────────────
    def _calc_trade_health(self, trade: Trade, coin_data: dict, current_price: float) -> float:
        flow = coin_data.get("flow_score", 50)
        oi = coin_data.get("oi_change", 0)
        rs = coin_data.get("rs_1h", 0)
        vwap = coin_data.get("vwap", 0)
        ema20 = coin_data.get("ema20", 0)
        cvd = coin_data.get("cvd", 0)

        # Flow (0-100)
        flow_score = min(100, max(0, (flow / 80) * 100)) if flow > 0 else 50

        # OI
        if oi > 0:
            oi_score = min(100, 50 + oi * 2)
        else:
            oi_score = max(0, 50 + oi * 2)

        # RS
        rs_score = min(100, 50 + rs * 5) if rs > -10 else 0

        # VWAP distance
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

        # EMA20 break penalty
        ema_penalty = 0
        if ema20 and current_price < ema20:
            ema_penalty = 20

        # CVD trend
        cvd_score = 50
        if cvd > 0:
            cvd_score = 80
        elif cvd < 0:
            cvd_score = 20

        health = (
            flow_score * 0.25 +
            oi_score * 0.20 +
            rs_score * 0.15 +
            vwap_score * 0.20 +
            cvd_score * 0.10 +
            (50 - ema_penalty) * 0.10
        )

        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        if pnl_pct > 0:
            health = min(100, health + pnl_pct * 0.5)
        else:
            health = max(0, health + pnl_pct * 0.5)

        return round(health, 1)

    # ── Dynamic ATR Multiplier ─────────────────────────────────────────────
    def _get_atr_multiplier(self, trade: Trade, current_pnl_pct: float) -> float:
        if trade.state in ("TP2_HIT", "RUNNER"):
            return 1.5
        if trade.state == "BREAKEVEN":
            return 1.8
        if trade.tp1_done:
            return 2.5
        if current_pnl_pct >= 20:
            return 1.5
        if current_pnl_pct >= 10:
            return 2.0
        return 3.0

    # ── Emergency Exit Check ──────────────────────────────────────────────
    def _emergency_exit_needed(self, coin_data: dict, market_health: float = 70.0, btc_regime: str = "") -> Tuple[bool, str]:
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
        if vwap and ema20 and price:
            if price < vwap and price < ema20:
                return True, "VWAP and EMA20 lost"
        return False, ""

    # ── Update ─────────────────────────────────────────────────────────────
    def update(self, symbol: str, current_price: float, coin_data: Dict[str, Any],
               df_5m=None, df_1h=None, market_health: float = 70.0, btc_regime: str = "") -> Optional[Dict[str, Any]]:
        trade = self.trades.get(symbol)
        if not trade or trade.state in ("EXIT", "CLOSED"):
            return None

        if current_price > trade.highest_high:
            trade.highest_high = current_price

        # Trade Health
        trade.health = self._calc_trade_health(trade, coin_data, current_price)

        # Emergency Exit
        emergency, reason = self._emergency_exit_needed(coin_data, market_health, btc_regime)
        if emergency:
            return self._close_trade(trade, current_price, f"EMERGENCY: {reason}")

        # Stop Loss
        if current_price <= trade.sl:
            return self._close_trade(trade, current_price, "Stop Loss")

        # TP1
        if not trade.tp1_done and current_price >= trade.tp1:
            trade.tp1_done = True
            trade.set_state("TP1_HIT")
            sell_ratio = 0.2
            trade.position_size *= (1 - sell_ratio)
            trade.sl = trade.entry_price  # breakeven
            trade.set_state("BREAKEVEN")
            trade.atr_multiplier = 2.5
            log.info(f"{symbol} TP1: sold 20%, SL to BE, ATR mult=2.5")
            return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price,
                    "ratio": sell_ratio, "reason": "TP1"}

        # TP2
        if not trade.tp2_done and current_price >= trade.tp2:
            trade.tp2_done = True
            trade.set_state("TP2_HIT")
            sell_ratio = 0.2
            trade.position_size *= (1 - sell_ratio)
            trade.state = "RUNNER"
            trade.atr_multiplier = 1.8
            log.info(f"{symbol} TP2: sold 20%, Runner active, ATR mult=1.8")
            return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price,
                    "ratio": sell_ratio, "reason": "TP2"}

        # ATR Trailing Stop
        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        trade.atr_multiplier = self._get_atr_multiplier(trade, pnl_pct)
        if df_5m is not None and len(df_5m) >= 15:
            new_sl = update_trailing_stop_atr(df_5m, trade.sl, trade.atr_multiplier)
            if new_sl is not None and new_sl > trade.sl:
                old_sl = trade.sl
                trade.sl = new_sl
                log.info(f"{symbol} SL moved: {old_sl:.4f} → {new_sl:.4f} (ATR x{trade.atr_multiplier})")
                # Telegram notification (placeholder)
                # send_sl_update(trade, old_sl, new_sl)

        # Force Exit if health too low
        if trade.health < 35:
            return self._close_trade(trade, current_price, f"Trade Health low ({trade.health})")

        # Exit Score (Smart Exit Engine)
        try:
            exit_result = calc_exit_score(
                df_5m=df_5m,
                df_1h=df_1h,
                rs_1h=coin_data.get("rs_1h", 0),
                rs_4h=coin_data.get("rs_4h", 0),
                oi_change_pct=coin_data.get("oi_change", 0),
                current_gain_pct=pnl_pct,
                flow_score=coin_data.get("flow_score", 50),
                market_health=market_health
            )
            if exit_result["exit_signal"] == "EXIT" and exit_result["confidence"] >= 80:
                return self._close_trade(trade, current_price,
                                         f"Exit Score {exit_result['exit_score']}: {', '.join(exit_result['reasons'])}")
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
        log.info(f"Trade closed: {trade.symbol} | Exit={exit_price:.4f} | PnL={pnl:.2f}$ ({pnl_pct:.2f}%) | Reason: {reason}")
        self.closed_trades.append(trade)
        if trade.symbol in self.trades:
            del self.trades[trade.symbol]
        return {"symbol": trade.symbol, "action": "SELL_ALL", "price": exit_price,
                "reason": reason, "pnl": pnl, "pnl_pct": pnl_pct}

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
