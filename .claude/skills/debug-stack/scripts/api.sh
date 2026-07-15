#!/usr/bin/env bash
#
# api.sh — authenticated requests against a CREST backend (cookie session + CSRF
# double-submit token handled for you). Point it at the attached backend (default
# http://localhost:5002) and drive endpoints.
#
#   api.sh login                 # log in with the seeded admin, persist the session
#   api.sh get    /api/path
#   api.sh post   /api/path '{"json":"body"}'
#   api.sh put    /api/path '{"json":"body"}'
#   api.sh delete /api/path
#
# Env overrides:
#   BASE   backend base URL           (default http://localhost:5002)
#   EMAIL  login email                (default: SEED_ADMIN_EMAIL / "admin")
#   PW     login password             (default: SEED_ADMIN_PASSWORD / "admin")
#
# The cookie jar is per-BASE in $TMPDIR so `login` once, then reuse across calls.
#
set -euo pipefail

BASE="${BASE:-http://localhost:5002}"
EMAIL="${EMAIL:-${SEED_ADMIN_EMAIL:-admin}}"
PW="${PW:-${SEED_ADMIN_PASSWORD:-admin}}"
JAR="${TMPDIR:-/tmp}/crest-api-$(echo "$BASE" | tr -c 'a-zA-Z0-9' '_').cookies"

csrf() { awk '/csrf_access_token/{print $7}' "$JAR" 2>/dev/null | tail -1; }

cmd="${1:-}"; shift || true
case "$cmd" in
  login)
    curl -sS -c "$JAR" -X POST "$BASE/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" -w '\nHTTP %{http_code}\n'
    ;;
  get)
    curl -sS -b "$JAR" "$BASE$1" -w '\nHTTP %{http_code}\n'
    ;;
  post|put)
    curl -sS -b "$JAR" -X "$(echo "$cmd" | tr a-z A-Z)" "$BASE$1" \
      -H 'Content-Type: application/json' -H "X-CSRF-TOKEN: $(csrf)" \
      -d "${2:-{}}" -w '\nHTTP %{http_code}\n'
    ;;
  delete)
    curl -sS -b "$JAR" -X DELETE "$BASE$1" \
      -H "X-CSRF-TOKEN: $(csrf)" -w '\nHTTP %{http_code}\n'
    ;;
  *)
    echo "usage: api.sh {login|get|post|put|delete} <path> [json-body]" >&2
    exit 2
    ;;
esac
