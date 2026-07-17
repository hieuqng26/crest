#!/bin/bash

# Docker Production Environment Management Script
# Usage:
#   ./build_prod.sh down              - Stop and remove production containers
#   ./build_prod.sh down --volumes    - Stop and remove production containers and volumes
#   ./build_prod.sh up                - Build and start production containers

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="env/.env.prod"
NGINX_SRC="services/client/nginx.conf"
NGINX_DST="/opt/crest/nginx/nginx.conf"

# ── Preflight: the MCP service fails closed without these; validate before we
# deploy so it doesn't crash-loop (restart: always). We never fabricate the
# secret — the operator sets it in $ENV_FILE.
preflight_mcp() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERROR: $ENV_FILE not found." >&2
        exit 1
    fi
    _val() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]'; }
    local missing=""
    for var in MCP_AUTH_TOKEN MCP_IDENTITY MCP_ALLOWED_HOSTS; do
        [ -z "$(_val "$var")" ] && missing="$missing $var"
    done
    if [ -n "$missing" ]; then
        echo "ERROR: the MCP server requires these in $ENV_FILE:$missing" >&2
        echo "  MCP_AUTH_TOKEN=<strong secret>   # e.g. openssl rand -hex 32" >&2
        echo "  MCP_IDENTITY=<an existing users.email, e.g. admin>" >&2
        echo "  MCP_ALLOWED_HOSTS=<public hostname the ingress forwards as Host>" >&2
        exit 1
    fi
}

# ── Sync the ingress config: the host-mounted $NGINX_DST overrides the image's
# baked-in nginx.conf, so make the repo the source of truth by copying it on
# each deploy (backing up the previous version first — reversible if the host
# file had out-of-repo tweaks). A bind-mounted file change doesn't restart the
# frontend, so we reload nginx after `up`.
sync_nginx() {
    if [ ! -f "$NGINX_SRC" ]; then
        echo "ERROR: $NGINX_SRC not found." >&2
        exit 1
    fi
    mkdir -p "$(dirname "$NGINX_DST")" || {
        echo "ERROR: cannot create $(dirname "$NGINX_DST") (need sudo/root?)." >&2
        exit 1
    }
    if [ -f "$NGINX_DST" ] && ! cmp -s "$NGINX_SRC" "$NGINX_DST"; then
        cp "$NGINX_DST" "$NGINX_DST.bak.$(date +%Y%m%d%H%M%S)"
        echo "==> Backed up existing $NGINX_DST"
    fi
    cp "$NGINX_SRC" "$NGINX_DST" || {
        echo "ERROR: cannot write $NGINX_DST (need sudo/root?)." >&2
        exit 1
    }
    echo "==> Synced $NGINX_SRC -> $NGINX_DST"
}

reload_nginx() {
    # Best-effort: pick up the (bind-mounted) nginx.conf without recreating the
    # container. Non-fatal if the frontend isn't up yet.
    if docker compose -f "$COMPOSE_FILE" exec -T frontend nginx -t >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" exec -T frontend nginx -s reload >/dev/null 2>&1 \
            && echo "==> Reloaded frontend nginx"
    else
        echo "==> Skipped nginx reload (frontend not ready or config invalid — check 'nginx -t')"
    fi
}

# Parse command line arguments
case "$1" in
    down)
        if [ "$2" == "--volumes" ]; then
            echo "==> Stopping and removing production containers and volumes..."
            docker compose -f "$COMPOSE_FILE" down --volumes
        else
            echo "==> Stopping and removing production containers..."
            docker compose -f "$COMPOSE_FILE" down
        fi
        echo "==> Containers stopped and removed!"
        ;;

    up)
        echo "==> Preflight: checking MCP configuration..."
        preflight_mcp
        echo "==> Syncing ingress nginx.conf..."
        sync_nginx
        echo "==> Building and starting production containers..."
        docker compose -f "$COMPOSE_FILE" up --build -d
        reload_nginx

        echo "==> Production environment is ready!"
        echo "==> Use 'docker compose -f $COMPOSE_FILE logs -f' to view logs"
        ;;
    *)
        echo "Error: Invalid command"
        echo ""
        echo "Usage:"
        echo "  ./build_prod.sh down              - Stop and remove production containers"
        echo "  ./build_prod.sh down --volumes    - Stop and remove production containers and volumes"
        echo "  ./build_prod.sh up                - Build and start production containers"
        exit 1
        ;;
esac
