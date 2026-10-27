# MicroGrid Command — HackSphere 3.0

Energy-demand forecasting and Main-Grid / Renewable-Storage dispatch dashboard for Zoho Catalyst
(QuickML for the model, AppSail for the web app).

* Forecasts demand (kW) per hourly row from `timestamp`, `ambient_temp_c`, `humidity_pct`, `solar_irradiance_wm2`.
* Applies the transition rules: demand > 160 kW **or** hour 18–22 inclusive → *Renewable Storage Mode*, otherwise *Main Grid Mode*; demand ≥ 200 kW → *Critical Overload Alert* (independent of mode).
* Dashboard: load curve with thresholds, battery state of charge, dispatch table, CSV upload + validation, editable input table, activity log, downloadable `predictions.csv`.
* The header always shows **where predictions came from**: `Catalyst QuickML` or `local fallback (not QuickML)`.

## Project layout
```
HackSphere/
├── app.py                  Flask entry point (the only server entry point)
├── predict.py              evaluator contract: predict(df) -> ndarray; cleaning, features, QuickML client, fallback
├── test_eval.py            provided self-tester (unchanged)
├── sample_test_input.csv   provided sample (unchanged)      train_telemetry.csv  provided training data (unchanged)
├── backend/                controller.py (grid rules + battery), service.py (validation), activity_log.py, data/sample_24h.csv
├── templates/index.html    static/css/style.css    static/js/app.js
├── ml/                     prepare_training_data.py (file for QuickML), train_local.py (fallback model + metrics.json)
├── tests/                  test_predict.py, test_controller.py, test_api.py
├── scripts/                build_appsail.sh (Linux-ready build), smoke_test.sh (checks a running app)
├── docs/predict_starter_original.py.txt   the starter predict.py you supplied, kept for reference
├── app-config.json  requirements*.txt  .env.example  .gitignore
```

## What was audited (and what could not be)
* I could **not** access your Mac. I only saw the files uploaded to this conversation: the starter `predict.py`, `test_eval.py`, `sample_test_input.csv`, `train_telemetry.csv`, and the problem statement. I never saw your `predictions.csv` or any QuickML endpoint details.
* `test_eval.py`, `sample_test_input.csv` and `train_telemetry.csv` are copied **byte-for-byte** (MD5 checked).
* The uploaded `predict.py` is the unmodified starter template. It was replaced because of verified gaps: no `--input/--output` CLI (the problem statement documents one), no feature engineering (it posted raw rows including `timestamp`), and its fallback is a hard-coded heuristic. The new `predict.py` keeps the same `predict(input_df)` signature and return type and still passes `test_eval.py`.
* Data finding: training data averages ~15.9 °C in its first 80% while the later 20% averages ~29.1 °C, and the provided test file is also a later, hotter period. Models that cannot extrapolate (tree ensembles) do worse on such a shift — see metrics below.

## Local fallback model — real validation numbers
From `ml/metrics.json` (chronological hold-out: last 20% of `train_telemetry.csv`, never shuffled):

| Model | Hold-out RMSE (kW) |
|---|---|
| Hour-of-day mean baseline | 48.76 |
| Gradient boosting (hour + weather) | 12.06 |
| **Ridge on engineered features (used as fallback)** | **8.43** |

These numbers describe the **local fallback only**. Your QuickML model's accuracy is unknown until you train it; use QuickML's own validation report and compare it with the table above. Features carry the timestamp as 24 hour one-hot columns plus cooling-degree terms (`predict.FEATURES`); the raw `timestamp` is never sent to a model.

## Run locally on macOS (step by step)
Open **Terminal**, then:
```bash
cd ~/HackSphere                      # adjust if the folder lives elsewhere (e.g. ~/Desktop/HackSphere)
python3 --version                    # want 3.10 or newer; if older: brew install python@3.11
python3 -m venv .venv                # create a virtual environment
source .venv/bin/activate            # activate it (prompt shows "(.venv)")
pip install --upgrade pip
pip install -r requirements-dev.txt  # app + pytest
python3 test_eval.py                 # provided self-tester -> must end with SUCCESS
python3 -m pytest -q                 # project tests
python3 predict.py --input sample_test_input.csv --output predictions.csv
python3 app.py                       # start the app -> open http://localhost:9000
```
In a second Terminal tab (same folder, `source .venv/bin/activate` not needed): `./scripts/smoke_test.sh`
Stop the app with `Ctrl+C`. The app starts and works **without any credentials**, using the labelled fallback.

