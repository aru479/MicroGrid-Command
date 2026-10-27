#!/usr/bin/env bash
# Checks a RUNNING app. Usage: ./scripts/smoke_test.sh [BASE_URL]   (default http://localhost:9000)
set -u
BASE="${1:-http://localhost:9000}"
fail=0
check() { if eval "$2"; then echo "PASS  $1"; else echo "FAIL  $1"; fail=1; fi; }
check "health endpoint"    "curl -sf $BASE/api/health | grep -q '\"ok\":true'"
check "dashboard loads"    "curl -sf $BASE/ | grep -q 'MicroGrid Command'"
check "sample endpoint"    "curl -sf $BASE/api/sample | grep -q timestamp"
check "forecast works"     "curl -sf -X POST $BASE/api/forecast -H 'Content-Type: application/json' -d \"{\\\"rows\\\": \$(curl -sf $BASE/api/sample | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)[\"rows\"]))')}\" | grep -q '\"ok\":true'"
check "bad input -> 400"   "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/api/forecast -H 'Content-Type: application/json' -d '{}')\" = 400 ]"
echo; echo "Which model is serving?"; curl -s $BASE/api/health; echo
exit $fail
