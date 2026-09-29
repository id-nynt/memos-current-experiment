#!/usr/bin/env bash
source "$(dirname -- "$0")/_common.sh"
"$PYTHON" -B tools/study_execution.py smoke "${1:-all}"
