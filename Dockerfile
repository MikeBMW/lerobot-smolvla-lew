# Z-MAX 模型引擎训练镜像 (2026-08-08 老倪: 容器化技术 — 远程 GPU 训练统一容器)
# 基础: PyTorch 官方 CUDA 镜像 (自带 torch, 免重复下载; V100 sm_70 支持)
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

WORKDIR /app

# 项目代码 (data/outputs 由 .dockerignore 排除, 运行时挂载)
COPY . /app

# lerobot + 依赖 (一次性构建, 训练复用)
RUN pip install --no-cache-dir -e . --no-deps 2>/dev/null; \
    pip install --no-cache-dir transformers sentencepiece protobuf 2>/dev/null; true

# 默认: 模型引擎训练入口
CMD ["python", "-m", "lerobot.scripts.lerobot_train", "--help"]
