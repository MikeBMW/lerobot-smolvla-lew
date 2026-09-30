#!/usr/bin/env bash
# 🍎 Mac(arm64) 备份端环境重建 —— 备份端收包后跑这个
# 老倪 2026-09-23: 小芳是孪生备份端 (Mac, 资源有限)
# 原则: venv 不跨平台复制, 必须重建; 依赖按 arm64 wheel 装; 先预检再装
set -euo pipefail

ROOT="${1:-$HOME/zmax}"
echo "════════════════════════════════════════════════════════════"
echo "🍎 Z-MAX 备份端环境重建 (arm64)  ROOT=$ROOT"
echo "════════════════════════════════════════════════════════════"

# ① 资源预检 (先评估, 再决定装什么)
echo "── ① 资源预检 ──"
python3 "$ROOT/tools/resource_preflight.py" || true

# ② 建 venv (用系统 python3; Mac 上别用 conda 混)
echo "── ② 建虚拟环境 ──"
cd "$ROOT"
python3 -m venv .venv-arm
# shellcheck disable=SC1091
source .venv-arm/bin/activate
python -m pip install -q --upgrade pip

# ③ 装依赖 (arm64 原生 wheel; torch 走 PyPI 官方即含 MPS)
echo "── ③ 安装依赖 (arm64/MPS) ──"
MIRROR="${PIP_MIRROR:-}"
PIPARG=""
[ -n "$MIRROR" ] && PIPARG="-i $MIRROR"
pip install $PIPARG torch torchvision          # arm64 默认含 MPS 支持
pip install $PIPARG transformers einops h5py numpy opencv-python pyyaml
# 可选: 闭环引擎需要 (纯 CPU 也能跑 metaworld)
pip install $PIPARG mujoco pygame 2>/dev/null || echo "  (mujoco 可选, 装不上不影响推理)"

# ④ 硬件/依赖自检
echo "── ④ 自检 ──"
python - <<'PY'
import platform, sys
ok = True
for m in ("torch", "transformers", "h5py", "numpy", "cv2"):
    try:
        __import__(m); print("   ✅", m)
    except Exception as e:
        ok = False; print("   ❌", m, type(e).__name__)
try:
    import torch
    print("   torch:", torch.__version__, "| MPS:", torch.backends.mps.is_available())
except Exception:
    print("   torch 不可用")
print("   arch:", platform.machine(), "| python:", sys.version.split()[0])
sys.exit(0 if ok else 1)
PY

echo "════════════════════════════════════════════════════════════"
echo "✅ 环境就绪: 用 $ROOT/.venv-arm/bin/python 跑工具"
echo "   下一步: python tools/replica_verify.py   (校验收到的包完整性)"
echo "════════════════════════════════════════════════════════════"
