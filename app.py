"""HackSphere 3.0 - Flask entry point (local dev and Catalyst AppSail).

Local:    python app.py                     -> http://localhost:9000
AppSail:  startup command `python3 -u app.py`; the port comes from X_ZOHO_CATALYST_LISTEN_PORT.
Nothing here requires QuickML credentials to start.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

import predict as P
from backend import activity_log as log
from backend import service
from backend.service import ValidationError

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB uploads


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, quickml_configured=P.quickml_configured(),
                   model_in_use="quickml" if P.quickml_configured() else "local-fallback")


@app.get("/api/sample")
def sample():
    import pandas as pd
    df = pd.read_csv(os.path.join(HERE, "backend", "data", "sample_24h.csv"))
    return jsonify(rows=df.to_dict("records"))


@app.get("/api/log")
def get_log():
    return jsonify(log=log.entries())


@app.post("/api/forecast")
def forecast():
    """JSON {rows:[...], soc:90}  or  multipart form with a CSV in field 'file' (+ optional 'soc')."""
    try:
        if "file" in request.files:
            raw = service.frame_from_csv(request.files["file"].read())
            soc = request.form.get("soc", 90)
        else:
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise ValidationError("Send JSON like {\"rows\": [...]} or upload a CSV file.")
            raw = service.frame_from_rows(body.get("rows"))
            soc = body.get("soc", 90)
        try:
            soc = float(soc)
        except (TypeError, ValueError):
            raise ValidationError("Starting battery charge must be a number.")
        return jsonify(service.run_forecast(raw, soc))
    except ValidationError as e:
        log.add("error", str(e))
        return jsonify(ok=False, error=str(e), log=log.entries()), 400
    except Exception as e:  # noqa: BLE001
        log.add("error", f"Unexpected server error: {type(e).__name__}")
        return jsonify(ok=False, error="Unexpected server error. Check the server logs.", log=log.entries()), 500


@app.errorhandler(413)
def too_large(_):
    return jsonify(ok=False, error="File too large (limit 2 MB)."), 413


if __name__ == "__main__":
    port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", os.getenv("PORT", "9000")))
    try:  # waitress is a production-grade server; fall back to Flask's own if not installed
        from waitress import serve
        print(f"Serving with waitress on 0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port)
