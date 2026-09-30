#!/usr/bin/env bash
# 建 3DGS 训练环境: 干净 venv + torch2.7.1/cu128 + gsplat 预编译轮(无需 nvcc)
set -x
export PATH="$HOME/.hermes/bin:$PATH"
V=$HOME/gs-venv
[ -x "$V/bin/python" ] || uv venv "$V" --python 3.12 || exit 1
PY=$V/bin/python
# 1) torch 与 gsplat 轮子必须同源(pt27cu128)
uv pip install --python "$PY" torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu128 || exit 2
# 2) gsplat 预编译轮(pt27cu128) —— 命中就不用 nvcc 现场编译
uv pip install --python "$PY" gsplat --index-url https://docs.gsplat.studio/whl/pt27cu128 \
  --extra-index-url https://pypi.org/simple || {
    echo "[fallback] 预编译轮没命中, 改走 PyPI(JIT)"; uv pip install --python "$PY" gsplat || exit 3; }
# 3) 常用件
uv pip install --python "$PY" numpy opencv-python-headless plyfile tqdm rich scipy || exit 4
echo '=== 自检 ==='
"$PY" - <<'EOF'
import torch, sys
print("python", sys.version.split()[0], "| torch", torch.__version__, "| cuda", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
try:
    import gsplat
    print("gsplat", getattr(gsplat, "__version__", "?"), "OK")
except Exception as e:
    print("gsplat 导入失败:", type(e).__name__, str(e)[:200])
EOF
echo "[gs-env] done"
