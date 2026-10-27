"""Builds the file you upload to QuickML:  ml/output/train_features.csv

Features come from predict.compute_columns(), i.e. EXACTLY the same code used at inference.
`timestamp` is not included (QuickML regression needs numeric features); its information is
carried by the derived hour one-hot columns.

Set QUICKML_FEATURES (comma separated) to train on a different subset; whatever you choose here
must also be set in the app's environment so inference sends the same columns.

Run from the project root:   python ml/prepare_training_data.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pandas as pd  # noqa: E402

import predict  # noqa: E402

raw = pd.read_csv("train_telemetry.csv")
if "target_demand_kw" not in raw.columns:
    sys.exit("train_telemetry.csv must contain target_demand_kw")
if raw["target_demand_kw"].isna().any():
    print("Warning: dropping rows with missing target")
    raw = raw.dropna(subset=["target_demand_kw"])
feats = predict.build_features(raw, predict.selected_features())
feats["target_demand_kw"] = raw["target_demand_kw"].values
os.makedirs("ml/output", exist_ok=True)
feats.to_csv("ml/output/train_features.csv", index=False)
print(f"wrote ml/output/train_features.csv  rows={len(feats)}  columns={list(feats.columns)}")
