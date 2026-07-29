"""
CRYPTO-BOT Elite – Institutional Analysis (v1)
Run locally: python tools/institutional_analysis.py
"""
import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegressionCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import cross_val_score
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

DB_PATH = "data/shadow.db"
OUTPUT_REPORT = "analysis_report.txt"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT 
            id, ts, symbol, decision, setup,
            entry_price, trigger_price, tp1, tp2, sl,
            ai_score, flow_score, pre_score, oi_change, rs_1h,
            is_compressed, probability, market_health, news_score,
            btc_regime, funding,
            outcome_tp1_hit, outcome_sl_hit, outcome_mfe, outcome_mae,
            time_to_tp1_min, time_to_sl_min,
            pnl_pct, max_profit_pct, max_drawdown_pct
        FROM shadow_trades
        WHERE outcome_status = 'FINAL'
          AND decision = 'BUY'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    # Feature engineering
    df["is_compressed"] = df["is_compressed"].map({"TRUE":1,"FALSE":0}).fillna(0)
    df["hour"] = pd.to_datetime(df["ts"]).dt.hour
    df["target"] = df["outcome_tp1_hit"].astype(int)
    df["rs_x_flow"] = df["rs_1h"] * df["flow_score"]
    df["compressed_x_oi"] = df["is_compressed"] * df["oi_change"]
    return df

def audit(df):
    total = len(df)
    tp1_rate = df["outcome_tp1_hit"].mean()
    sl_rate = df["outcome_sl_hit"].mean()
    avg_win = df[df["outcome_tp1_hit"]==1]["pnl_pct"].mean()
    avg_loss = df[df["outcome_sl_hit"]==1]["pnl_pct"].mean()
    avg_mfe = df["outcome_mfe"].mean()
    avg_mae = df["outcome_mae"].mean()
    ev = tp1_rate * avg_win - (1 - tp1_rate) * abs(avg_loss)
    profit_factor = (tp1_rate * avg_win) / ((1 - tp1_rate) * abs(avg_loss)) if avg_loss != 0 else np.inf

    with open(OUTPUT_REPORT, "w") as f:
        f.write("=== Performance Audit ===\n")
        f.write(f"Trades: {total}\n")
        f.write(f"TP1 Rate: {tp1_rate:.2%}\n")
        f.write(f"SL Rate: {sl_rate:.2%}\n")
        f.write(f"Avg Win (PnL%): {avg_win:.2f}%\n")
        f.write(f"Avg Loss (PnL%): {avg_loss:.2f}%\n")
        f.write(f"Avg MFE: {avg_mfe:.2f}%\n")
        f.write(f"Avg MAE: {avg_mae:.2f}%\n")
        f.write(f"Expected Value (EV): {ev:.2f}%\n")
        f.write(f"Profit Factor: {profit_factor:.2f}\n\n")
    print(f"Audit done → {OUTPUT_REPORT}")

def feature_importance(df):
    features = [
        "rs_1h", "flow_score", "oi_change", "is_compressed",
        "market_health", "probability", "ai_score", "pre_score",
        "news_score", "funding", "rs_x_flow", "compressed_x_oi"
    ]
    X = df[features].fillna(0)
    y = df["target"]
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    lr = LogisticRegressionCV(Cs=5, cv=3, max_iter=2000, class_weight="balanced")
    lr.fit(X_scaled, y)
    rf = RandomForestClassifier(n_estimators=50, max_depth=4, class_weight="balanced", random_state=42)
    rf.fit(X_scaled, y)

    with open(OUTPUT_REPORT, "a") as f:
        f.write("=== Logistic Regression Coefficients ===\n")
        for name, coef in sorted(zip(features, lr.coef_[0]), key=lambda x: -abs(x[1])):
            f.write(f"{name:20s}: {coef:+.4f}\n")

        f.write("\n=== Random Forest Importance ===\n")
        for name, imp in sorted(zip(features, rf.feature_importances_), key=lambda x: -x[1]):
            f.write(f"{name:20s}: {imp:.3f}\n")
    print("Feature importance written.")

def segmentations(df):
    with open(OUTPUT_REPORT, "a") as f:
        f.write("\n=== Segmentation ===\n")
        # Setup
        for setup in df["setup"].dropna().unique():
            sub = df[df["setup"] == setup]
            f.write(f"{setup:15s}: n={len(sub):3d}, TP1={sub['outcome_tp1_hit'].mean():.1%}, "
                    f"MFE={sub['outcome_mfe'].mean():.1f}%, MAE={sub['outcome_mae'].mean():.1f}%\n")
        # Regime
        for regime in df["btc_regime"].dropna().unique():
            sub = df[df["btc_regime"] == regime]
            f.write(f"Regime {regime:15s}: n={len(sub):3d}, TP1={sub['outcome_tp1_hit'].mean():.1%}\n")
        # Compression
        for comp in [0, 1]:
            sub = df[df["is_compressed"] == comp]
            f.write(f"Compression {comp}: n={len(sub):3d}, TP1={sub['outcome_tp1_hit'].mean():.1%}\n")
        # RS bin
        bins = [-np.inf, 0, 0.5, 1, np.inf]
        labels = ["<0", "0-0.5", "0.5-1", ">1"]
        df["rs_bin"] = pd.cut(df["rs_1h"], bins=bins, labels=labels)
        for lbl in labels:
            sub = df[df["rs_bin"] == lbl]
            f.write(f"RS {lbl:8s}: n={len(sub):3d}, TP1={sub['outcome_tp1_hit'].mean():.1%}\n")
        # Hour
        for hour in sorted(df["hour"].unique()):
            sub = df[df["hour"] == hour]
            f.write(f"Hour {hour:2d}: n={len(sub):3d}, TP1={sub['outcome_tp1_hit'].mean():.1%}\n")
        print("Segmentation done.")

def ml_calibration(df):
    features = ["rs_1h", "flow_score", "oi_change", "is_compressed", "market_health"]
    X = df[features].fillna(0)
    y = df["target"]
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    lr = LogisticRegressionCV(Cs=5, cv=3, max_iter=2000, class_weight="balanced")
    calibrated = CalibratedClassifierCV(lr, method="isotonic", cv=3)
    calibrated.fit(X_scaled, y)
    prob_pos = calibrated.predict_proba(X_scaled)[:, 1]

    plt.figure()
    fraction_of_positives, mean_predicted_value = calibration_curve(y, prob_pos, n_bins=10)
    plt.plot(mean_predicted_value, fraction_of_positives, "s-", label="Calibrated LR")
    plt.plot([0, 1], [0, 1], "k:", label="Perfectly calibrated")
    plt.xlabel("Mean predicted probability")
    plt.ylabel("Fraction of positives")
    plt.title("Calibration Curve (Isotonic)")
    plt.legend()
    plt.savefig("calibration_curve.png")
    print("Calibration curve saved.")

def main():
    df = load_data()
    print(f"Loaded {len(df)} BUY FINAL trades.")
    audit(df)
    feature_importance(df)
    segmentations(df)
    ml_calibration(df)
    print("Institutional analysis completed.")

if __name__ == "__main__":
    main()
