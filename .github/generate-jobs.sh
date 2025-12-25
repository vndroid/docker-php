#!/usr/bin/env bash
set -Eeuo pipefail

# 自动扫描项目结构并生成 GitHub Actions 矩阵
# 项目结构预期: {version}/{base-image}/{variant}/Dockerfile
# 示例: 8.4/alpine3.21/fpm/Dockerfile

declare -a include

# 扫描所有 Dockerfile
while IFS= read -r dockerfile; do
  # 提取路径信息
  # 例如: 8.4/alpine3.21/fpm/Dockerfile
  # -> version=8.4, base=alpine3.21, variant=fpm
  
  dir=$(dirname "$dockerfile")
  variant=$(basename "$dir")
  base_dir=$(dirname "$dir")
  base=$(basename "$base_dir")
  version_dir=$(dirname "$base_dir")
  version=$(basename "$version_dir")
  
  # 从 Dockerfile 中提取完整的 PHP 版本号
  php_version=$(grep -E '^\s*ENV\s+PHP_VERSION' "$dockerfile" | head -1 | awk '{print $NF}')
  
  # 如果能提取到具体版本，使用完整版本号；否则使用目录版本号
  if [ -n "$php_version" ]; then
    display_version="$php_version"
  else
    display_version="$version"
  fi
  
  # 构建两个镜像标签：完整版本和缩略版本
  full_tag="php:${display_version}-${variant}-${base}"
  short_tag="php:${version}-${variant}-${base}"
  name="${display_version}-${variant}-${base}"
  dockerfile_path="${dockerfile#./}"
  
  # 提取标签的 image name 部分（去掉 php: 前缀）
  full_image_tag="${display_version}-${variant}-${base}"
  short_image_tag="${version}-${variant}-${base}"
  
  # ghcr.io 完整和缩略标签
  ghcr_full_tag="ghcr.io/\${{ github.repository_owner }}/php:${full_image_tag}"
  ghcr_short_tag="ghcr.io/\${{ github.repository_owner }}/php:${short_image_tag}"
  
  # 创建矩阵条目
  entry=$(jq -n \
    --arg name "$name" \
    --arg version "$version" \
    --arg base "$base" \
    --arg variant "$variant" \
    --arg full_tag "$full_tag" \
    --arg short_tag "$short_tag" \
    --arg dockerfile "$dockerfile_path" \
    --arg os "ubuntu-latest" \
    --arg build_context "$(dirname $dockerfile_path)" \
    --arg full_image_tag "$full_image_tag" \
    --arg short_image_tag "$short_image_tag" \
    '{
      name: $name,
      version: $version,
      base: $base,
      variant: $variant,
      full_tag: $full_tag,
      short_tag: $short_tag,
      full_image_tag: $full_image_tag,
      short_image_tag: $short_image_tag,
      dockerfile: $dockerfile,
      os: $os,
      runs: {
        prepare: "echo \"Preparing environment for \($name)\"",
        pull: "echo \"Pulling dependencies\"",
        build: "docker build -t \($full_tag) -t \($short_tag) -f \($dockerfile) \($build_context) && docker tag \($full_tag) $REGISTRY/$GITHUB_REPOSITORY_OWNER/php:\($full_image_tag) && docker tag \($short_tag) $REGISTRY/$GITHUB_REPOSITORY_OWNER/php:\($short_image_tag) && docker push $REGISTRY/$GITHUB_REPOSITORY_OWNER/php:\($full_image_tag) && docker push $REGISTRY/$GITHUB_REPOSITORY_OWNER/php:\($short_image_tag)",
        history: "docker history \($full_tag) || true",
        test: "docker run --rm \($full_tag) php -v",
      }
    }')
  
  include+=("$entry")
done < <(find . -name "Dockerfile" -type f | grep -E '[0-9]+\.[0-9]+' | sort)

# 生成最终的 strategy JSON
if [ ${#include[@]} -eq 0 ]; then
  echo "{\"include\": []}"
else
  strategy=$(jq -n \
    --argjson include "$(printf '%s\n' "${include[@]}" | jq -s '.')" \
    '{include: $include}')
  echo "$strategy"
fi
