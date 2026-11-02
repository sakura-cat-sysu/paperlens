#!/usr/bin/env bash
# 调用方设置 root 和 release；回滚时始终使用对应 release 的文件。
compose() {
  local files=(-f "$release/compose.yaml")
  if [[ -f "$root/shared-host" ]]; then
    files+=(-f "$release/compose.shared.yaml")
  fi
  RELEASE_DIR="$release" docker compose --project-directory "$root" --env-file "$root/.env" \
    --env-file "$release/images.env" "${files[@]}" "$@"
}
