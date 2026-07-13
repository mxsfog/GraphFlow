#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Файл .env не найден. Сначала выполните: bash scripts/bootstrap_local.sh" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Виртуальное окружение не найдено. Сначала выполните: bash scripts/bootstrap_local.sh" >&2
  exit 1
fi

mkdir -p .runtime/logs .runtime/tmp .runtime/cache/uv .runtime/cache/npm
export UV_CACHE_DIR="$PWD/.runtime/cache/uv"
export npm_config_cache="$PWD/.runtime/cache/npm"
export ELECTROMOTIV_TEMP_DIR="$PWD/.runtime/tmp"

bash scripts/start_stack.sh

for attempt in $(seq 1 60); do
  if PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline ensure-schema \
    >.runtime/logs/ensure-schema.log 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "OrientDB не готова. Лог: .runtime/logs/ensure-schema.log" >&2
    exit 1
  fi
  sleep 2
done

PYTHONPATH=src .venv/bin/python -m electromotiv_pipeline graph-api \
  --host 127.0.0.1 \
  --port 8090 \
  >.runtime/logs/graph-api.log 2>&1 &
api_pid=$!

(cd frontend && npm run dev -- --force >../.runtime/logs/frontend.log 2>&1) &
frontend_pid=$!

cleanup() {
  kill "$api_pid" "$frontend_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Graph API: http://127.0.0.1:8090"
echo "Frontend:  http://127.0.0.1:5173"
echo "Логи: .runtime/logs"
echo "Логин/пароль Graph API берутся из GRAPH_API_USERNAME и GRAPH_API_PASSWORD в .env."

wait -n "$api_pid" "$frontend_pid"
