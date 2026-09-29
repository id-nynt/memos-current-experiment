#!/usr/bin/env bash
set -Eeuo pipefail
trap 'code=$?; echo "FAIL: initial Python setup stopped (exit $code)"; exit "$code"' ERR
umask 077
cd -- "$(dirname -- "$0")/.."
command -v python3 >/dev/null || { echo 'FAIL: install Python 3.11+ and python3-venv'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source scripts/_common.sh
if ! "$PYTHON" -c 'import importlib.metadata; assert importlib.metadata.version("PyYAML")=="6.0.2"' 2>/dev/null; then
  "$PYTHON" -m pip install 'PyYAML==6.0.2'
fi
"$PYTHON" -B tools/server_prepare.py
