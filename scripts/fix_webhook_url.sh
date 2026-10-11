#!/usr/bin/env bash
# Re-create the n8n Docker container with WEBHOOK_URL set, keeping EVERYTHING else (image, volumes,
# ports, environment, restart policy). Fixes n8n's own chat window: "Error: Failed to receive response".
#
#   bash scripts/fix_webhook_url.sh                    # container shopassist-n8n, port 5679
#   bash scripts/fix_webhook_url.sh my-n8n 5679        # other container name / port
#   bash scripts/fix_webhook_url.sh shopassist-n8n 5679 --dry-run   # only print what it would do
#
# Safe: the old container is STOPPED and RENAMED to <name>-backup-<time>, not deleted. Your workflows and
# credentials live in the volume, which the new container reuses. To undo, see the lines printed at the end.
set -euo pipefail

NAME="${1:-shopassist-n8n}"
PORT="${2:-5679}"
DRY="${3:-}"
URL="http://localhost:${PORT}/"

command -v docker >/dev/null || { echo "docker command not found"; exit 1; }
docker inspect "$NAME" >/dev/null 2>&1 || { echo "No container named '$NAME'. Run: docker ps"; exit 1; }

label() { docker inspect -f "{{index .Config.Labels \"$1\"}}" "$NAME"; }
PROJECT=$(label com.docker.compose.project)
if [ -n "$PROJECT" ]; then
  # Managed by docker compose: add WEBHOOK_URL in a separate override file (your compose file is not edited)
  # and let compose re-create only this service. Volumes (workflows, credentials) are kept.
  WORKDIR=$(label com.docker.compose.project.working_dir)
  SERVICE=$(label com.docker.compose.service)
  CONFIGS=$(label com.docker.compose.project.config_files)
  OVERRIDE="${WORKDIR}/shopassist-webhook.override.yml"
  FILES=()
  IFS=',' read -r -a CFG <<< "$CONFIGS"
  for f in "${CFG[@]}"; do [ -n "$f" ] && FILES+=(-f "$f"); done
  FILES+=(-f "$OVERRIDE")
  echo "Compose project : $PROJECT   service: $SERVICE"
  echo "Compose file(s) : $CONFIGS"
  echo "Override file   : $OVERRIDE  (adds WEBHOOK_URL=${URL})"
  echo "Command         : docker compose -p $PROJECT ${FILES[*]} up -d $SERVICE"
  if [ "$DRY" = "--dry-run" ]; then echo "(dry run - nothing changed)"; exit 0; fi
  [ -d "$WORKDIR" ] || { echo "Compose folder $WORKDIR not found. Add WEBHOOK_URL=${URL} to the n8n service's environment by hand, then: docker compose up -d"; exit 1; }
  printf 'services:\n  %s:\n    environment:\n      WEBHOOK_URL: "%s"\n' "$SERVICE" "$URL" > "$OVERRIDE"
  (cd "$WORKDIR" && docker compose -p "$PROJECT" "${FILES[@]}" up -d "$SERVICE")
  echo -n "Waiting for n8n"
  for _ in $(seq 1 90); do
    if [ "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/rest/settings")" = "200" ]; then echo " - ready."; break; fi
    echo -n "."; sleep 2
  done
  echo "Done. n8n now uses WEBHOOK_URL=${URL}."
  echo "Note: next time you start n8n with plain 'docker compose up -d', add:  -f $(basename "${CFG[0]}") -f $(basename "$OVERRIDE")"
  echo "      (or copy 'WEBHOOK_URL: \"${URL}\"' into the environment of service '$SERVICE' in your compose file)."
  echo "To undo:  rm \"$OVERRIDE\" && (cd \"$WORKDIR\" && docker compose -p $PROJECT ${CFG[*]/#/-f } up -d $SERVICE)"
  exit 0
fi

IMAGE=$(docker inspect -f '{{.Config.Image}}' "$NAME")
RESTART=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$NAME")
ARGS=(-d --name "$NAME")
[ -n "$RESTART" ] && [ "$RESTART" != "no" ] && ARGS+=(--restart "$RESTART")

# ports, e.g. -p 127.0.0.1:5679:5678/tcp
while IFS= read -r p; do [ -n "$p" ] && ARGS+=(-p "$p"); done < <(docker inspect -f \
  '{{range $port, $b := .HostConfig.PortBindings}}{{range $b}}{{if .HostIp}}{{.HostIp}}:{{end}}{{.HostPort}}:{{$port}}{{println}}{{end}}{{end}}' "$NAME")
# volumes and bind mounts (keeps your workflows + credentials)
while IFS= read -r m; do [ -n "$m" ] && ARGS+=(-v "$m"); done < <(docker inspect -f \
  '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}:{{.Destination}}{{println}}{{end}}' "$NAME")
# extra hosts (e.g. host.docker.internal)
while IFS= read -r h; do [ -n "$h" ] && ARGS+=(--add-host "$h"); done < <(docker inspect -f \
  '{{range .HostConfig.ExtraHosts}}{{.}}{{println}}{{end}}' "$NAME")
# environment: everything the container had, except an old WEBHOOK_URL
while IFS= read -r e; do
  case "$e" in ""|WEBHOOK_URL=*) ;; *) ARGS+=(-e "$e") ;; esac
done < <(docker inspect -f '{{range .Config.Env}}{{.}}{{println}}{{end}}' "$NAME")
ARGS+=(-e "WEBHOOK_URL=${URL}")

BACKUP="${NAME}-backup-$(date +%Y%m%d%H%M%S)"
echo "Container : $NAME   image: $IMAGE"
echo "New run   : docker run ${ARGS[*]} $IMAGE" | sed -E 's/((PASSWORD|KEY|TOKEN|SECRET)[A-Z_]*)=[^ ]*/\1=***/g'
if [ "$DRY" = "--dry-run" ]; then echo "(dry run - nothing changed)"; exit 0; fi

docker stop "$NAME" >/dev/null
docker rename "$NAME" "$BACKUP"
if ! docker run "${ARGS[@]}" "$IMAGE" >/dev/null; then
  echo "Starting the new container FAILED - restoring the old one."
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$BACKUP" "$NAME" && docker start "$NAME" >/dev/null
  exit 1
fi

echo -n "Waiting for n8n"
for _ in $(seq 1 90); do
  if [ "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/rest/settings")" = "200" ]; then echo " - ready."; break; fi
  echo -n "."; sleep 2
done
echo
echo "Done. n8n now uses WEBHOOK_URL=${URL} (open workflow 03 -> Open chat and try again)."
echo "Old container kept as '$BACKUP'. When everything works you can remove it:  docker rm $BACKUP"
echo "To undo:  docker rm -f $NAME && docker rename $BACKUP $NAME && docker start $NAME"
