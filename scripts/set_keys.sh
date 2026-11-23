#!/usr/bin/env bash
# Puts your keys into .env for you. Run on your Mac:
#
#     bash scripts/set_keys.sh
#
# For each key it opens the web page where you get it, then asks you to paste it.
# What you paste is hidden (nothing shows while you type or paste: that is normal) and goes only into .env
# on your Mac. Press Enter without pasting to keep the value that is already there.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
# Older .env files may not have the cloud lines yet.
for k in CLOUD_N8N_URL CLOUD_N8N_API_KEY GROQ_API_KEY COHERE_API_KEY; do
  grep -qE "^$k=" .env || echo "$k=REPLACE_ME" >> .env
done

current() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/ #.*//' | xargs; }
is_set()  { local v; v="$(current "$1")"; [ -n "$v" ] && [[ "$v" != *REPLACE_ME* ]]; }
masked()  { local v; v="$(current "$1")"; printf '%s...%s' "${v:0:4}" "${v: -4}"; }

save() {  # save NAME VALUE  (replaces the NAME= line in .env, keeps everything else)
  KEY="$1" VALUE="$2" python3 - <<'PY'
import os, re
k, v = os.environ["KEY"], os.environ["VALUE"].strip()
lines = open(".env").read().splitlines()
lines = [f"{k}={v}" if re.match(rf"^{k}=", l) else l for l in lines]
open(".env", "w").write("\n".join(lines) + "\n")
PY
}

ask() {  # ask NAME "where to get it" URL [visible]
  local name="$1" help="$2" url="$3" visible="${4:-}" v
  echo
  echo "== $name"
  if is_set "$name"; then echo "   already set ($(masked "$name")). Press Enter to keep it."; fi
  echo "   $help"
  [ -n "$url" ] && { open "$url" 2>/dev/null || true; echo "   (opening $url)"; }
  if [ -n "$visible" ]; then read -r -p "   Paste $name: " v; else read -r -s -p "   Paste $name (hidden): " v; echo; fi
  v="$(printf '%s' "$v" | tr -d '[:space:]')"
  if [ -n "$v" ]; then save "$name" "$v"; echo "   saved"; else echo "   kept"; fi
}

echo "This puts your cloud keys into .env. Log in on each page that opens, create the key, copy it, paste it here."

ask GROQ_API_KEY   "Groq -> API Keys -> Create API Key (starts with gsk_)"        "https://console.groq.com/keys"
ask COHERE_API_KEY "Cohere -> API keys -> copy the Trial key"                     "https://dashboard.cohere.com/api-keys"
is_set PINECONE_API_KEY || \
ask PINECONE_API_KEY "Pinecone -> API Keys -> copy the key (starts with pcsk_)"   "https://app.pinecone.io"

echo
echo "== Render (n8n in the cloud)"
if is_set CLOUD_N8N_API_KEY; then
  echo "   CLOUD_N8N_API_KEY already set ($(masked CLOUD_N8N_API_KEY))."
else
  echo "   If you have not created n8n on Render yet: Render -> New -> Blueprint -> ShopAssist-AI."
  echo "   It asks for these values (copy them from here):"
  echo "     WEBHOOK_URL            = https://shopassist-n8n.onrender.com/   (use the link Render shows you, with / at the end)"
  echo "     DB_POSTGRESDB_HOST     = $(current POSTGRES_HOST)"
  echo "     DB_POSTGRESDB_USER     = $(current POSTGRES_USER)"
  if command -v pbcopy >/dev/null && is_set POSTGRES_PASSWORD; then
    printf '%s' "$(current POSTGRES_PASSWORD)" | pbcopy
    echo "     DB_POSTGRESDB_PASSWORD = (copied to your clipboard: just press Cmd+V in Render)"
  else
    echo "     DB_POSTGRESDB_PASSWORD = the POSTGRES_PASSWORD line in .env"
  fi
  open "https://dashboard.render.com/select-repo?type=blueprint" 2>/dev/null || true
  echo "   When Render shows Live, open your n8n link, create your login,"
  echo "   then Settings -> n8n API -> Create an API key."
  read -r -p "   Press Enter when you have the n8n API key ... " _
fi
ask CLOUD_N8N_URL     "Your Render n8n link, e.g. https://shopassist-n8n.onrender.com (no / at the end)" "" visible
save CLOUD_N8N_URL "$(current CLOUD_N8N_URL | sed 's:/*$::')"
ask CLOUD_N8N_API_KEY "n8n (Render) -> Settings -> n8n API -> Create an API key"  ""

echo
echo "Check:"
missing=0
for k in GROQ_API_KEY COHERE_API_KEY PINECONE_API_KEY CLOUD_N8N_URL CLOUD_N8N_API_KEY POSTGRES_HOST POSTGRES_PASSWORD; do
  if is_set "$k"; then printf '  \033[32mOK\033[0m   %s\n' "$k"; else printf '  \033[31mMISSING\033[0m %s\n' "$k"; missing=1; fi
done
echo
if [ "$missing" = 0 ]; then
  echo "All keys are in .env. Next:  bash scripts/cloud_setup.sh"
else
  echo "Run  bash scripts/set_keys.sh  again to fill the missing ones."
  echo "(POSTGRES_* come from your Supabase setup: supabase.com -> project -> Connect -> Session pooler.)"
fi
