import io

import pytest

from app import app
from backend import activity_log


@pytest.fixture
def client():
    activity_log.clear()
    app.config["TESTING"] = True
    return app.test_client()


def sample_rows(client):
    return client.get("/api/sample").get_json()["rows"]


def test_index_and_static(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200


def test_health_without_credentials(client):
    d = client.get("/api/health").get_json()
    assert d["ok"] and d["quickml_configured"] is False and d["model_in_use"] == "local-fallback"


def test_sample_has_24_rows(client):
    assert len(sample_rows(client)) == 24


def test_forecast_json_shape_and_rules(client):
    d = client.post("/api/forecast", json={"rows": sample_rows(client), "soc": 80}).get_json()
    assert d["ok"] and d["source"] == "local-fallback" and "NOT a QuickML" in d["source_label"]
    assert len(d["rows"]) == 24 and d["summary"]["hours"] == 24
    for r in d["rows"]:
        if 18 <= r["hour"] <= 22 or r["predicted_demand_kw"] > 160:
            assert r["grid_mode"] == "Renewable Storage Mode"
        else:
            assert r["grid_mode"] == "Main Grid Mode"
        assert r["overload_alert"] == (r["predicted_demand_kw"] >= 200)
    assert d["log"]


def test_forecast_csv_upload(client):
    csv = "timestamp,ambient_temp_c,humidity_pct,solar_irradiance_wm2\n2026-07-01 00:00:00,25,60,0\n2026-07-01 01:00:00,,60,0\n"
    d = client.post("/api/forecast", data={"file": (io.BytesIO(csv.encode()), "t.csv")},
                    content_type="multipart/form-data").get_json()
    assert d["ok"] and len(d["rows"]) == 2
    assert any("interpolated" in w for w in d["warnings"])


def test_missing_column_is_a_helpful_400(client):
    csv = "timestamp,ambient_temp_c\n2026-07-01 00:00:00,25\n"
    r = client.post("/api/forecast", data={"file": (io.BytesIO(csv.encode()), "t.csv")}, content_type="multipart/form-data")
    assert r.status_code == 400 and "humidity_pct" in r.get_json()["error"]


@pytest.mark.parametrize("payload", [{}, {"rows": []}, {"rows": "x"}, {"rows": [1, 2]}])
def test_bad_json_is_400(client, payload):
    assert client.post("/api/forecast", json=payload).status_code == 400


def test_non_json_body_is_400(client):
    assert client.post("/api/forecast", data="nope", content_type="text/plain").status_code == 400


def test_empty_file_and_bad_soc(client):
    r = client.post("/api/forecast", data={"file": (io.BytesIO(b""), "e.csv")}, content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/api/forecast", json={"rows": sample_rows(client), "soc": 5})
    assert r.status_code == 400
    r = client.post("/api/forecast", json={"rows": sample_rows(client), "soc": "abc"})
    assert r.status_code == 400


def test_too_many_rows(client):
    rows = [{"timestamp": "2026-07-01 00:00:00", "ambient_temp_c": 20, "humidity_pct": 50, "solar_irradiance_wm2": 0}] * 1001
    assert client.post("/api/forecast", json={"rows": rows}).status_code == 400


def test_log_endpoint(client):
    client.post("/api/forecast", json={"rows": sample_rows(client)})
    assert client.get("/api/log").get_json()["log"]
