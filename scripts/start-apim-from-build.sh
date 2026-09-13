#!/usr/bin/env bash
# 从源码构建产物启动 WSO2 APIM 4.7.0(端口整体 +100,管理口 9543,避让镜像版 9443)。
#
# 前置:已完成 mvn 构建,产物 zip 在 product-apim-4.7.0/all-in-one-apim/modules/distribution/product/target/
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APIM_DIR="$HERE/infra/wso2-apim"
SRC="$APIM_DIR/product-apim-4.7.0"
RUNTIME="$APIM_DIR/runtime"
ZIP="$(ls "$SRC"/all-in-one-apim/modules/distribution/product/target/wso2am-*.zip 2>/dev/null | head -1 || true)"
OFFSET="${APIM_OFFSET:-100}"

if [ -z "$ZIP" ]; then
  echo "❌ 未找到构建产物 wso2am-*.zip,先完成 mvn 构建" >&2
  exit 1
fi

if [ ! -d "$RUNTIME" ]; then
  echo "📦 解压 $(basename "$ZIP") → $RUNTIME"
  mkdir -p "$RUNTIME"
  unzip -q "$ZIP" -d "$RUNTIME"
fi

CARBON_HOME="$(dirname "$(find "$RUNTIME" -name api-manager.sh -path '*/bin/*' | head -1)")/.."
echo "CARBON_HOME=$CARBON_HOME"

# 端口偏移:9443→9543, 9763→9863, 8243→8343 ...
TOML="$CARBON_HOME/repository/conf/deployment.toml"
if ! grep -q '^[server]' "$TOML" 2>/dev/null; then
  printf '\n[server]\noffset = %s\n' "$OFFSET" >> "$TOML"
  echo "🔧 已写入 [server] offset=$OFFSET"
fi

HTTPS_PORT=$((9443 + OFFSET))
echo "▶️  启动 APIM(console),管理口 https://127.0.0.1:${HTTPS_PORT}/carbon"
exec "$CARBON_HOME/bin/api-manager.sh" console