## Connect QuickML (manual console steps)
1. `pip install -r requirements-ml.txt` then `python3 ml/prepare_training_data.py` → creates `ml/output/train_features.csv` (numeric features + `target_demand_kw`).
2. Catalyst console → **QuickML** → create a dataset from that file → build a regression pipeline, target `target_demand_kw`. Prefer a linear / regularised-linear algorithm if offered; the test period is hotter than most of the training data.
3. Train, then **Endpoints → Create Endpoint → Publish**. On the endpoint page copy: **Endpoint URL**, **endpoint key**, your **org ID**, and the **Sample Request** and **Sample Response**.
4. Compare the Sample Request with the payload this repo sends (`predict._call_quickml`):
   * This repo is configured for the endpoint sample request shown in the console: `QUICKML_PAYLOAD_MODE=single_data`, one POST per row with `{"data": {"timestamp": "...", "ambient_temp_c": ..., "humidity_pct": ..., "solar_irradiance_wm2": ...}}`.
   * The current QuickML model was trained on the three raw numeric weather columns; set `QUICKML_FEATURES=ambient_temp_c,humidity_pct,solar_irradiance_wm2`. Timestamp is included in the request envelope because the endpoint's Sample Request shows it, but is not used as a numeric model feature.
   * `QUICKML_PAYLOAD_MODE=batch_data` sends one `{"data": [ ... ]}` request and should be used only if the endpoint explicitly supports a batch list. `single` remains available for legacy flat requests.
   * `_parse_response` accepts the endpoint response envelope `{"result": [ ... ]}` shown in the console as well as common variants. A real call must still be verified using your credentials.
   * If you retrain the QuickML model with different columns, set `QUICKML_FEATURES` to exactly those input column names (any of `predict.ALL_COLUMNS`).
5. Auth: QuickML REST endpoints use Zoho OAuth2 (scope `QuickML.deployment.READ`) plus the `X-QUICKML-ENDPOINT-KEY` and `CATALYST-ORG` headers. Create a Self Client in the Zoho API console to obtain a client ID/secret and refresh token; set the data-centre `ZOHO_ACCOUNTS_URL` (`.com`, `.in`, `.eu`, …).
6. Local test: `cp .env.example .env`, fill it in, then `python3 predict.py` — it prints `[source: quickml]` only if the endpoint really answered, otherwise `[source: local-fallback]` with the reason.

Never commit `.env`; `.gitignore` excludes it. **Evaluator note:** the hidden evaluation runs `predict.py` somewhere you don't control, where your environment variables may be absent; in that case it silently uses the fallback. Ask the organisers how credentials should be supplied.

## Deploy to Catalyst AppSail
Facts checked against the Catalyst docs: AppSail Python managed runtimes are 3.10–3.13; the app must listen on `X_ZOHO_CATALYST_LISTEN_PORT` (default 9000; `app.py` does this); startup commands are executed **without a shell**; `app-config.json` keys are `command`, `buildPath`, `stack`, `env_variables`, `memory`; you must bundle your own dependencies; default memory/disk are 512 MB / 256 MB.

```bash
npm install -g zcatalyst-cli          # Catalyst CLI (needs Node.js)
catalyst login
./scripts/build_appsail.sh 3.11       # builds build/appsail/ with LINUX wheels (Mac wheels would not run on AppSail)
catalyst init                         # in the project root: choose/create a project, add AppSail,
                                      #   runtime Python (same version you built for), source directory: build/appsail,
                                      #   startup command: python3 -u app.py
catalyst deploy
```
* `catalyst init` writes `stack`/`buildPath` into `build/appsail/app-config.json`; rerunning `build_appsail.sh` keeps that file. The root `app-config.json` is only a template (no `stack`/`buildPath`, because the CLI fills those in).
* Put QuickML values in the AppSail **Configurations → Environment variables** (or `env_variables`). Don't commit real values.
* Check the build size the script prints against the 256 MB default disk; raise disk/memory in the console if needed.
* The deployed URL (shown after deploy / in the console) is your public app link; run `./scripts/smoke_test.sh https://<your-app-url>` against it.
* Catalyst CLI prompts and flags change; if something differs, `catalyst --help` and the AppSail "Deploy from the CLI" docs win over this README.

## Tests
`python3 -m pytest -q` covers: the `predict()` contract, cleaning, feature schema (no timestamp), QuickML client in both payload modes with mocked HTTP, fallback labelling and failure handling, the 160/200 kW and 18–22 h rules incl. boundaries, battery limits, and every API endpoint incl. error cases.

## What is verified vs not
| Verified in my sandbox | NOT verified |
|---|---|
| 29 tests passing (run with a stand-in runner because pytest could not be installed offline) | Real `pytest` run — please run it on your Mac |
| `test_eval.py` → SUCCESS; CLI writes `predictions.csv` | Any real QuickML endpoint, its payload/response format, or its accuracy |
| Flask app over HTTP: `/`, `/api/*`, CSV upload | Zoho OAuth refresh against real Zoho servers |
| QuickML client against a *local fake* server (checks my client's headers/payload logic only) | Browser rendering of the dashboard / Chart.js (no browser was opened) |
| | `waitress` path, `build_appsail.sh` pip step, Catalyst CLI, deployment — nothing was deployed |

## Manual setup still required
1. Create the Catalyst project; train + publish the QuickML model; copy URL / endpoint key / org ID / sample request+response.
2. Adjust `_call_quickml` / `_parse_response` if the sample request/response differ; set `QUICKML_FEATURES` if you changed the columns.
3. Create the Zoho OAuth client + refresh token; set env vars locally (`.env`) and in AppSail.
4. `catalyst init` + `catalyst deploy`; check the public URL with `scripts/smoke_test.sh`.
5. Push to GitHub (without `.env`) or zip the folder as `TeamName_Submission.zip`; submit app URL + code.

## Assumptions to know
* Battery numbers (800 kWh, 150 kW max discharge, 100 kW max charge, 10 % reserve, 90 % default start) are dashboard assumptions; the problem statement defines none. Edit `backend/controller.py`.
* Activity log is in memory and resets on restart; Catalyst Data Store persistence is not implemented.
