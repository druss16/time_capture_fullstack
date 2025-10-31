#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt pyinstaller

# Console binary (so it can log to stdout/err if you run it manually)
pyinstaller \
  --onefile \
  --name TimeTrackerAgent \
  main.py

mkdir -p dist_out
cp dist/TimeTrackerAgent dist_out/
echo "✅ Built agent → $(pwd)/dist_out/TimeTrackerAgent"