"""
CRYPTO-BOT Elite – Shadow Rules Analysis
בודק מה היה קורה אילו החלנו פילטרים שונים על BUY FINAL.
"""
import sqlite3, os
from datetime import datetime
from utils.logger import get_logger

log = get_logger("shadow_rules")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")

# הגדרת מערכות חוקים
RULES = {
    "Baseline (all)":          lambda r: True,
    "RS > 0.3":                lambda r: r["rs_1h"] > 0.3,
    "RS > 0.5":                lambda r: r["rs_1h"] > 0.5,
    "Flow > 40":               lambda r: r["flow_score"] > 40,
    "Flow > 50":               lambda r: r["flow_score"] > 50,
    "Flow > 60":               lambda r: r["flow_score"] > 60,
    "Prob > 45":               lambda r: r["probability"] > 45,
    "Prob > 55":               lambda r: r["probability"] > 55,
    "RS>0.5 + Flow>50":        lambda r: r["rs_1h"] > 0.5 and r["flow_score"] > 50,
    "RS>0.5 + Flow>50 + MH>50": lambda r: r["rs_1h"] > 0.5 and r["flow_score"] > 50 and r["market_health"] > 50,
    "RS>0.5 + Flow>50 + MH>55": lambda r: r["rs_1h"] > 0.5 and r["flow_score"] > 50 and r["market_health"] > 55,
}

def run_analysis():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # שליפת כל עסקאות BUY FINAL
    trades = cur.execute("""
        SELECT * FROM shadow_trades
        WHERE decision = 'BUY' AND outcome_status = 'FINAL'
        AND entry_price > 0
    """).fetchall()

    log.info(f"Analyzing {len(trades)} BUY FINAL trades across {len(RULES)} rules")

    results = []
    for rule_name, rule_func in RULES.items():
        filtered = [t for t in trades if rule_func(t)]
        if not filtered:
            results.append((rule_name, 0, 0, 0, 0, 0, 0))
            continue

        cnt = len(filtered)
        tp1_rate = sum(t["outcome_tp1_hit"] for t in filtered) / cnt
        # PnL ממוצע (אם יש)
        pnl_vals = [t["pnl_pct"] for t in filtered if t["pnl_pct"] is not None and t["pnl_pct"] != 0]
        avg_pnl = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0
        # מקסימום Up/Down
        mfe_vals = [t["outcome_mfe"] for t in filtered if t["outcome_mfe"] is not None and t["outcome_mfe"] != 0]
        avg_mfe = sum(mfe_vals) / len(mfe_vals) if mfe_vals else 0
        mae_vals = [t["outcome_mae"] for t in filtered if t["outcome_mae"] is not None and t["outcome_mae"] != 0]
        avg_mae = sum(mae_vals) / len(mae_vals) if mae_vals else 0

        results.append((rule_name, cnt, round(tp1_rate*100,1), round(avg_pnl,2), round(avg_mfe,2), round(avg_mae,2), round(avg_pnl,2)))

    # מיון לפי TP1 rate (או PnL)
    results.sort(key=lambda x: x[2], reverse=True)

    # הדפסת טבלה
    header = f"{'Rule':<30s} {'Trades':>7s} {'TP1%':>7s} {'Avg PnL%':>9s} {'Avg MFE%':>9s} {'Avg MAE%':>9s}"
    lines = [header, "-"*len(header)]
    for rule, cnt, tp1, pnl, mfe, mae in results:
        lines.append(f"{rule:<30s} {cnt:7d} {tp1:7.1f} {pnl:9.2f} {mfe:9.2f} {mae:9.2f}")

    report = "\n".join(lines)
    log.info("Shadow Rules Analysis:\n" + report)
    return report
