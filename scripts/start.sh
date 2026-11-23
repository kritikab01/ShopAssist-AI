#!/usr/bin/env bash
# ShopAssist on your Mac, one command (local n8n on :5679 + Ollama + Supabase from .env):
#
#     bash scripts/start.sh
#
# Checks each part in order, starts what is stopped, re-publishes the workflows and opens the app at
# http://localhost:8501. Safe to run again at any time. It never touches the other n8n on port 5688.
set -uo pipefail
cd "$(dirname "$0")/.."

N8N_CONTAINER="${N8N_CONTAINER:-shopassist-n8n}"
N8N_IMAGE="${N8N_IMAGE:-2.48.7}"
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
wait_for() {  # wait_for URL SECONDS
  for _ in $(seq 1 "$2"); do curl -s -m 2 -o /dev/null "$1" && return 0; sleep 1; done; return 1
}

echo "1/6  Settings file (.env)"
[ -f .env ] || fail ".env is missing. Copy .env.example to .env and fill in your keys (docs/RUNBOOK.md)."
python3 -c "import pg8000" 2>/dev/null || pip3 install -q pg8000 || fail "could not install pg8000 (run: pip3 install pg8000)"
ok ".env found, pg8000 installed"

echo "2/6  Ollama (local AI)"
if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null; then
  open -a Ollama 2>/dev/null || true
  wait_for http://localhost:11434/api/tags 30 || fail "Ollama is not running. Open the Ollama app (ollama.com) and run this again."
fi
for m in qwen2.5:3b nomic-embed-text; do
  curl -s http://localhost:11434/api/tags | grep -q "\"$m" || ollama pull "$m" || fail "could not download model $m"
done
ok "Ollama running with qwen2.5:3b and nomic-embed-text"

echo "3/6  n8n on http://localhost:5679"
if ! curl -s -m 2 -o /dev/null http://localhost:5679/healthz; then
  docker info >/dev/null 2>&1 || { open -a Docker 2>/dev/null || true; echo "       waiting for Docker Desktop ..."; \
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done; }
  docker info >/dev/null 2>&1 || fail "Docker Desktop is not running. Open it and run this again."
  if docker inspect "$N8N_CONTAINER" >/dev/null 2>&1; then
    docker start "$N8N_CONTAINER" >/dev/null || fail "could not start the n8n container '$N8N_CONTAINER'. Check: docker logs $N8N_CONTAINER"
  else
    # First run on this Mac: create the n8n container (its data lives in the Docker volume shopassist_n8n_data).
    echo "       no container '$N8N_CONTAINER' yet, creating it (n8n $N8N_IMAGE, first download takes a few minutes)"
    echo "       (already have n8n under another name? Ctrl+C, then: N8N_CONTAINER=<name> bash scripts/start.sh)"
    docker run -d --name "$N8N_CONTAINER" --restart unless-stopped \
      -p 127.0.0.1:5679:5678 \
      -e WEBHOOK_URL=http://localhost:5679/ -e N8N_SECURE_COOKIE=false \
      -e GENERIC_TIMEZONE=Asia/Kolkata -e N8N_DIAGNOSTICS_ENABLED=false \
      -v shopassist_n8n_data:/home/node/.n8n \
      "n8nio/n8n:$N8N_IMAGE" >/dev/null || fail "could not create the n8n container (see the Docker message above)"
    NEW_N8N=1
  fi
  wait_for http://localhost:5679/healthz 120 || fail "n8n did not start. Check: docker logs $N8N_CONTAINER"
  if [ -n "${NEW_N8N:-}" ]; then
    echo
    echo "  n8n is new on this Mac. Open http://localhost:5679, create your login, then"
    echo "  Settings -> n8n API -> Create an API key. Put it in .env as N8N_API_KEY=... and run this again."
    exit 0
  fi
fi
ok "n8n is up"

echo "4/6  Database (Postgres / Supabase) and tables"
python3 scripts/setup_database.py >/tmp/shopassist_db.log 2>&1 \
  || { tail -5 /tmp/shopassist_db.log; fail "database not reachable. If you use Supabase, open supabase.com -> project shopassist -> Restore if it is paused."; }
ok "database ready"

echo "5/6  Import and publish the 7 workflows"
python3 scripts/import_to_n8n.py --publish || fail "import failed (check N8N_API_KEY in .env)"
python3 scripts/doctor.py || true

echo "6/6  Web app"
if lsof -ti :8501 >/dev/null 2>&1; then
  echo "       an old copy of the app is on port 8501, restarting it"
  kill "$(lsof -ti :8501)" 2>/dev/null || true; sleep 1
fi
( sleep 2; open http://localhost:8501 2>/dev/null || true ) &
echo
echo "  Chat + dashboard: http://localhost:8501   (Ctrl+C stops the app)"
echo "  n8n:              http://localhost:5679"
echo
exec python3 app/server.py
