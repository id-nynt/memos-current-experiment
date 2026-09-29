#!/usr/bin/env bash
source "$(dirname -- "$0")/_common.sh"
"$PYTHON" -B tools/study_execution.py validate "${1:-all}"
