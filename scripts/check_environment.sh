#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/docker_common.sh

echo "Workspace:"
pwd

echo
echo "Disk for workspace:"
df -h .

echo
echo "Docker:"
"$DOCKER_BIN_RESOLVED" --version || true
"$DOCKER_BIN_RESOLVED" compose version || true
"$DOCKER_BIN_RESOLVED" info --format 'DockerRootDir={{.DockerRootDir}} Driver={{.Driver}} OS={{.OperatingSystem}}' || true

echo
echo "D-only runtime directories:"
find .runtime -maxdepth 3 -type d | sort
