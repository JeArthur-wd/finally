#!/usr/bin/env bash
# Start FinAlly in Docker (macOS/Linux). Idempotent.
# Usage: scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT=8000
URL="http://localhost:${PORT}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help)
      echo "Usage: $0 [--build] [--no-open]"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not on PATH." >&2
  exit 1
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "WARNING: .env not found - created it from .env.example."
    echo "         Add your OPENROUTER_API_KEY to .env to enable the AI chat."
  else
    echo "Error: neither .env nor .env.example found in $ROOT_DIR" >&2
    exit 1
  fi
fi

if [ "$BUILD" -eq 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" .
fi

# Replace any existing container (running or stopped); the volume is kept.
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Removing existing container '$CONTAINER'..."
  docker rm -f "$CONTAINER" >/dev/null
fi

echo "Starting container '$CONTAINER'..."
docker run -d \
  --name "$CONTAINER" \
  -v "${VOLUME}:/app/db" \
  -p "${PORT}:8000" \
  --env-file .env \
  "$IMAGE" >/dev/null

echo "Waiting for FinAlly to become ready..."
for _ in $(seq 1 60); do
  if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "FinAlly is running at ${URL}"
echo "Stop it with: scripts/stop_mac.sh"

if [ "$OPEN" -eq 1 ]; then
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
