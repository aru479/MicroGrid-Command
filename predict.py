"""HackSphere 3.0 - predict.py   (single source of truth for cleaning, features and inference)

Contract used by test_eval.py and the hidden evaluator (unchanged from the starter):
    predict(input_df: pandas.DataFrame) -> numpy.ndarray   # one kW value per row, same order

Pipeline
  1. clean()           validate + impute raw telemetry (never drops or reorders rows)
  2. build_features()  numeric features derived from the timestamp + weather columns.
                       `timestamp` itself is NOT sent to the model.
  3. QuickML endpoint  if configured via environment variables (see .env.example)
  4. local fallback    ridge model embedded below, used when QuickML is not configured or fails.
                       It is ALWAYS reported as "local-fallback", never as QuickML.

CLI:  python predict.py --input sample_test_input.csv --output predictions.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

try:  # optional: load a local .env during development (never required)
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

PLACEHOLDER = "YOUR_PUBLISHED_QUICKML_ENDPOINT_URL_HERE"  # kept from the starter template
RAW_COLS = ["ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"]
HOUR_COLS = [f"h_{h}" for h in range(24)]
# Default feature vector (matches ml/prepare_training_data.py and the embedded fallback model)
FEATURES = HOUR_COLS + RAW_COLS + ["cool_deg", "cool_deg_day", "cool_deg_eve", "temp_day"]
# Every column build_features can compute; QUICKML_FEATURES may pick any subset, in any order.
EXTRA_COLS = ["hour", "day_of_week", "month"]
ALL_COLUMNS = FEATURES + EXTRA_COLS

# Filled in by `python ml/train_local.py` (ridge regression on FEATURES).
_EMBEDDED_MODEL = {"intercept": 145.26178448563155, "coef": {"h_0": -53.99726019316304, "h_1": -52.89397393722502, "h_2": -52.1374850240836, "h_3": -52.96544414232079, "h_4": -53.378262839536276, "h_5": -53.068717989080476, "h_6": -10.456299981507136, "h_7": 28.702972951873722, "h_8": 29.822785460581088, "h_9": 30.767499974531926, "h_10": 0.8337726748923948, "h_11": -0.04330397283711875, "h_12": -0.8840932738255259, "h_13": -0.061036556241808745, "h_14": 0.03211685688178011, "h_15": -0.7009667953691006, "h_16": 0.4460986778341552, "h_17": -0.32978497606859636, "h_18": 54.32004337409469, "h_19": 55.39529475726733, "h_20": 55.38158254991048, "h_21": 54.608539210497696, "h_22": 53.89161896409689, "h_23": -33.285695769864475, "ambient_temp_c": -0.03673413853589672, "humidity_pct": -0.020090502463434353, "solar_irradiance_wm2": -0.0004624555884415813, "cool_deg": 9.033197202286798, "cool_deg_day": -0.452635967076788, "cool_deg_eve": -0.5200019212706958, "temp_day": 0.0408042560258798}}  # __MODEL__


# ----------------------------------------------------------------------------- config
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def quickml_configured() -> bool:
    url = _env("QUICKML_ENDPOINT_URL")
    return bool(url) and url != PLACEHOLDER


def selected_features() -> list[str]:
    """Columns sent to QuickML. Must equal the columns the QuickML model was trained on."""
    raw = _env("QUICKML_FEATURES")
    cols = [c.strip() for c in raw.split(",") if c.strip()] if raw else list(RAW_COLS)
    unknown = [c for c in cols if c not in ALL_COLUMNS]
    if unknown:
        raise ValueError(f"QUICKML_FEATURES has unknown column(s) {unknown}; allowed: {ALL_COLUMNS}")
    return cols


# ----------------------------------------------------------------------------- cleaning
def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and impute. Row count and order are preserved."""
    missing = [c for c in ["timestamp"] + RAW_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    df = df.copy().reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in RAW_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # physical sanity bounds -> NaN, then imputed
    df.loc[~df["ambient_temp_c"].between(-40, 60), "ambient_temp_c"] = np.nan
    df.loc[~df["humidity_pct"].between(0, 100), "humidity_pct"] = np.nan
    df.loc[~df["solar_irradiance_wm2"].between(0, 1500), "solar_irradiance_wm2"] = np.nan
    defaults = {"ambient_temp_c": 25.0, "humidity_pct": 60.0, "solar_irradiance_wm2": 0.0}
    for c in RAW_COLS:
        df[c] = df[c].interpolate(limit_direction="both").fillna(defaults[c])
    if df["timestamp"].isna().any():  # continue hourly from the previous valid timestamp
        ts = df["timestamp"].copy()
        for i in range(len(ts)):
            if pd.isna(ts.iloc[i]):
                prev = ts.iloc[i - 1] if i > 0 else pd.NaT
                ts.iloc[i] = prev + pd.Timedelta(hours=1) if pd.notna(prev) else pd.Timestamp("2000-01-01")
        df["timestamp"] = ts
    return df


# ----------------------------------------------------------------------------- features
def compute_columns(df: pd.DataFrame) -> pd.DataFrame:
    """All derivable numeric columns (superset of FEATURES). Used for training AND inference."""
    d = clean(df)
    hour = d["timestamp"].dt.hour
    t = d["ambient_temp_c"]
    cool = np.maximum(0.0, t - 24.0)
    day = hour.between(7, 17).astype(float)
    eve = hour.between(18, 22).astype(float)
    out = pd.DataFrame({f"h_{h}": (hour == h).astype(float) for h in range(24)})
    out["ambient_temp_c"] = t
    out["humidity_pct"] = d["humidity_pct"]
    out["solar_irradiance_wm2"] = d["solar_irradiance_wm2"]
    out["cool_deg"] = cool
    out["cool_deg_day"] = cool * day
    out["cool_deg_eve"] = cool * eve
    out["temp_day"] = t * day
    out["hour"] = hour.astype(float)
    out["day_of_week"] = d["timestamp"].dt.dayofweek.astype(float)
    out["month"] = d["timestamp"].dt.month.astype(float)
    return out.reset_index(drop=True)


def build_features(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    return compute_columns(df)[columns or FEATURES]


# ----------------------------------------------------------------------------- inference
def _local_predict(df: pd.DataFrame) -> np.ndarray:
    feats = build_features(df)
    m = _EMBEDDED_MODEL
    if m is None:  # run `python ml/train_local.py`; until then use the starter's dummy heuristic
        hours = feats[HOUR_COLS].values.argmax(axis=1)
        return 120.0 + 30.0 * np.sin(2 * np.pi * (hours - 6) / 24) + feats["cool_deg"].values * 8.5
    coef = np.array([m["coef"][f] for f in FEATURES])
    return feats[FEATURES].values @ coef + m["intercept"]


def _parse_response(result) -> np.ndarray:
    """Tolerant parser. VERIFY against your endpoint's *Sample Response* and tighten if needed."""
    if isinstance(result, dict):
        for k in ("predictions", "prediction", "result", "data", "output"):
            if k in result:
                return _parse_response(result[k])
        if len(result) == 1:
            return _parse_response(next(iter(result.values())))
        raise ValueError(f"unrecognised response keys {list(result)[:6]}")
    if isinstance(result, list):
        if result and isinstance(result[0], dict):
            key = "target_demand_kw" if "target_demand_kw" in result[0] else next(iter(result[0]))
            return np.array([r[key] for r in result], dtype=float)
        return np.array(result, dtype=float).ravel()
    return np.array([result], dtype=float)


def _access_token() -> str:
    """Prefer a refresh-token flow (access tokens are short-lived); else a static QUICKML_TOKEN."""
    rt, cid, cs = _env("ZOHO_REFRESH_TOKEN"), _env("ZOHO_CLIENT_ID"), _env("ZOHO_CLIENT_SECRET")
    if rt and cid and cs:
        base = _env("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
        r = requests.post(
            f"{base}/oauth/v2/token",
            data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": cid, "client_secret": cs},
            timeout=10,
        )
        r.raise_for_status()
        body = r.json()
        if "access_token" not in body:
            raise ValueError(f"OAuth refresh failed: {body.get('error', 'no access_token in response')}")
        return body["access_token"]
    return _env("QUICKML_TOKEN")


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    token = _access_token()
    if token:
        h["Authorization"] = f"Zoho-oauthtoken {token}"
    if _env("QUICKML_ENDPOINT_KEY"):
        h["X-QUICKML-ENDPOINT-KEY"] = _env("QUICKML_ENDPOINT_KEY")
    if _env("CATALYST_ORG"):
        h["CATALYST-ORG"] = _env("CATALYST_ORG")
    return h


def _call_quickml(df: pd.DataFrame) -> np.ndarray:
    """Call QuickML using the payload shapes supported by this project.

    single_data (default): one request per row, body {"data": {timestamp, features...}}
      This matches the Sample Request shown for the user's published endpoint.
    batch_data: one request with body {"data": [{...}, {...}]}; use only if the endpoint
      explicitly supports batch rows.
    single: legacy flat one-row body {feature: value, ...}.
    """
    url, headers, timeout = _env("QUICKML_ENDPOINT_URL"), _headers(), float(_env("QUICKML_TIMEOUT", "20"))
    cleaned = clean(df)
    features = build_features(cleaned, selected_features()).to_dict(orient="records")
    # The endpoint's Sample Request contains timestamp inside `data`, even though timestamp
    # is not a numeric model feature in the trained pipeline.
    rows = []
    for i, row in enumerate(features):
        rows.append({"timestamp": cleaned.loc[i, "timestamp"].strftime("%Y-%m-%d %H:%M:%S"), **row})
    mode = _env("QUICKML_PAYLOAD_MODE", "single_data")

    def post(body):
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return _parse_response(r.json())

    if mode == "batch_data":
        preds = post({"data": rows})
    elif mode == "single_data":
        with ThreadPoolExecutor(max_workers=8) as ex:
            parts = list(ex.map(lambda row: post({"data": row}), rows))
        if any(len(p) != 1 for p in parts):
            raise ValueError("single-row response did not contain exactly one value")
        preds = np.array([p[0] for p in parts], dtype=float)
    elif mode == "single":
        flat_rows = [{k: v for k, v in row.items() if k != "timestamp"} for row in rows]
        with ThreadPoolExecutor(max_workers=8) as ex:
            parts = list(ex.map(post, flat_rows))
        if any(len(p) != 1 for p in parts):
            raise ValueError("single-row response did not contain exactly one value")
        preds = np.array([p[0] for p in parts], dtype=float)
    else:
        raise ValueError(f"QUICKML_PAYLOAD_MODE must be 'single_data', 'single' or 'batch_data', got '{mode}'")
    if len(preds) != len(rows) or not np.isfinite(preds).all():
        raise ValueError("endpoint returned the wrong number of values or non-finite values")
    return preds


def predict_with_meta(input_df: pd.DataFrame):
    """Returns (predictions, meta). meta['source'] is 'quickml' or 'local-fallback'."""
    meta = {"source": "local-fallback", "fallback_reason": None, "quickml_configured": quickml_configured()}
    preds = None
    if quickml_configured():
        try:
            preds = _call_quickml(input_df)
            meta["source"] = "quickml"
        except Exception as e:  # noqa: BLE001  - never crash the evaluator
            status = getattr(getattr(e, "response", None), "status_code", None)
            meta["fallback_reason"] = f"{type(e).__name__}" + (f" (HTTP {status})" if status else "") + f": {str(e)[:160]}"
            print(f"Warning: QuickML call failed - {meta['fallback_reason']}. Using local fallback.", file=sys.stderr)
    else:
        meta["fallback_reason"] = "QuickML not configured (QUICKML_ENDPOINT_URL is not set)"
    if preds is None:
        preds = _local_predict(input_df)
    preds = np.clip(np.nan_to_num(np.asarray(preds, dtype=float), nan=120.0, posinf=300.0, neginf=0.0), 0.0, None)
    return preds, meta


def predict(input_df: pd.DataFrame):
    """Parameters: input_df with columns ['timestamp','ambient_temp_c','humidity_pct','solar_irradiance_wm2'].
    Returns: numpy.ndarray of predicted demand (kW), one per input row."""
    return predict_with_meta(input_df)[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="HackSphere demand prediction")
    ap.add_argument("--input", default="sample_test_input.csv")
    ap.add_argument("--output", default="predictions.csv")
    args = ap.parse_args()
    frame = pd.read_csv(args.input)
    values, info = predict_with_meta(frame)
    pd.DataFrame({"timestamp": frame["timestamp"], "target_demand_kw": np.round(values, 2)}).to_csv(
        args.output, index=False)
    print(f"Wrote {len(values)} predictions to {args.output}  [source: {info['source']}]")
    if info["fallback_reason"]:
        print(f"Note: {info['fallback_reason']}")
