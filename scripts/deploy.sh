#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/compose.prod.yaml"
EXPECTED_BRANCH="${ADC_DEPLOY_BRANCH:-main}"

cd "$REPO_ROOT"

if [[ "$(git branch --show-current)" != "$EXPECTED_BRANCH" ]]; then
  echo "Refusing deployment: expected branch $EXPECTED_BRANCH." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing deployment: the server checkout has local changes." >&2
  exit 1
fi

if docker compose -f "$COMPOSE_FILE" ps --status running --quiet adc-evidence | grep -q .; then
  echo "Creating a transaction-consistent SQLite backup..."
  docker compose -f "$COMPOSE_FILE" exec -T adc-evidence \
    python -m adc_evidence.backup \
    --database /app/data/processed/adc_evidence.db \
    --output-dir /app/backups
fi

git fetch origin "$EXPECTED_BRANCH"
git merge --ff-only "origin/$EXPECTED_BRANCH"

export ADC_GIT_SHA="$(git rev-parse --short=12 HEAD)"
export ADC_IMAGE_TAG="$ADC_GIT_SHA"

docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

HEALTH_ENDPOINT="$(
  docker compose -f "$COMPOSE_FILE" port adc-evidence 8501 | tail -n 1
)"
if [[ -z "$HEALTH_ENDPOINT" ]]; then
  docker compose -f "$COMPOSE_FILE" ps
  echo "Deployment did not publish the Streamlit health port." >&2
  exit 1
fi
HEALTH_URL="http://${HEALTH_ENDPOINT}/_stcore/health"

for _ in {1..30}; do
  if curl --fail --silent --show-error \
    "$HEALTH_URL" >/dev/null; then
    echo "Deployment healthy at commit $ADC_GIT_SHA."
    exit 0
  fi
  sleep 2
done

docker compose -f "$COMPOSE_FILE" ps
docker compose -f "$COMPOSE_FILE" logs --tail=100 adc-evidence
echo "Deployment failed its health check." >&2
exit 1
