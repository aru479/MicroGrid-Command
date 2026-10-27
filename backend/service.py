"""Input validation + forecast orchestration. The prediction itself is predict.predict_with_meta()."""
from __future__ import annotations

import io

import pandas as pd

import predict as P
from backend import activity_log as log
from backend.controller import Battery, dispatch, summarize

MAX_ROWS = 1000
REQUIRED = ["timestamp"] + P.RAW_COLS


class ValidationError(ValueError):
    """Raised for bad user input; the message is safe to show in the UI."""


def frame_from_csv(data: bytes) -> pd.DataFrame:
    if not data.strip():
        raise ValidationError("The uploaded file is empty.")
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"Could not read the file as CSV ({type(e).__name__}).") from e


def frame_from_rows(rows) -> pd.DataFrame:
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        raise ValidationError("Provide at least one telemetry row.")
    return pd.DataFrame(rows)


def validate(raw: pd.DataFrame):
    """Returns (frame with normalised column names, list of warnings). Raises ValidationError."""
    raw = raw.copy()
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValidationError(f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(REQUIRED)}.")
    if raw.empty:
        raise ValidationError("The file has a header but no data rows.")
    if len(raw) > MAX_ROWS:
        raise ValidationError(f"Too many rows ({len(raw)}). The maximum is {MAX_ROWS}.")
    raw = raw[REQUIRED]
    warnings = []
    ts = pd.to_datetime(raw["timestamp"], errors="coerce")
    if ts.isna().any():
        warnings.append(f"{int(ts.isna().sum())} row(s) have an unreadable timestamp "
                        "(expected YYYY-MM-DD HH:MM:SS); they were placed one hour after the previous row.")
    num = raw[P.RAW_COLS].apply(pd.to_numeric, errors="coerce")
    bad = int(num.isna().any(axis=1).sum())
    if bad:
        warnings.append(f"{bad} row(s) have missing or non-numeric weather values; they were interpolated.")
    out_of_range = int(((num["humidity_pct"] < 0) | (num["humidity_pct"] > 100) | (num["ambient_temp_c"] < -40)
                        | (num["ambient_temp_c"] > 60) | (num["solar_irradiance_wm2"] < 0)).sum())
    if out_of_range:
        warnings.append(f"{out_of_range} row(s) have physically implausible values; they were treated as missing.")
    if ts.notna().all():
        if ts.duplicated().any():
            warnings.append("Duplicate timestamps found; every row is still forecast.")
        steps = ts.diff().dropna()
        if len(steps) and (steps != pd.Timedelta(hours=1)).any():
            warnings.append("Timestamps are not strictly hourly or not in order; forecasts are per row.")
    if len(raw) != 24:
        warnings.append(f"{len(raw)} rows supplied (a full forecast window is 24 hourly rows).")
    return raw, warnings


def run_forecast(raw: pd.DataFrame, start_soc: float = 90.0) -> dict:
    if not 10.0 <= start_soc <= 100.0:
        raise ValidationError("Starting battery charge must be between 10 and 100 %.")
    raw, warnings = validate(raw)
    cleaned = P.clean(raw)
    preds, meta = P.predict_with_meta(raw)
    rows = dispatch(list(cleaned["timestamp"]), list(preds), Battery(soc_pct=start_soc))
    for r, (_, c) in zip(rows, cleaned.iterrows()):
        r.update(ambient_temp_c=round(float(c["ambient_temp_c"]), 2), humidity_pct=round(float(c["humidity_pct"]), 2),
                 solar_irradiance_wm2=round(float(c["solar_irradiance_wm2"]), 1))
    summary = summarize(rows)
    label = ("Catalyst QuickML (live endpoint)" if meta["source"] == "quickml"
             else "Local fallback model - NOT a QuickML prediction")
    log.add("info", f"Forecast of {len(rows)} row(s) via {meta['source']}; peak {summary['peak_kw']} kW")
    for w in warnings:
        log.add("warn", w)
    if meta["source"] != "quickml":
        log.add("warn", f"Fallback used: {meta['fallback_reason']}")
    if summary["overload_hours"]:
        log.add("crit", f"{summary['overload_hours']} hour(s) at or above 200 kW - critical overload alert")
    return {"ok": True, "source": meta["source"], "source_label": label, "fallback_reason": meta["fallback_reason"],
            "warnings": warnings, "rows": rows, "summary": summary, "log": log.entries()}
