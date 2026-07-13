#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/docker_common.sh

"$DOCKER_BIN_RESOLVED" compose --env-file .env -f infra/docker-compose.yml up -d --wait
"$DOCKER_BIN_RESOLVED" compose --env-file .env -f infra/docker-compose.yml ps
