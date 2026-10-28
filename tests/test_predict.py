import numpy as np
import pandas as pd
import pytest

import predict as P


@pytest.fixture
def sample():
    return pd.read_csv("sample_test_input.csv")


def test_contract_length_order_finite(sample):
    out = P.predict(sample)
    assert isinstance(out, np.ndarray) and len(out) == len(sample)
    assert np.isfinite(out).all() and (out >= 0).all()


def test_unconfigured_is_labelled_fallback(sample):
    _, meta = P.predict_with_meta(sample.head(5))
    assert meta["source"] == "local-fallback" and not meta["quickml_configured"]
    assert "not configured" in meta["fallback_reason"]


def test_clean_preserves_rows_and_imputes():
    df = pd.DataFrame({"timestamp": ["2015-06-17 00:00:00", "bad", "2015-06-17 02:00:00"],
                       "ambient_temp_c": [20, None, 22], "humidity_pct": [50, 999, 60], "solar_irradiance_wm2": [0, -5, 10]})
    out = P.clean(df)
    assert len(out) == 3 and not out[P.RAW_COLS].isna().any().any()
    assert out["timestamp"].iloc[1] == pd.Timestamp("2015-06-17 01:00:00")


def test_features_have_no_timestamp_and_are_numeric(sample):
    f = P.build_features(sample.head(24))
    assert list(f.columns) == P.FEATURES and "timestamp" not in f.columns
    assert f.dtypes.apply(lambda t: np.issubdtype(t, np.number)).all()
    assert (f[P.HOUR_COLS].sum(axis=1) == 1).all()


def test_selected_features_rejects_unknown(monkeypatch):
    monkeypatch.setenv("QUICKML_FEATURES", "hour,nonsense")
    with pytest.raises(ValueError):
        P.selected_features()


def test_missing_column_raises():
    with pytest.raises(ValueError):
        P.predict(pd.DataFrame({"timestamp": ["2015-06-17 00:00:00"]}))


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_quickml_single_mode_is_used_and_labelled(monkeypatch, sample):
    monkeypatch.setenv("USE_QUICKML", "true")
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.invalid/predict")
    monkeypatch.setenv("QUICKML_ENDPOINT_KEY", "k")
    monkeypatch.setenv("CATALYST_ORG", "o")
    monkeypatch.setenv("QUICKML_TOKEN", "t")
    seen = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        seen["headers"], seen["body"] = headers, json
        return FakeResp({"predictions": [123.0]})

    monkeypatch.setattr(P.requests, "post", fake_post)
    out, meta = P.predict_with_meta(sample.head(3))
    assert meta["source"] == "quickml" and meta["fallback_reason"] is None
    assert list(out) == [123.0] * 3
    assert seen["headers"]["X-QUICKML-ENDPOINT-KEY"] == "k" and seen["headers"]["CATALYST-ORG"] == "o"
    assert seen["headers"]["Authorization"] == "Zoho-oauthtoken t"
    assert set(seen["body"]) == {"data"}
    assert set(seen["body"]["data"]) == {"timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"}


def test_quickml_batch_mode(monkeypatch, sample):
    monkeypatch.setenv("USE_QUICKML", "true")
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.invalid/predict")
    monkeypatch.setenv("QUICKML_PAYLOAD_MODE", "batch_data")
    monkeypatch.setattr(P.requests, "post", lambda *a, **k: FakeResp({"result": [1.0, 2.0, 3.0]}))
    out, meta = P.predict_with_meta(sample.head(3))
    assert meta["source"] == "quickml" and list(out) == [1.0, 2.0, 3.0]


def test_quickml_failure_falls_back_with_reason(monkeypatch, sample):
    monkeypatch.setenv("USE_QUICKML", "true")
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.invalid/predict")

    def boom(*a, **k):
        raise P.requests.ConnectionError("no network")

    monkeypatch.setattr(P.requests, "post", boom)
    out, meta = P.predict_with_meta(sample.head(4))
    assert meta["source"] == "local-fallback" and len(out) == 4 and "ConnectionError" in meta["fallback_reason"]


def test_quickml_wrong_length_falls_back(monkeypatch, sample):
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", "https://example.invalid/predict")
    monkeypatch.setenv("QUICKML_PAYLOAD_MODE", "batch_data")
    monkeypatch.setattr(P.requests, "post", lambda *a, **k: FakeResp({"predictions": [1.0]}))
    _, meta = P.predict_with_meta(sample.head(3))
    assert meta["source"] == "local-fallback"
