"""
scanner/expected_moves.py
Compute Expected Move and Hold Time from historical AI_60_80/AI_80_100 trades.
Uses point-in-time DB data only.
"""
import os
import sqlite3
import numpy as np
from utils.logger import get_logger

log = get_logger("expected_moves")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")


def get_expected_stats(ai_score: float, setup: str, min_n: int = 5) -> dict:
    """
    Returns median MFE, MAE, TP1 time, exit time from historical trades
    with similar AI bucket and setup.
    Returns None if not enough data.
    """
    # Determine AI bucket
    if ai_score >= 80:
        ai_bucket = "AI_80_100"
    elif ai_score >= 60:
        ai_bucket = "AI_60_80"
    elif ai_score >= 40:
        ai_bucket = "AI_40_60"
    else:
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT 
            outcome_mfe, outcome_mae, 
            duration_minutes,
            outcome_tp1_hit,
            pnl_pct, pnl_r,
            time_to_tp1_min
        FROM shadow_trades
        WHERE decision='BUY'
          AND outcome_status='FINAL'
          AND outcome_checked=1
          AND ai_bucket = ?
          AND setup = ?
    """, (ai_bucket, setup)).fetchall()
    conn.close()

    if len(rows) < min_n:
        log.debug(f"Not enough data: ai={ai_bucket}, setup={setup}, n={len(rows)}")
        return None

    mfe_vals = [r["outcome_mfe"] for r in rows if r["outcome_mfe"] is not None]
    mae_vals = [r["outcome_mae"] for r in rows if r["outcome_mae"] is not None]
    duration_vals = [r["duration_minutes"] for r in rows if r["duration_minutes"] is not None]
    tp1_vals = [r["time_to_tp1_min"] for r in rows if r["time_to_tp1_min"] is not None]
    tp1_hits = sum(1 for r in rows if r["outcome_tp1_hit"])

    return {
        "n": len(rows),
        "median_mfe": round(float(np.median(mfe_vals)), 2) if mfe_vals else 0,
        "median_mae": round(float(np.median(mae_vals)), 2) if mae_vals else 0,
        "median_hold_min": int(np.median(duration_vals)) if duration_vals else 0,
        "median_tp1_min": int(np.median(tp1_vals)) if tp1_vals else 0,
        "tp1_rate": round(tp1_hits / len(rows) * 100, 1),
        "ai_bucket": ai_bucket,
    }


def format_expected_move(stats: dict) -> str:
    """Format for Telegram."""
    if not stats:
        return ""
    hold_h = stats["median_hold_min"] / 60 if stats["median_hold_min"] else 0
    tp1_h = stats["median_tp1_min"] / 60 if stats["median_tp1_min"] else 0

    lines = []
    lines.append(f"📊 *היסטוריית Setup (n={stats['n']})*")
    lines.append(f"   • TP1 Rate: {stats['tp1_rate']}%")
    lines.append(f"   • חציון MFE: {stats['median_mfe']}%")
    lines.append(f"   • חציון MAE: {stats['median_mae']}%")
    if tp1_h > 0:
        lines.append(f"   • חציון זמן ל‑TP1: {tp1_h:.1f} שעות")
    if hold_h > 0:
        lines.append(f"   • חציון זמן החזקה: {hold_h:.1f} שעות")
    return "\n".join(lines)
