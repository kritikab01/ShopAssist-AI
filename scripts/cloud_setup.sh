#!/usr/bin/env bash
# Puts ShopAssist into the cloud n8n on Render (Groq + Cohere instead of Ollama). Run on your laptop:
#
#     bash scripts/cloud_setup.sh
#
# Needs in .env: CLOUD_N8N_URL, CLOUD_N8N_API_KEY, GROQ_API_KEY, COHERE_API_KEY, PINECONE_API_KEY, POSTGRES_* (Supabase).
# Your local setup (N8N_URL / N8N_API_KEY for localhost:5679) is not changed. Safe to run again.
set -uo pipefail
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
val()  { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/ #.*//' -e 's/^["'\'']//' -e 's/["'\'']$//' | xargs; }

echo "1/5  Keys in .env"
[ -f .env ] || fail ".env is missing (copy .env.example to .env)"
python3 -c "import pg8000" 2>/dev/null || pip3 install -q pg8000 || fail "run: pip3 install pg8000"
for k in CLOUD_N8N_URL CLOUD_N8N_API_KEY GROQ_API_KEY COHERE_API_KEY PINECONE_API_KEY POSTGRES_HOST POSTGRES_PASSWORD; do
  v="$(val "$k")"
  if [ -z "$v" ] || [[ "$v" == *REPLACE_ME* ]]; then fail "$k is not set in .env (see docs/DEPLOY.md, section C)"; fi
done
CLOUD_URL="$(val CLOUD_N8N_URL)"; CLOUD_URL="${CLOUD_URL%/}"
ok "all keys present"

echo "2/5  Cloud n8n at $CLOUD_URL (a sleeping free instance needs up to 2 minutes to wake up)"
up=""
for _ in $(seq 1 40); do curl -s -m 5 -o /dev/null -w '%{http_code}' "$CLOUD_URL/healthz" | grep -q 200 && { up=1; break; }; sleep 3; done
[ -n "$up" ] || fail "n8n on Render does not answer. Render dashboard -> shopassist-n8n -> Logs"
ok "cloud n8n is up"

echo "3/5  Database (Supabase): tables + n8n schema"
python3 scripts/setup_database.py >/tmp/shopassist_db.log 2>&1 || { tail -5 /tmp/shopassist_db.log; fail "database not reachable (check POSTGRES_* in .env)"; }
ok "database ready"

echo "4/5  Pinecone index shopassist-cloud (1024 dims, Cohere)"
python3 scripts/setup_pinecone.py --cloud || fail "Pinecone setup failed (check PINECONE_API_KEY)"

echo "5/5  Import and publish the 7 cloud workflows"
# The cloud n8n reaches Supabase directly, never the laptop-only overrides.
N8N_URL="$CLOUD_URL" N8N_PUBLIC_URL="$CLOUD_URL" N8N_API_KEY="$(val CLOUD_N8N_API_KEY)" \
POSTGRES_HOST_FOR_N8N="" POSTGRES_PORT_FOR_N8N="" OLLAMA_URL_FOR_N8N="" \
  python3 scripts/import_to_n8n.py --cloud --publish || fail "import failed (check CLOUD_N8N_API_KEY)"

cat <<MSG

Done. Last steps:
  1. Open $CLOUD_URL -> workflow 01 -> Execute workflow, then 02 (fills the knowledge base, once).
  2. Vercel -> project shop.assist.ai -> Settings -> Environment Variables -> N8N_URL = $CLOUD_URL
     (Production), then Deployments -> Redeploy. Check: https://shopassistai.vercel.app/api/status
MSG
