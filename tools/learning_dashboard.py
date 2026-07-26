"""
CRYPTO-BOT Elite — Learning Dashboard (v3 – עשיר)
"""
import sqlite3
import os
from datetime import datetime
from utils.logger import get_logger

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def _calc_ev(win_rate, avg_win, avg_loss):
    if win_rate is None or avg_win is None or avg_loss is None:
        return None
    return round((win_rate * avg_win) + ((1 - win_rate) * avg_loss), 2)

def _profit_factor(avg_win, avg_loss, win_rate):
    if avg_loss == 0 or win_rate is None:
        return None
    gross_profit = win_rate * avg_win
    gross_loss = (1 - win_rate) * abs(avg_loss)
    return round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stats = {
        "total_trades": 0,
        "tp1_rate": 0, "tp2_rate": 0, "sl_rate": 0,
        "avg_max_up": 0, "avg_max_down": 0,
        "avg_win": 0, "avg_loss": 0,
        "profit_factor": 0, "expectancy": 0,
        "best_setup": None, "best_prob_range": None, "best_flow_range": None,
        "prob_ranges": [], "flow_ranges": [], "setup_ranges": [],
        "regime_ranges": [], "hour_ranges": [],
        "oi_ranges": [], "compression_ranges": [], "trending_ranges": [],
        "ai_ranges": []
    }

    # סה"כ עסקאות שנסגרו (FINAL)
    total = cur.execute("""
        SELECT COUNT(*) as cnt FROM shadow_trades
        WHERE entry_price > 0 AND outcome_status = 'FINAL'
    """).fetchone()["cnt"]
    if total < 5:
        conn.close()
        return stats

    stats["total_trades"] = total

    # מדדי יסוד
    row = cur.execute("""
        SELECT AVG(outcome_tp1_hit) as tp1, AVG(outcome_tp2_hit) as tp2,
               AVG(outcome_sl_hit) as sl, AVG(outcome_max_up_pct) as maxup,
               AVG(outcome_max_down_pct) as maxdown
        FROM shadow_trades WHERE entry_price > 0 AND outcome_status = 'FINAL'
    """).fetchone()
    stats["tp1_rate"] = row["tp1"] or 0
    stats["tp2_rate"] = row["tp2"] or 0
    stats["sl_rate"] = row["sl"] or 0
    stats["avg_max_up"] = row["maxup"] or 0
    stats["avg_max_down"] = row["maxdown"] or 0

    # Avg Win / Avg Loss (מבוסס על PnL%)
    pnl_row = cur.execute("""
        SELECT AVG(CASE WHEN pnl_pct>0 THEN pnl_pct END) as avg_win,
               AVG(CASE WHEN pnl_pct<0 THEN pnl_pct END) as avg_loss
        FROM shadow_trades WHERE entry_price > 0 AND outcome_status = 'FINAL' AND pnl_pct != 0
    """).fetchone()
    stats["avg_win"] = pnl_row["avg_win"] or 0
    stats["avg_loss"] = abs(pnl_row["avg_loss"] or 0)

    win_rate = stats["tp1_rate"]  # TP1 כמדד הצלחה
    stats["expectancy"] = _calc_ev(win_rate, stats["avg_win"], -stats["avg_loss"])
    stats["profit_factor"] = _profit_factor(stats["avg_win"], stats["avg_loss"], win_rate)

    # פילוחים – פונקציית עזר
    def segment(table, column, ranges, labels):
        cases = " ".join([f"WHEN {column} {r} THEN '{l}'" for r, l in zip(ranges, labels)])
        query = f"""
            SELECT CASE {cases} END as seg,
                   COUNT(*) as cnt,
                   AVG(outcome_tp1_hit) as tp1_rate,
                   AVG(CASE WHEN pnl_pct>0 THEN pnl_pct END) as avg_win,
                   AVG(CASE WHEN pnl_pct<0 THEN pnl_pct END) as avg_loss
            FROM {table}
            WHERE entry_price > 0 AND outcome_status = 'FINAL'
            GROUP BY seg ORDER BY MIN({column})
        """
        return cur.execute(query).fetchall()

    # Setup
    stats["setup_ranges"] = [dict(r) for r in segment("shadow_trades", "setup",
        ["= 'DIP_BUY'", "= 'VWAP_RECLAIM'", "= 'BREAKOUT'", "ELSE"],
        ["DIP_BUY", "VWAP_RECLAIM", "BREAKOUT", "OTHER"])]

    # Probability
    stats["prob_ranges"] = [dict(r) for r in segment("shadow_trades", "probability",
        ["<30", "BETWEEN 30 AND 40", "BETWEEN 40 AND 50", "BETWEEN 50 AND 60", "BETWEEN 60 AND 70", ">=70"],
        ["<30","30-40","40-50","50-60","60-70","70+"])]

    # Flow
    stats["flow_ranges"] = [dict(r) for r in segment("shadow_trades", "flow_score",
        ["<30", "BETWEEN 30 AND 50", "BETWEEN 50 AND 70", ">=70"],
        ["<30","30-50","50-70","70+"])]

    # AI Score
    stats["ai_ranges"] = [dict(r) for r in segment("shadow_trades", "ai_score",
        ["<50", "BETWEEN 50 AND 60", "BETWEEN 60 AND 70", "BETWEEN 70 AND 80", ">=80"],
        ["<50","50-60","60-70","70-80","80+"])]

    # Market Regime
    stats["regime_ranges"] = [dict(r) for r in segment("shadow_trades", "btc_regime",
        ["= 'TRENDING_BULL'", "= 'RANGE'", "= 'RISK_OFF'", "ELSE"],
        ["TREND","RANGE","RISK_OFF","OTHER"])]

    # שעה (לפי ts)
    hour_query = """
        SELECT CAST(strftime('%H', ts) AS INTEGER) as hour,
               COUNT(*) as cnt,
               AVG(outcome_tp1_hit) as tp1_rate,
               AVG(CASE WHEN pnl_pct>0 THEN pnl_pct END) as avg_win,
               AVG(CASE WHEN pnl_pct<0 THEN pnl_pct END) as avg_loss
        FROM shadow_trades
        WHERE entry_price > 0 AND outcome_status = 'FINAL'
        GROUP BY hour ORDER BY hour
    """
    stats["hour_ranges"] = [dict(r) for r in cur.execute(hour_query).fetchall()]

    # OI
    stats["oi_ranges"] = [dict(r) for r in segment("shadow_trades", "oi_change",
        ["<0", "BETWEEN 0 AND 100", "BETWEEN 100 AND 500", ">=500"],
        ["Negative","0-100","100-500","500+"])]

    # Compression
    stats["compression_ranges"] = [dict(r) for r in segment("shadow_trades", "is_compressed",
        ["= 'TRUE'", "= 'FALSE'", "ELSE"],
        ["True","False","Other"])]

    # Trending Bonus (אם קיים שדה trend_bonus)
    try:
        stats["trending_ranges"] = [dict(r) for r in segment("shadow_trades", "trend_bonus",
            ["=0", ">0", "ELSE"], ["No","Yes","Other"])]
    except:
        pass

    # Best ranges
    def best_range(ranges, key="tp1_rate"):
        if not ranges:
            return None
        return max(ranges, key=lambda x: x.get(key, 0) or 0)

    stats["best_setup"] = best_range(stats["setup_ranges"])
    stats["best_prob_range"] = best_range(stats["prob_ranges"])
    stats["best_flow_range"] = best_range(stats["flow_ranges"])
    stats["best_ai_range"] = best_range(stats["ai_ranges"])
    stats["best_regime"] = best_range(stats["regime_ranges"])
    stats["best_hour"] = best_range(stats["hour_ranges"])
    stats["best_oi"] = best_range(stats["oi_ranges"])
    stats["best_compression"] = best_range(stats["compression_ranges"])

    conn.close()
    return stats


