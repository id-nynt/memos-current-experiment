#!/usr/bin/env bash
source "$(dirname -- "$0")/_common.sh"
"$PYTHON" -B tools/study_execution.py study "${1:?Choose batch-1 through batch-5}"
