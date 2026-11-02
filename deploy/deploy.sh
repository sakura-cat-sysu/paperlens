#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

root=${PAPERLENS_ROOT:-/opt/paperlens}
release=$(realpath "${1:?Usage: deploy.sh /opt/paperlens/releases/SHA}")
[[ -f "$root/.env" && -f "$release/compose.yaml" ]] || { echo 'Missing server .env or release bundle' >&2; exit 1; }
exec 9>"$root/deploy.lock"
flock -w 1800 9 || { echo 'Another deployment is active' >&2; exit 1; }
previous=$(readlink -f "$root/current" || true)

source "$(dirname "${BASH_SOURCE[0]}")/compose.sh"

rollback() {
  trap - ERR
  echo 'Deployment failed; restoring the previous application release' >&2
  if [[ -n "$previous" && -f "$previous/images.env" ]]; then
    release=$previous
    compose up -d --wait --wait-timeout 180 api worker scheduler web || echo 'Rollback needs operator attention' >&2
  else
    echo 'No previous release is available; inspect docker compose logs' >&2
  fi
  exit 1
}
trap rollback ERR

if [[ -f "$root/shared-host" ]]; then
  bash "$release/deploy/build.sh" "$release"
  compose config --quiet
else
  compose config --quiet
  compose pull --quiet
fi
compose up -d --wait --wait-timeout 180 postgres rabbitmq
mkdir -p "$root/backups"
backup="$root/backups/predeploy-$(date -u +%Y%m%dT%H%M%SZ).dump"
compose exec -T postgres pg_dump -U paperlens -d paperlens -Fc > "$backup"
[[ -s "$backup" ]]
compose run --rm --no-deps migrate

# 等待正在收费的模型阶段结束，再替换 Worker。
compose stop -t 1320 worker
compose up -d --wait --wait-timeout 180 api worker scheduler web

domain=$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["web"]["environment"]["DOMAIN"])')
expected=$(awk -F= '$1=="RELEASE_SHA" {print $2}' "$release/images.env")
[[ "$expected" =~ ^[a-f0-9]{40}$ ]]
for path in api/health/ready release.json; do
  curl --fail --silent --show-error --resolve "$domain:443:127.0.0.1" "https://$domain/$path" \
    | python3 -c 'import json,sys; actual=json.load(sys.stdin)["release"]; assert actual == sys.argv[1], (actual, sys.argv[1])' "$expected"
done
curl --fail --silent --show-error --resolve "$domain:443:127.0.0.1" "https://$domain/" > /dev/null
ln -sfn "$release" "$root/current"
trap - ERR
printf 'Deployed %s\n' "$expected"
