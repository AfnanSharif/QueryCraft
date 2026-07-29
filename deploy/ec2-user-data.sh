#!/usr/bin/env bash
set -euo pipefail

# Reference bootstrap for an Ubuntu EC2 host. Set these in instance user-data
# or replace them through your CI/CD system before use.
: "${APP_IMAGE:?Set APP_IMAGE to an immutable container image tag}"
: "${APP_PASSWORD:?Set APP_PASSWORD from a secret delivery mechanism}"

apt-get update
apt-get install -y docker.io
systemctl enable --now docker
docker volume create querycraft-data
docker run -d --restart unless-stopped --name querycraft \
  -p 8501:8501 \
  -e APP_PASSWORD="${APP_PASSWORD}" \
  -e DATABASE_PATH=/app/.local/food_delivery.db \
  -v querycraft-data:/app/.local \
  "${APP_IMAGE}"
