"""Trains the LOCAL FALLBACK model (not the QuickML model) and records honest validation metrics.

Validation is chronological: the last 20% of train_telemetry.csv (later in time) is held out, which
mirrors how the hidden test set follows the training period and avoids leakage from shuffling.
Final fallback coefficients are re-fit on all rows and embedded into predict.py.

Requires scikit-learn:  pip install -r requirements-ml.txt
Run from project root:  python ml/train_local.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import GradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402

import predict  # noqa: E402

raw = pd.read_csv("train_telemetry.csv")
raw["_ts"] = pd.to_datetime(raw["timestamp"])
raw = raw.sort_values("_ts").reset_index(drop=True)
X = predict.build_features(raw)
y = raw["target_demand_kw"].values
n = int(len(X) * 0.8)
rmse = lambda p, t: float(np.sqrt(np.mean((np.asarray(p) - np.asarray(t)) ** 2)))  # noqa: E731

hour_mean = pd.Series(y[:n]).groupby(raw["_ts"].dt.hour.values[:n]).mean()
baseline = raw["_ts"].dt.hour.values[n:]
metrics = {
    "validation": "chronological hold-out (last 20% of train_telemetry.csv)",
    "train_rows": int(n), "holdout_rows": int(len(X) - n),
    "holdout_temp_mean_c": round(float(raw["ambient_temp_c"].values[n:].mean()), 2),
    "train_temp_mean_c": round(float(raw["ambient_temp_c"].values[:n].mean()), 2),
    "rmse_hour_mean_baseline": round(rmse([hour_mean[h] for h in baseline], y[n:]), 3),
}
for a in (0.1, 1.0, 10.0):
    m = Ridge(alpha=a).fit(X[:n], y[:n])
    metrics[f"rmse_ridge_alpha_{a}"] = round(rmse(m.predict(X[n:]), y[n:]), 3)
gb_cols = ["hour", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"]
Xg = predict.build_features(raw, gb_cols)
gb = GradientBoostingRegressor(n_estimators=500, max_depth=4, learning_rate=0.03, subsample=0.8, random_state=0)
gb.fit(Xg[:n], y[:n])
metrics["rmse_gradient_boosting"] = round(rmse(gb.predict(Xg[n:]), y[n:]), 3)

final = Ridge(alpha=1.0).fit(X, y)
model = {"intercept": float(final.intercept_), "coef": {f: float(c) for f, c in zip(predict.FEATURES, final.coef_)}}
with open("predict.py") as fh:
    src = fh.read()
src = re.sub(r"_EMBEDDED_MODEL = .*?# __MODEL__", lambda _: f"_EMBEDDED_MODEL = {json.dumps(model)}  # __MODEL__",
             src, flags=re.S)
with open("predict.py", "w") as fh:
    fh.write(src)
with open("ml/metrics.json", "w") as fh:
    json.dump(metrics, fh, indent=2)
print(json.dumps(metrics, indent=2))
print("Embedded fallback coefficients into predict.py. These metrics are for the LOCAL model only.")
