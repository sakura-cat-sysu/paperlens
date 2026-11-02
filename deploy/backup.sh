#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
root=${PAPERLENS_ROOT:-/opt/paperlens}
release=$(readlink -f "$root/current")
[[ -f "$release/images.env" ]]
source "$(dirname "${BASH_SOURCE[0]}")/compose.sh"
mkdir -p "$root/backups"
file="$root/backups/paperlens-$(date -u +%Y%m%dT%H%M%SZ).dump"
compose exec -T postgres pg_dump -U paperlens -d paperlens -Fc > "$file"
[[ -s "$file" ]]
printf 'Database backup created: %s\n' "$file"
