#!/bin/bash

# Docker Debug Environment Management Script
# Usage:
#   ./build_debug.sh down              - Stop and remove debug containers
#   ./build_debug.sh down --volumes    - Stop and remove debug containers and volumes
#   ./build_debug.sh up                - Build and start debug containers

# Parse command line arguments
case "$1" in
    down)
        if [ "$2" == "--volumes" ]; then
            echo "==> Stopping and removing debug containers and volumes..."
            docker compose -f docker-compose.debug.yml down --volumes
        else
            echo "==> Stopping and removing debug containers..."
            docker compose -f docker-compose.debug.yml down
        fi
        echo "==> Containers stopped and removed!"
        ;;

    up)
        # Just build and start debug containers
        echo "==> Building and starting debug containers..."
        docker compose -f docker-compose.debug.yml up --build -d

        echo "==> Debug environment is ready!"
        echo "==> Use 'docker compose -f docker-compose.debug.yml logs -f' to view logs"
        ;;
    *)
        echo "Error: Invalid command"
        echo ""
        echo "Usage:"
        echo "  ./build_debug.sh down              - Stop and remove debug containers"
        echo "  ./build_debug.sh down --volumes    - Stop and remove debug containers and volumes"
        echo "  ./build_debug.sh up                - Build and start debug containers"
        exit 1
        ;;
esac
