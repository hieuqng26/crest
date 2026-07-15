#!/usr/bin/env bash
#
# cleanup.sh — tear down the attached verify container and its image. The running
# mst-* stack is never touched. Test rows written to the shared dev DB are append-only
# and left as-is (delete them via the API first if you want a pristine DB).
#
# Env overrides: NAME (default worktree-verify-backend), TAG (default worktree-dev/backend:latest)
#
set -euo pipefail

NAME="${NAME:-worktree-verify-backend}"
TAG="${TAG:-worktree-dev/backend:latest}"

docker rm -f "$NAME"   >/dev/null 2>&1 && echo "removed container $NAME" || echo "no container $NAME"
docker image rm "$TAG" >/dev/null 2>&1 && echo "removed image $TAG"       || echo "no image $TAG"

# Drop any stale cookie jars this session created.
rm -f "${TMPDIR:-/tmp}"/crest-api-*.cookies 2>/dev/null || true
echo "done — the running stack is unchanged."
