"""
CRYPTO-BOT Elite – Phase 2 Analysis (131 BUY FINAL)
"""
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegressionCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import cross_val_score
from sklearn.calibration import CalibratedClassifierCV
import warnings
warnings.filterwarnings("ignore")

# ── Load data ─────────────────────────────────────────────────────────────────
try:
    df = pd.read_csv("data/learning_dataset.csv")
    print(f"Loaded {len(df)} BUY FINAL trades")
except FileNotFoundError:
    print("data/learning_dataset.csv not found. Run export_learning_dataset.py first.")
    exit()

# ── Feature Engineering ───────────────────────────────────────────────────────
# Interactions (keep simple)
df["rs_x_flow"] = df["rs_1h"] * df["flow_score"]
df["compressed_x_oi"] = df["is_compressed"].map({"TRUE":1,"FALSE":0}) * df["oi_change"]
df["prob_x_flow"] = df["probability"] * df["flow_score"]

# Encode categorical
for col in ["btc_regime", "setup"]:
    if col in df.columns:
        df[col] = LabelEncoder().fit_transform(df[col].astype(str))

# Features (use only meaningful ones)
features = [
    "rs_1h", "flow_score", "oi_change", "is_compressed",
    "market_health", "btc_regime", "setup",
    "rs_x_flow", "compressed_x_oi", "prob_x_flow"
]
# Convert is_compressed to 0/1
df["is_compressed"] = df["is_compressed"].map({"TRUE":1,"FALSE":0}).fillna(0)

X = df[features].fillna(0)
y = df["target"].astype(int)

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

print(f"\nPositive class ratio: {y.mean():.2%}")

# ── Logistic Regression (with regularization) ─────────────────────────────────
lr = LogisticRegressionCV(Cs=10, cv=3, max_iter=5000, class_weight="balanced")
lr.fit(X_scaled, y)

print("\n=== Logistic Regression Coefficients (scaled) ===")
for f, coef in zip(features, lr.coef_[0]):
    print(f"{f:20s}: {coef:+.4f}")

# Cross-validated ROC-AUC
lr_auc = cross_val_score(lr, X_scaled, y, cv=3, scoring="roc_auc").mean()
print(f"Logistic Regression ROC-AUC (CV): {lr_auc:.3f}")

# ── Random Forest (conservative) ──────────────────────────────────────────────
rf = RandomForestClassifier(n_estimators=50, max_depth=4, max_features="sqrt",
                            class_weight="balanced", random_state=42)
rf.fit(X_scaled, y)

print("\n=== Random Forest Feature Importance ===")
for f, imp in sorted(zip(features, rf.feature_importances_), key=lambda x: -x[1]):
    print(f"{f:20s}: {imp:.3f}")

rf_auc = cross_val_score(rf, X_scaled, y, cv=3, scoring="roc_auc").mean()
print(f"Random Forest ROC-AUC (CV): {rf_auc:.3f}")

# ── Expected Value (simple estimate) ──────────────────────────────────────────
# Use calibration on LR
calibrated = CalibratedClassifierCV(lr, method="isotonic", cv=3)
calibrated.fit(X_scaled, y)
prob_cal = calibrated.predict_proba(X_scaled)[:, 1]

df["prob_calibrated"] = prob_cal
df["expected_value"] = (df["prob_calibrated"] * df["outcome_mfe"].fillna(0) 
                        - (1 - df["prob_calibrated"]) * df["outcome_mae"].fillna(0))

print("\n=== Expected Value (top 5 trades) ===")
print(df.nlargest(5, "expected_value")[["symbol","probability","prob_calibrated","expected_value"]])

# ── SHAP (optional, if installed) ─────────────────────────────────────────────
try:
    import shap
    explainer = shap.TreeExplainer(rf)
    shap_values = explainer.shap_values(X_scaled)
    # Summary plot for class 1 (TP1 hit)
    shap.summary_plot(shap_values[1], X_scaled, feature_names=features, show=False)
    import matplotlib.pyplot as plt
    plt.savefig("shap_summary.png", bbox_inches="tight")
    print("SHAP summary saved as shap_summary.png")
except ImportError:
    print("SHAP not installed – skipping")
except Exception as e:
    print(f"SHAP error: {e}")

print("\nDone.")
