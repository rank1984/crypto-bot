import pandas as pd, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import LabelEncoder

df = pd.read_csv("learning_dataset.csv")
df = df[df["decision"] == "BUY"].dropna(subset=["target"])

cat_cols = ["is_compressed", "btc_regime", "setup"]
for c in cat_cols:
    if c in df.columns:
        df[c] = LabelEncoder().fit_transform(df[c].astype(str))

features = ["probability","flow_score","rs_1h","oi_change","rvol",
            "is_compressed","market_health","news_score"]
X = df[features].fillna(0)
y = df["target"]

# Logistic Regression
lr = LogisticRegression(max_iter=1000).fit(X, y)
print("=== Logistic Regression Coefficients ===")
for f, coef in zip(features, lr.coef_[0]):
    print(f"{f:20s}: {coef:+.3f}")

# Random Forest
rf = RandomForestClassifier().fit(X, y)
print("\n=== Random Forest Importance ===")
for f, imp in sorted(zip(features, rf.feature_importances_), key=lambda x: -x[1]):
    print(f"{f:20s}: {imp:.3f}")
