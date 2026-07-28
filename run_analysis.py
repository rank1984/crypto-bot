import sqlite3
import pandas as pd

DB_PATH = "data/shadow.db"

QUERIES = {
    "1. TP1 Rate לפי Probability": """
        SELECT 
          CASE 
            WHEN probability < 30 THEN '<30'
            WHEN probability < 40 THEN '30-40'
            WHEN probability < 50 THEN '40-50'
            WHEN probability < 60 THEN '50-60'
            WHEN probability < 70 THEN '60-70'
            ELSE '70+'
          END AS prob_range,
          COUNT(*) AS trades,
          ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate,
          ROUND(AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END), 2) AS avg_win_pct,
          ROUND(AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END), 2) AS avg_loss_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY prob_range
        ORDER BY MIN(probability);
    """,
    "2. TP1 Rate לפי Flow": """
        SELECT 
          CASE 
            WHEN flow_score < 30 THEN '<30'
            WHEN flow_score < 50 THEN '30-50'
            WHEN flow_score < 70 THEN '50-70'
            ELSE '70+'
          END AS flow_range,
          COUNT(*) AS trades,
          ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate,
          ROUND(AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END), 2) AS avg_win_pct,
          ROUND(AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END), 2) AS avg_loss_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY flow_range
        ORDER BY MIN(flow_score);
    """,
    "3. TP1 Rate לפי Setup": """
        SELECT setup, COUNT(*) AS trades,
               ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate,
               ROUND(AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END), 2) AS avg_win_pct,
               ROUND(AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END), 2) AS avg_loss_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY setup
        ORDER BY tp1_rate DESC;
    """,
    "4. TP1 Rate לפי שעה": """
        SELECT CAST(strftime('%H', ts) AS INTEGER) AS hour,
               COUNT(*) AS trades,
               ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY hour
        ORDER BY hour;
    """,
    "5. TP1 Rate לפי Regime": """
        SELECT btc_regime, COUNT(*) AS trades,
               ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY btc_regime;
    """,
    "6. TP1 Rate לפי OI Change": """
        SELECT 
          CASE 
            WHEN oi_change < 0 THEN 'Negative'
            WHEN oi_change < 100 THEN '0-100'
            WHEN oi_change < 500 THEN '100-500'
            ELSE '500+'
          END AS oi_range,
          COUNT(*) AS trades,
          ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY oi_range
        ORDER BY MIN(oi_change);
    """,
    "7. TP1 Rate לפי Compression": """
        SELECT is_compressed, COUNT(*) AS trades,
               ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
        GROUP BY is_compressed;
    """,
    "8. שילוב Probability >= 50 ו-Flow >= 50": """
        SELECT 
          COUNT(*) AS trades,
          ROUND(AVG(outcome_tp1_hit), 3) AS tp1_rate,
          ROUND(AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END), 2) AS avg_win_pct,
          ROUND(AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END), 2) AS avg_loss_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL' AND entry_price > 0
          AND probability >= 50 AND flow_score >= 50;
    """
}

def run_analysis():
    try:
        conn = sqlite3.connect(DB_PATH)
        print("=" * 60)
        print("📊 SHADOW DB STATISTICAL ANALYSIS REPORT")
        print("=" * 60 + "\n")
        
        for title, query in QUERIES.items():
            print(f"### {title}")
            df = pd.read_sql_query(query, conn)
            if df.empty:
                print("אין נתונים מתאימים בשאילתה זו.\n")
            else:
                print(df.to_string(index=False))
            print("\n" + "-" * 60 + "\n")
            
        conn.close()
    except Exception as e:
        print(f"❌ שגיאה בהרצת הניתוח: {e}")

if __name__ == "__main__":
    run_analysis()
