#!/usr/bin/env bash
# Start LeadsHunter Model Training Ground web console on 127.0.0.1:8791
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -e . -q
exec python -m uvicorn csl_lab.webapp.app:app --host 127.0.0.1 --port 8791
