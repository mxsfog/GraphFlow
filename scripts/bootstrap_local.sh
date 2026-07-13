#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Не найдена команда: $1" >&2
    exit 1
  fi
}

require_command python3
require_command npm
require_command node
require_command openssl
require_command uv

if [[ "$PWD" != /mnt/d/* ]]; then
  echo "Проект должен находиться на диске D: путь /mnt/d/..." >&2
  exit 1
fi

node_major="$(node --version | sed 's/^v//' | cut -d. -f1)"
if (( node_major < 22 )); then
  echo "Требуется Node.js 22 или новее." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

python3 - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
text = path.read_text(encoding="utf-8")
replacements = {
    "ORIENTDB_ROOT_PASSWORD=replace_with_strong_local_password": (
        "ORIENTDB_ROOT_PASSWORD=" + secrets.token_urlsafe(24)
    ),
    "GRAPH_API_PASSWORD=replace_with_graph_api_password": (
        "GRAPH_API_PASSWORD=" + secrets.token_urlsafe(24)
    ),
}
for old, new in replacements.items():
    text = text.replace(old, new)
if "GRAPH_API_USERNAME=" not in text:
    text += "\nGRAPH_API_USERNAME=admin\n"
if "GRAPH_API_PASSWORD=" not in text:
    text += "GRAPH_API_PASSWORD=" + secrets.token_urlsafe(24) + "\n"
path.write_text(text, encoding="utf-8")
PY

mkdir -p .runtime/logs .runtime/tmp .runtime/cache/uv .runtime/cache/npm outputs
export UV_CACHE_DIR="$PWD/.runtime/cache/uv"
export npm_config_cache="$PWD/.runtime/cache/npm"
export ELECTROMOTIV_TEMP_DIR="$PWD/.runtime/tmp"

uv sync --frozen --group dev

npm ci --prefix frontend

uv run ruff check src tests
PYTHONPATH=src uv run python -m pytest -q
uv run python -m compileall -q src tests
npm run build --prefix frontend

echo "Локальная сборка завершена."
echo "Для запуска решения выполните: bash scripts/run_local_solution.sh"
