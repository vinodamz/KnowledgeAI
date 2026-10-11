#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose --env-file .env -f deploy/compose.yml exec api python -m knowledge_ai.cli "$@"
