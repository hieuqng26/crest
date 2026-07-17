#!/usr/bin/env bash
#
# setup-env-prod.sh — create env/.env.prod from the committed template and
# fill in every secret. Run from anywhere; paths are resolved relative to this
# script.
#
#   ./env/setup-env-prod.sh          # create .env.prod (refuses to clobber)
#   ./env/setup-env-prod.sh --force  # regenerate, overwriting existing secrets
#
# Two secrets are PINNED to values baked into docker-compose.prod.yml and are
# NOT randomised — they must match or the app can't authenticate to the service:
#   APP_DB_PASSWORD  == mssql  SA_PASSWORD   (Supersecret@123!)
#   REDIS_PASSWORD   == redis  --requirepass (Ey@2026!)
# If you change them here, change them in docker-compose.prod.yml too.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/.env.example.prod"
TARGET="$SCRIPT_DIR/.env.prod"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

[ -f "$TEMPLATE" ] || { echo "error: template not found: $TEMPLATE" >&2; exit 1; }

if [ -f "$TARGET" ] && [ "$FORCE" -ne 1 ]; then
    echo "error: $TARGET already exists. Re-run with --force to overwrite its secrets." >&2
    exit 1
fi

command -v openssl >/dev/null || { echo "error: openssl is required" >&2; exit 1; }

# --- secret generators -------------------------------------------------------
# hexN: N bytes of randomness as lowercase hex (2N chars). Safe in .env and sed.
hex() { openssl rand -hex "$1"; }

# MSSQL CREATE LOGIN runs with CHECK_POLICY=ON, so the app-DB password must meet
# Windows complexity: >=3 of {upper, lower, digit, symbol} and must NOT contain
# the login name ("crst"). Wrap a random hex core in fixed complexity affixes.
# Charset avoids sed-special chars (& / \) and shell/quote-hostile chars.
mssql_pw() { printf 'Kp%s#7Q' "$(hex 12)"; }

# --- pinned values (must match docker-compose.prod.yml) ----------------------
SA_PASSWORD='Supersecret@123!'
REDIS_PASSWORD='Ey@2026!'

# --- generated secrets -------------------------------------------------------
SECRET_KEY="$(hex 32)"          # Flask session signing key
JWT_SECRET_KEY="$(hex 32)"      # JWT signing key
APP_DB_APP_PASSWORD="$(mssql_pw)"   # 'crst' app login (created by entrypoint.sh)
APM_SECRET_TOKEN="$(hex 16)"    # Elastic APM (only used if monitoring enabled)
SEED_ADMIN_PASSWORD="$(mssql_pw)"   # initial systemadmin login
MCP_AUTH_TOKEN="$(hex 32)"      # remote MCP server bearer token (fails closed)

# --- build the file ----------------------------------------------------------
cp "$TEMPLATE" "$TARGET"

# subst <placeholder> <value> — replace the template placeholder in place.
# '|' delimiter + generated charset guarantee no sed-metacharacter clashes.
subst() { sed -i "s|$1|$2|g" "$TARGET"; }

subst '<flask-secret-key>'    "$SECRET_KEY"
subst '<jwt-secret-key>'      "$JWT_SECRET_KEY"
subst '<mssql-sa-password>'   "$SA_PASSWORD"
subst '<mssql-app-password>'  "$APP_DB_APP_PASSWORD"
subst '<apm-secret-token>'    "$APM_SECRET_TOKEN"
subst '<redis-password>'      "$REDIS_PASSWORD"
subst '<seed-admin-password>' "$SEED_ADMIN_PASSWORD"

# MCP server: the mcp service in docker-compose.prod.yml fails closed without a
# token. Enable it here; identity/allowed-hosts still need real values (below).
cat >> "$TARGET" <<EOF

# ── Filled in by setup-env-prod.sh ───────────────────────────────────────────
MCP_AUTH_TOKEN=$MCP_AUTH_TOKEN
# TODO: MCP_IDENTITY must be an existing users.email (triggered_by on MCP runs)
# MCP_IDENTITY=
# TODO: MCP_ALLOWED_HOSTS — comma-separated public hostname(s) the ingress forwards
# MCP_ALLOWED_HOSTS=
EOF

chmod 600 "$TARGET"

echo "Wrote $TARGET (mode 600)."
echo
echo "Still TODO by hand — the script can't know these:"
echo "  * CORS_ORIGIN     — replace <your-azure-domain-or-ip>/<your-azure-public-ip>"
echo "  * MCP_IDENTITY / MCP_ALLOWED_HOSTS — if the MCP service is deployed"
echo
echo "Reminder: APP_DB_PASSWORD and REDIS_PASSWORD are pinned to"
echo "docker-compose.prod.yml — keep them in sync if you rotate either."
