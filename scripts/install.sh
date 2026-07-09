#!/usr/bin/env bash
#
# install.sh — Install Docker Engine + Compose plugin and Python on Ubuntu 24.04.
# Matches the "Server Preparation" steps in DEPLOYMENT.md.
#
# Usage:  sudo ./scripts/install.sh
#
set -euo pipefail

# --- pre-flight checks ------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Error: run as root (sudo ./scripts/install.sh)" >&2
  exit 1
fi

if ! command -v lsb_release >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y lsb-release
fi

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "Warning: this script targets Ubuntu; detected '${ID:-unknown}'. Continuing anyway." >&2
fi

# The user to add to the docker group (the human who invoked sudo).
TARGET_USER="${SUDO_USER:-$USER}"

echo "==> Removing any old/conflicting Docker packages"
apt-get remove -y docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc 2>/dev/null || true

echo "==> Installing prerequisites"
apt-get update
apt-get install -y ca-certificates curl

echo "==> Adding Docker's official GPG key"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "==> Adding Docker apt repository"
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu \
  ${VERSION_CODENAME} stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "==> Installing Docker Engine + Compose plugin"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Enabling and starting Docker"
systemctl enable --now docker

echo "==> Adding '${TARGET_USER}' to the docker group"
usermod -aG docker "${TARGET_USER}"

echo "==> Installing Python 3 (with pip and venv)"
apt-get install -y python3 python3-pip python3-venv

echo "==> Verifying installation"
docker version
docker compose version
python3 --version
pip3 --version

echo
echo "Docker + Python installed. Log out and back in (or run 'newgrp docker') so '${TARGET_USER}' can use docker without sudo."
