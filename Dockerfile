# Z-MAX 模型引擎训练镜像 (2026-08-08 老倪: 容器化技术 — 远程 GPU 训练统一容器)
# 基础: PyTorch 官方 CUDA 镜像 (自带 torch, 免重复下载; V100 sm_70 支持)
# 🐛 2026-08-08: lerobot 用 PEP695 泛型语法 (Python≥3.12) — 必须 3.12 镜像 (2.2.0 是 3.10 跑不了)
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

# 项目代码 (data/outputs 由 .dockerignore 排除, 运行时挂载)
COPY . /app

# lerobot + 依赖 (一次性构建, 训练复用; 🐛 2026-08-08: 镜像 Python 3.10 < pyproject >=3.12 → --ignore-requires-python;
#   全依赖安装 (termcolor/tensorboard 等 — --no-deps 会漏))
RUN pip install --no-cache-dir --ignore-requires-python -e . 2>/dev/null; \
    pip install --no-cache-dir --ignore-requires-python termcolor tensorboard 2>/dev/null; true

# 默认: 模型引擎训练入口
CMD ["python", "-m", "lerobot.scripts.lerobot_train", "--help"]
