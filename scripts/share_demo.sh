#!/usr/bin/env bash
# Give your running ShopAssist web app a temporary public https link (for an interview / demo), free,
# no account: Cloudflare Quick Tunnel.            bash scripts/share_demo.sh
#
# Only the web app (port 8501) is shared - NOT the n8n editor, NOT the database. The link works while this
# command and your laptop are running; Ctrl+C stops it and the link dies.
# Safety while public: the manager dashboard needs ADMIN_KEY (this script creates one in .env if missing),
# orders are only shown with the phone's last 4 digits (5 wrong tries lock the order), each visitor can send
# 20 messages per 5 minutes, all data is fictional.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${APP_PORT:-8501}"

if ! command -v cloudflared >/dev/null; then
  echo "Install cloudflared first:  brew install cloudflared     (Windows/Linux: see developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)"
  exit 1
fi

touch .env
if ! grep -qE '^ADMIN_KEY=.+' .env; then
  KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
  grep -q '^ADMIN_KEY=' .env && sed -i.bak "s#^ADMIN_KEY=.*#ADMIN_KEY=$KEY#" .env && rm -f .env.bak || echo "ADMIN_KEY=$KEY" >> .env
  echo "Created ADMIN_KEY in .env (the dashboard asks for it)."
  RESTART=1
fi
echo "Dashboard key (keep it for yourself): $(grep '^ADMIN_KEY=' .env | cut -d= -f2)"

if [ "${RESTART:-0}" = 1 ] || ! curl -s -m 2 "http://localhost:$PORT/api/health" >/dev/null; then
  pkill -f "app/server.py" 2>/dev/null || true
  if docker compose ps app 2>/dev/null | grep -q running; then
    ADMIN_KEY="$(grep '^ADMIN_KEY=' .env | cut -d= -f2)" docker compose up -d app
  else
    nohup python3 app/server.py > /tmp/shopassist-app.log 2>&1 &
  fi
  sleep 2
fi
curl -s -m 5 "http://localhost:$PORT/api/health" >/dev/null || { echo "The web app does not start - see /tmp/shopassist-app.log"; exit 1; }

echo "Opening the tunnel ... the public link (https://....trycloudflare.com) appears below. Ctrl+C to stop."
cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT"
