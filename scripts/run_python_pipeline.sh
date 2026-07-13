#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

model_args=()
if [[ -n "${OPENROUTER_MODEL_OVERRIDE:-}" ]]; then
  model_args=(--model "$OPENROUTER_MODEL_OVERRIDE")
fi

PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline run "${model_args[@]}" "$@"
