#!/bin/bash

# Docker Debug Environment Management Script
# Usage:
#   ./build_prod.sh down              - Stop and remove production containers
#   ./build_prod.sh down --volumes    - Stop and remove production containers and volumes
#   ./build_prod.sh up                - Build and start production containers

# Parse command line arguments
case "$1" in
    down)
        if [ "$2" == "--volumes" ]; then
            echo "==> Stopping and removing debug containers and volumes..."
            docker compose -f docker-compose.prod.yml down --volumes
        else
            echo "==> Stopping and removing debug containers..."
            docker compose -f docker-compose.prod.yml down
        fi
        echo "==> Containers stopped and removed!"
        ;;

    up)
        # Just build and start debug containers
        echo "==> Building and starting production containers..."
        docker compose -f docker-compose.prod.yml up --build -d

        echo "==> Production environment is ready!"
        echo "==> Use 'docker compose -f docker-compose.prod.yml logs -f' to view logs"
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
