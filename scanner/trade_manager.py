"""
CRYPTO-BOT Elite — Trade Manager

אחראי על ניהול מחזור חיים של עסקה:
- פתיחת עסקה (כניסה)
- מעקב אחר מחיר, TP1, TP2, Trailing Stop
- החלטות יציאה (TP, Stop, Exit Score)
- ניהול Runner אחרי מימוש חלקי
- תיעוד מלא (Journal)
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from utils.logger import get_logger
from scanner.exit_engine import calc_exit_score
from tools.shadow_mode import update_shadow_exit

log = get_logger(__name__)


@dataclass
class Trade:
    symbol: str
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    setup_type: str
    entry_time: datetime
    position_size: float          # כמות מטבע
    initial_capital: float        # כמה כסף הושקע
    state: str = "ACTIVE"         # ACTIVE, TP1_HIT, RUNNER, CLOSED
    highest_high: float = 0.0
    lowest_low: float = 0.0       # למעקב אחר drawdown
    tp1_done: bool = False
    exit_reason: str = ""
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    log: List[Dict[str, Any]] = field(default_factory=list)


class TradeManager:
    """
    מנהל את כל העסקאות הפתוחות.
    """

    def __init__(self, portfolio_capital: float = 500.0, max_trades: int = 2):
        self.trades: Dict[str, Trade] = {}  # symbol -> Trade
        self.portfolio_capital = portfolio_capital
        self.max_trades = max_trades
        self.closed_trades: List[Trade] = []

    def can_open_trade(self) -> bool:
        """האם מותר לפתוח עסקה נוספת?"""
        active = [t for t in self.trades.values() if t.state not in ("CLOSED",)]
        return len(active) < self.max_trades

    def open_trade(self, signal: Dict[str, Any], price: float) -> Optional[Trade]:
        """
        פותח עסקה חדשה על בסיס EntrySignal.
        מחשב Position Size לפי סיכון 1% (פשוט, אפשר להחליף ב-Position Sizer).
        """
        if not self.can_open_trade():
            log.warning("Max trades reached, cannot open new trade")
            return None

        symbol = signal.get("symbol", "UNK")
        entry = signal.get("entry", price)
        sl = signal.get("sl", entry * 0.98)
        tp1 = signal.get("tp1", entry * 1.04)
        tp2 = signal.get("tp2", entry * 1.10)
        setup_type = signal.get("setup_type", "")

        # Position Size: 1% סיכון, סטופ 4% = השקעה של 25% מהתיק
        risk_per_trade = self.portfolio_capital * 0.01
        stop_distance_pct = abs(entry - sl) / entry if entry > 0 else 0.04
        if stop_distance_pct == 0:
            stop_distance_pct = 0.04
        capital_to_allocate = risk_per_trade / stop_distance_pct
        capital_to_allocate = min(capital_to_allocate, self.portfolio_capital * 0.25)  # מקסימום 25% לתיק
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
            lowest_low=entry,  # התחלה ממחיר כניסה
        )

        self.trades[symbol] = trade
        log.info(f"Trade opened: {symbol} | Entry={entry:.4f} | SL={sl:.4f} | TP1={tp1:.4f} | TP2={tp2:.4f} | Size={position_size:.4f} | Capital={capital_to_allocate:.2f}$")
        trade.log.append({"time": datetime.now(), "event": "OPEN", "price": entry})
        return trade

    def update(self, symbol: str, current_price: float, coin_data: Dict[str, Any], 
               df_5m=None, df_1h=None, btc_momentum_5m: float = 0.0) -> Optional[Dict[str, Any]]:
        """
        מעדכן עסקה פעילה: בודק TP, SL, Exit Score, ומבצע פעולות.
        מחזיר אירוע (action) אם קרה משהו.
        """
        trade = self.trades.get(symbol)
        if not trade or trade.state == "CLOSED":
            return None

        # עדכון Highest High
        if current_price > trade.highest_high:
            trade.highest_high = current_price

        # עדכון Lowest Low
        if trade.lowest_low == 0 or current_price < trade.lowest_low:
            trade.lowest_low = current_price

        # 1. Stop Loss
        if current_price <= trade.sl:
            return self._close_trade(trade, current_price, "Stop Loss")

        # 2. Trailing Stop (מופעל אחרי TP1)
        if trade.tp1_done and trade.state == "RUNNER":
            # טרייל 3% מהשיא
            trailing_sl = trade.highest_high * 0.97
            if trailing_sl > trade.sl:
                trade.sl = trailing_sl
            if current_price <= trade.sl:
                return self._close_trade(trade, current_price, "Trailing Stop")

        # 3. TP1 / TP2
        if not trade.tp1_done and current_price >= trade.tp1:
            trade.tp1_done = True
            # מימוש 30%
            sell_ratio = 0.3
            sell_amount = trade.position_size * sell_ratio
            trade.position_size *= (1 - sell_ratio)
            # העבר סטופ לבראק-איבן
            trade.sl = trade.entry_price
            trade.state = "RUNNER"
            log.info(f"{symbol} TP1 hit: Sold {sell_ratio*100:.0f}% at {current_price:.4f}, SL moved to BE, Runner active")
            trade.log.append({"time": datetime.now(), "event": "TP1", "price": current_price, "sold_ratio": sell_ratio})
            # מחזיר אירוע SELL_PARTIAL
            return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price, "ratio": sell_ratio, "reason": "TP1"}

        if current_price >= trade.tp2:
            return self._close_trade(trade, current_price, "TP2")

        # 4. Exit Score (Smart Exit Engine)
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
            if exit_result["exit_signal"] == "EXIT":
                return self._close_trade(trade, current_price, f"Exit Score: {', '.join(exit_result['reasons'])}")
            if exit_result["exit_signal"] == "TRIM" and trade.state == "RUNNER":
                # ממליץ לקצץ עוד 20%
                sell_ratio = 0.2
                sell_amount = trade.position_size * sell_ratio
                trade.position_size *= (1 - sell_ratio)
                log.info(f"{symbol} TRIM signal: Sold 20% at {current_price:.4f}, reason: {exit_result['reasons']}")
                trade.log.append({"time": datetime.now(), "event": "TRIM", "price": current_price, "ratio": sell_ratio, "reasons": exit_result["reasons"]})
                return {"symbol": symbol, "action": "SELL_PARTIAL", "price": current_price, "ratio": sell_ratio, "reason": "TRIM"}
        except Exception as e:
            log.error(f"Exit Score error for {symbol}: {e}")

        return None  # No action

    def _close_trade(self, trade: Trade, exit_price: float, reason: str) -> Dict[str, Any]:
        """
        סגירה מלאה של העסקה.
        """
        # חישוב PnL
        pnl = (exit_price - trade.entry_price) * trade.position_size
        pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        
        # חישוב Max Profit / Max Drawdown
        max_profit_pct = ((trade.highest_high - trade.entry_price) / trade.entry_price) * 100 if trade.highest_high > 0 else 0
        max_drawdown_pct = ((trade.lowest_low - trade.entry_price) / trade.entry_price) * 100 if trade.lowest_low > 0 else 0
        
        # עדכון
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.state = "CLOSED"
        trade.exit_time = datetime.now()
        trade.exit_reason = reason
        trade.log.append({"time": trade.exit_time, "event": "CLOSE", "price": exit_price, "reason": reason, "pnl": pnl})

        # ── תיעוד יציאה ב-Shadow DB ────────────────────────────────
        try:
            duration_minutes = int((trade.exit_time - trade.entry_time).total_seconds() / 60)
            update_shadow_exit(
                symbol=trade.symbol,
                exit_reason=reason,
                pnl=pnl,
                duration_minutes=duration_minutes,
                pnl_pct=pnl_pct,
                max_profit_pct=max_profit_pct,
                max_drawdown_pct=max_drawdown_pct,
                trade_state=trade.state,
                exit_price=exit_price
            )
        except Exception as e:
            log.error(f"Shadow Exits update failed: {e}")

        log.info(f"Trade closed: {trade.symbol} | Exit={exit_price:.4f} | PnL={pnl:.2f}$ ({pnl_pct:.2f}%) | Reason: {reason}")
        self.closed_trades.append(trade)
        # Remove from active
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
        return [t for t in self.trades.values() if t.state != "CLOSED"]

    def get_closed_trades(self) -> List[Trade]:
        return self.closed_trades

    def get_summary(self) -> Dict[str, Any]:
        """סיכום תיק."""
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
