#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release=$(realpath "${1:?Usage: build.sh /opt/paperlens/releases/SHA}")
sha=$(basename "$release")
[[ "$sha" =~ ^[a-f0-9]{40}$ ]]
export DOCKER_BUILDKIT=1
cd "$release"
# 版本和哈希仍由锁文件固定，只替换下载源。
docker build --progress=plain --build-arg RELEASE_SHA="$sha" \
  --build-arg PYPI_INDEX=https://mirrors.cloud.tencent.com/pypi/simple \
  -t "paperlens-api:$sha" .
docker build --progress=plain -f frontend/Dockerfile --build-arg RELEASE_SHA="$sha" \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -t "paperlens-web:$sha" .
api=$(docker image inspect --format '{{.Id}}' "paperlens-api:$sha")
web=$(docker image inspect --format '{{.Id}}' "paperlens-web:$sha")
[[ "$api" =~ ^sha256:[a-f0-9]{64}$ && "$web" =~ ^sha256:[a-f0-9]{64}$ ]]
printf 'API_IMAGE=%s\nWEB_IMAGE=%s\nRELEASE_SHA=%s\n' "$api" "$web" "$sha" > "$release/images.env"
