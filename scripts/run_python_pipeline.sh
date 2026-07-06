#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHONPATH=src python3 -m electromotiv_pipeline run \
  --model "${OPENROUTER_MODEL_OVERRIDE:-deepseek/deepseek-v4-flash}" \
  "$@"
