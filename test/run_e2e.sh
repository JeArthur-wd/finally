#!/usr/bin/env bash
# Run the FinAlly Playwright E2E suite against a throwaway container.
#
# Usage: test/run_e2e.sh [--build] [extra playwright args...]
#   --build   force a rebuild of the `finally` image
# Env:
#   BASE_URL  if set, skip Docker entirely and test that URL instead
#   E2E_PORT  host port for the container (default 8001)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="finally"
CONTAINER="finally-e2e"
VOLUME="finally-e2e-data"
PORT="${E2E_PORT:-8001}"

BUILD=0
PW_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    *) PW_ARGS+=("$arg") ;;
  esac
done

cd "$SCRIPT_DIR"
if [ ! -d node_modules/@playwright/test ]; then
  echo ">> Installing test dependencies"
  npm install && npx playwright install chromium || exit 1
fi

if [ -n "${BASE_URL:-}" ]; then
  echo ">> BASE_URL set; testing $BASE_URL without Docker"
  npx playwright test "${PW_ARGS[@]}"
  exit $?
fi

cleanup() {
  echo ">> Tearing down $CONTAINER and $VOLUME"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [ "$BUILD" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo ">> Building image $IMAGE"
  docker build -t "$IMAGE" "$REPO_ROOT" || exit 1
fi

cleanup  # remove leftovers from a previous aborted run
echo ">> Starting $CONTAINER on port $PORT (LLM_MOCK=true)"
docker run -d --name "$CONTAINER" \
  -p "$PORT:8000" \
  -v "$VOLUME:/app/db" \
  -e LLM_MOCK=true \
  -e MASSIVE_API_KEY= \
  -e OPENROUTER_API_KEY= \
  "$IMAGE" >/dev/null || exit 1

URL="http://localhost:$PORT"
echo ">> Waiting for $URL/api/health"
for i in $(seq 1 60); do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then
    echo ">> App is healthy"
    break
  fi
  if [ "$i" = 60 ]; then
    echo "!! App did not become healthy in 60s. Container logs:"
    docker logs "$CONTAINER" 2>&1 | tail -50
    exit 1
  fi
  sleep 1
done

BASE_URL="$URL" npx playwright test "${PW_ARGS[@]}"
STATUS=$?
if [ "$STATUS" != 0 ]; then
  echo ">> Tests failed; last container logs:"
  docker logs "$CONTAINER" 2>&1 | tail -80
fi
exit $STATUS
