"""
CRYPTO-BOT Elite — Learning Dashboard
מדפיס סטטיסטיקות מתוך shadow_trades
"""
import sqlite3
import os
from datetime import datetime
from utils.logger import get_logger

log = get_logger("learning_dashboard")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

def run_dashboard():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # סה"כ עסקאות
    total = cur.execute("SELECT COUNT(*) as cnt FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["cnt"]
    if total < 5:
        log.info(f"Learning Dashboard: only {total} trades with outcome – need more data")
        conn.close()
        return

    # TP1 Rate
    tp1_rate = cur.execute("SELECT AVG(outcome_tp1_hit) as rate FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["rate"]

    # TP2 Rate
    tp2_rate = cur.execute("SELECT AVG(outcome_tp2_hit) as rate FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["rate"]

    # SL Rate
    sl_rate = cur.execute("SELECT AVG(outcome_sl_hit) as rate FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["rate"]

    # Average Max Up / Max Down
    avg_up = cur.execute("SELECT AVG(outcome_max_up_pct) as avg FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["avg"]
    avg_down = cur.execute("SELECT AVG(outcome_max_down_pct) as avg FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1").fetchone()["avg"]

    # Best Setup
    best_setup = cur.execute("""
        SELECT setup, COUNT(*) as cnt, AVG(outcome_tp1_hit) as tp1_rate
        FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1
        GROUP BY setup
        ORDER BY tp1_rate DESC LIMIT 1
    """).fetchone()

    # Best Probability Range
    best_prob = cur.execute("""
        SELECT
            CASE
                WHEN probability < 30 THEN '<30%'
                WHEN probability < 40 THEN '30-40%'
                WHEN probability < 50 THEN '40-50%'
                WHEN probability < 60 THEN '50-60%'
                WHEN probability < 70 THEN '60-70%'
                ELSE '70%+'
            END as prob_range,
            AVG(outcome_tp1_hit) as tp1_rate,
            COUNT(*) as cnt
        FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1
        GROUP BY prob_range
        ORDER BY tp1_rate DESC LIMIT 1
    """).fetchone()

    # Best Flow Range
    best_flow = cur.execute("""
        SELECT
            CASE
                WHEN flow_score < 30 THEN '<30'
                WHEN flow_score < 50 THEN '30-50'
                WHEN flow_score < 70 THEN '50-70'
                ELSE '70+'
            END as flow_range,
            AVG(outcome_tp1_hit) as tp1_rate,
            COUNT(*) as cnt
        FROM shadow_trades WHERE entry_price > 0 AND outcome_checked=1
        GROUP BY flow_range
        ORDER BY tp1_rate DESC LIMIT 1
    """).fetchone()

    conn.close()

    lines = []
    lines.append("=" * 35)
    lines.append(" LEARNING REPORT")
    lines.append("=" * 35)
    lines.append(f" Trades with outcome: {total}")
    lines.append(f" TP1 Rate: {tp1_rate*100:.0f}%")
    lines.append(f" TP2 Rate: {tp2_rate*100:.0f}%")
    lines.append(f" SL Rate:  {sl_rate*100:.0f}%")
    lines.append(f" Avg Max Up:  {avg_up:.1f}%")
    lines.append(f" Avg Max Down: {avg_down:.1f}%")
    if best_setup:
        lines.append(f" Best Setup: {best_setup['setup']} (TP1: {best_setup['tp1_rate']*100:.0f}%)")
    if best_prob:
        lines.append(f" Best Prob: {best_prob['prob_range']} (TP1: {best_prob['tp1_rate']*100:.0f}%)")
    if best_flow:
        lines.append(f" Best Flow: {best_flow['flow_range']} (TP1: {best_flow['tp1_rate']*100:.0f}%)")
    lines.append("=" * 35)

    log.info("\n".join(lines))
