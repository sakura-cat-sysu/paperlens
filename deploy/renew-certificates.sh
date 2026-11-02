#!/usr/bin/env bash
set -Eeuo pipefail
root=${PAPERLENS_ROOT:-/opt/paperlens}
release=$(readlink -f "$root/current")
certbot renew --quiet --webroot -w "$root/acme"
RELEASE_DIR="$release" docker compose --project-directory "$root" --env-file "$root/.env" \
  --env-file "$release/images.env" -f "$release/compose.yaml" exec -T web nginx -s reload
