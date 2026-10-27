#!/usr/bin/env bash
# Builds build/appsail/ : app code + Linux-compatible dependencies, ready for `catalyst init` / `catalyst deploy`.
# Why: pip on a Mac installs macOS wheels, which will NOT run on AppSail (Linux). We ask pip for Linux wheels.
#
# Usage:  ./scripts/build_appsail.sh [PYTHON_VERSION]      e.g. ./scripts/build_appsail.sh 3.11
# Pick a version AppSail supports (3.10-3.13 per the docs) and use the same one when you run `catalyst init`.
set -euo pipefail
cd "$(dirname "$0")/.."
PYVER="${1:-3.11}"
OUT="build/appsail"
mkdir -p "$OUT"

# refresh code; keep app-config.json if the Catalyst CLI already generated one here
for f in app.py predict.py requirements.txt; do   # training data is not needed at runtime
  cp "$f" "$OUT/"
done
rm -rf "$OUT/backend" "$OUT/templates" "$OUT/static"
cp -R backend templates static "$OUT/"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
[ -f "$OUT/app-config.json" ] || cp app-config.json "$OUT/app-config.json"

echo "Installing Linux (manylinux x86_64) wheels for Python $PYVER into $OUT ..."
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt --target "$OUT" \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --implementation cp --python-version "$PYVER" --only-binary=:all: --upgrade

find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} + || true
echo; echo "Build size:"; du -sh "$OUT"
echo "AppSail's default disk is 256 MB - if the size above is near that, raise the disk in the console."
echo "Done. Next: see README 'Deploy to Catalyst AppSail'."