def run_dashboard():
    stats = get_stats()
    if stats["total_trades"] < 5:
        log.info(f"Learning Dashboard: need more data, have {stats['total_trades']}")
        return ""

    lines = ["=" * 45, "   LEARNING REPORT", "=" * 45]
    lines.append(f" Trades (FINAL): {stats['total_trades']}")
    lines.append(f" TP1 Rate: {stats['tp1_rate']*100:.0f}%  TP2: {stats['tp2_rate']*100:.0f}%  SL: {stats['sl_rate']*100:.0f}%")
    lines.append(f" Avg Win: {stats['avg_win']:+.2f}%  Avg Loss: {stats['avg_loss']:.2f}%")
    if stats["profit_factor"]:
        lines.append(f" Profit Factor: {stats['profit_factor']:.2f}  Expectancy (EV): {stats['expectancy']:+.2f}%")
    lines.append(f" Avg Max Up: {stats['avg_max_up']:.2f}%  Avg Max Down: {stats['avg_max_down']:.2f}%")

    # Best of each
    def print_best(title, obj, key="tp1_rate"):
        if obj:
            val = obj.get(key, 0) or 0
            lines.append(f" Best {title}: {obj.get('seg', obj.get('setup', obj.get('hour', '??')))}  (TP1: {val*100:.0f}%)")

    print_best("Setup", stats["best_setup"])
    print_best("Probability", stats["best_prob_range"])
    print_best("Flow", stats["best_flow_range"])
    print_best("AI Score", stats["best_ai_range"])
    print_best("Regime", stats["best_regime"])
    print_best("Hour", stats["best_hour"])
    print_best("OI", stats["best_oi"])
    print_best("Compression", stats["best_compression"])
    lines.append("=" * 45)

    report = "\n".join(lines)
    log.info(report)
    return report
