#!/usr/bin/env bash
# ShopAssist in one command (Docker Desktop must be running):   bash scripts/up.sh
#
# 1. starts Postgres (with schema + fake data), n8n and the web app   (docker compose)
# 2. first run only: asks you to create the n8n owner account + API key (n8n has no way to script this)
# 3. creates the Pinecone index, imports all 7 workflows, creates credentials, publishes them
# 4. runs the health check
# Safe to run again at any time (e.g. after git pull).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Docker is not installed: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker Desktop is not running - open it and try again."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  # point the scripts at the Postgres inside docker compose instead of Supabase
  sed -i.bak -e 's#^POSTGRES_HOST=.*#POSTGRES_HOST=localhost#' -e 's#^POSTGRES_PORT=.*#POSTGRES_PORT=5433#' \
    -e 's#^POSTGRES_USER=.*#POSTGRES_USER=postgres#' -e 's#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=shopassist#' \
    -e 's#^POSTGRES_SSL=.*#POSTGRES_SSL=disable#' -e 's#^\# POSTGRES_HOST_FOR_N8N=#POSTGRES_HOST_FOR_N8N=#' \
    -e 's#^\# POSTGRES_PORT_FOR_N8N=#POSTGRES_PORT_FOR_N8N=#' .env && rm -f .env.bak
  echo "Created .env for the Docker setup (local Postgres). Add your PINECONE_API_KEY to it."
fi

echo "==> Starting Postgres, n8n and the web app ..."
docker compose up -d --build --wait

if grep -qE '^N8N_API_KEY=(REPLACE_ME)?[[:space:]]*$' .env; then
  cat <<MSG

One-time step (n8n cannot do this by script):
  1. Open http://localhost:5679 and create your owner account.
  2. Settings -> n8n API -> Create an API key -> copy it.
  3. Put it in .env as  N8N_API_KEY=...   and run  bash scripts/up.sh  again.
MSG
  exit 0
fi

if ! curl -s -m 3 http://localhost:11434/api/tags >/dev/null; then
  echo "NOTE: Ollama is not running. Mac: open the Ollama app (ollama.com), then: ollama pull qwen2.5:3b && ollama pull nomic-embed-text"
  echo "      Linux without Ollama: docker compose --profile ollama up -d && docker compose exec ollama ollama pull qwen2.5:3b"
fi

if ! grep -qE '^PINECONE_API_KEY=(pcsk_REPLACE_ME)?[[:space:]]*$' .env; then
  python3 scripts/setup_pinecone.py || true
fi
echo "==> Importing and publishing the 7 workflows ..."
python3 scripts/import_to_n8n.py --publish
echo "==> Health check ..."
python3 scripts/doctor.py || true
cat <<MSG

Done.
  Web app (chat + manager dashboard): http://localhost:8501
  n8n:                                http://localhost:5679
First time: in n8n open workflow 01 -> Execute workflow, then 02 (fills the knowledge base; safe to re-run).
MSG
