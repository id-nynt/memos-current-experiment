#!/usr/bin/env bash
source "$(dirname -- "$0")/_common.sh"
"$PYTHON" -B tools/study_execution.py export "${1:-all}"
