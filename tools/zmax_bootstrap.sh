#!/usr/bin/env bash
# Z-MAX 基线自检/首次 clone 初始化的入口 (真正的实现在 zmax_bootstrap.py)
#   bash tools/zmax_bootstrap.sh                 # 只读体检: 识别已下载的模型/数据, 列出缺的
#   bash tools/zmax_bootstrap.sh --apply         # 铺运行时骨架 + 写 zmax_paths.env + 采纳老位置资产
#   bash tools/zmax_bootstrap.sh --apply --smoke # 铺好后做状态空间功能自检
#   bash tools/zmax_bootstrap.sh --download      # 下缺失的必需资产(走 hf-mirror)
#   bash tools/zmax_bootstrap.sh --secrets       # 生成本机密钥占位(不进仓库)
#   bash tools/zmax_bootstrap.sh --systemd       # 装 systemd 单元
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${ZMAX_PY:-$HERE/../gui-venv311/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONUNBUFFERED=1
exec "$PY" "$HERE/zmax_bootstrap.py" "$@"
