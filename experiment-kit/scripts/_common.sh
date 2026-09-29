#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
mkdir -p results/logs
LOG="results/logs/$(basename -- "$0" .sh)-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
exec > >(tee -a "$LOG") 2>&1
trap 'code=$?; echo "FAIL: command stopped (exit $code). Log: $LOG"; exit "$code"' ERR
if [[ ! -x .venv/bin/python ]]; then
  echo 'FAIL: run bash scripts/server-prepare.sh first'
  exit 1
fi
export PATH="$ROOT/.venv/bin:$PATH"
PYTHON="$ROOT/.venv/bin/python"
