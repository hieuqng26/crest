#!/usr/bin/env bash
#
# attach-backend.sh — build the backend image from the CURRENT worktree and run it as
# one extra backend container attached to the ALREADY-RUNNING CREST debug stack's
# network, reusing that stack's MSSQL / Redis / MinIO. Non-disruptive: the running
# stack's containers and image are never touched.
#
# Safe only for code-only changes. If your branch adds an Alembic migration, this will
# apply it to the shared dev DB on boot — use a parallel stack instead (see
# references/parallel-stack.md).
#
# Overrides via env vars:
#   PORT     host port to publish the backend on            (default 5002)
#   TAG      image tag to build/run for the worktree copy   (default worktree-dev/backend:latest)
#   NAME     container name                                 (default worktree-verify-backend)
#   NETWORK  docker network to attach to  (default: auto-detected from running backend)
#   ENVFILE  path to env/.env.dev         (default: auto-located via git worktree list)
#
set -euo pipefail

[[ "${1:-}" == "--help" || "${1:-}" == "-h" ]] && { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

PORT="${PORT:-5002}"
TAG="${TAG:-worktree-dev/backend:latest}"
NAME="${NAME:-worktree-verify-backend}"

# Repo root of the current worktree (build context lives under it).
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# --- locate the gitignored env file -----------------------------------------------
# env/.env.dev is gitignored, so it exists only in the checkout where the user created
# it (usually the MAIN worktree). Search this worktree, then every other worktree.
if [[ -z "${ENVFILE:-}" ]]; then
  if [[ -f "$ROOT/env/.env.dev" ]]; then
    ENVFILE="$ROOT/env/.env.dev"
  else
    while read -r _ _ wt; do
      [[ -f "$wt/env/.env.dev" ]] && { ENVFILE="$wt/env/.env.dev"; break; }
    done < <(git worktree list --porcelain | awk '/^worktree /{print "wt "$0}')
  fi
fi
# Fallback: parse `git worktree list` classic format if the above found nothing.
if [[ -z "${ENVFILE:-}" ]]; then
  while read -r wt _; do
    [[ -f "$wt/env/.env.dev" ]] && { ENVFILE="$wt/env/.env.dev"; break; }
  done < <(git worktree list)
fi
[[ -n "${ENVFILE:-}" && -f "$ENVFILE" ]] || {
  echo "ERROR: could not locate env/.env.dev. Set ENVFILE=/path/to/env/.env.dev." >&2
  exit 1
}
echo "env file:   $ENVFILE"

# --- auto-detect the running stack's network --------------------------------------
if [[ -z "${NETWORK:-}" ]]; then
  SRC="$(docker ps --format '{{.Names}}' | grep -iE 'backend' | grep -v "$NAME" | head -1 || true)"
  [[ -n "$SRC" ]] || { echo "ERROR: no running backend container found; is the stack up? Set NETWORK=..." >&2; exit 1; }
  NETWORK="$(docker inspect "$SRC" -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)"
fi
echo "network:    $NETWORK  (from running stack)"
echo "image tag:  $TAG      (distinct — won't overwrite mst-dev/backend:latest)"
echo "port:       http://localhost:$PORT"

# --- build the worktree image ------------------------------------------------------
echo "--- building backend image from $ROOT/services/server ..."
docker build -t "$TAG" -f services/server/Dockerfile services/server

# --- run it attached to the running stack -----------------------------------------
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  --network "$NETWORK" \
  --env-file "$ENVFILE" \
  -e SERVICE_NAME=backend -e DEBUG_PORT=5678 \
  -e CELERY_BROKER_URL='redis://default:Ey%40123%21@redis:6379/0' \
  -e CELERY_RESULT_BACKEND='redis://default:Ey%40123%21@redis:6379/0' \
  -e MINIO_ENDPOINT=minio:9000 -e MINIO_ACCESS_KEY=minioadmin -e MINIO_SECRET_KEY=minioadmin \
  -p "$PORT:5000" \
  "$TAG" >/dev/null

echo "--- container $NAME started; waiting for /api/ping ..."
for _ in $(seq 1 60); do
  if [[ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/api/ping" 2>/dev/null)" == "200" ]]; then
    echo "READY → http://localhost:$PORT   (login with the seeded admin from $ENVFILE)"
    exit 0
  fi
  sleep 3
done
echo "WARN: /api/ping did not return 200 in time. Check: docker logs $NAME" >&2
exit 1
