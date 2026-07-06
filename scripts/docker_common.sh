#!/usr/bin/env bash
set -euo pipefail

resolve_docker_bin() {
  if [[ -n "${DOCKER_BIN:-}" ]]; then
    printf '%s\n' "$DOCKER_BIN"
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1; then
    command -v docker
    return 0
  fi

  if [[ -x "/mnt/d/Docker/resources/bin/docker.exe" ]]; then
    printf '%s\n' "/mnt/d/Docker/resources/bin/docker.exe"
    return 0
  fi

  if command -v docker.exe >/dev/null 2>&1; then
    command -v docker.exe
    return 0
  fi

  echo "Docker CLI is not available. Enable Docker Desktop WSL integration or set DOCKER_BIN." >&2
  return 1
}

DOCKER_BIN_RESOLVED="$(resolve_docker_bin)"
