# =============================================================================
# Z-MAX 标准容器框架 (2026-08-08 老倪设计)
# -----------------------------------------------------------------------------
# 一个标准容器环境, 四处运行:
#   ① 远程 GPU 服务器 (V100)   → 训练        (x86_64 + CUDA)
#   ② 本地 (4060 WSL)          → 推理测试    (x86_64 + CUDA)
#   ③ Mac (M1/M2, 小芳)        → 数据/推理   (arm64 + CPU)
#   ④ Orin (Z-MAX 部署)        → 真机推理    (arm64 + JetPack CUDA)
#
# 构建:  docker buildx build --platform linux/amd64,linux/arm64 -t zmax-std:1.0 .
# 或单平台: docker build -t zmax-std:1.0 .   (当前架构)
# 推送: 见 deploy/ 脚本 (save+scp 或 registry)
# =============================================================================

# ---- 阶段0: 基础环境 (多平台) ------------------------------------------------
# 基础镜像: 统一 python 3.12 (与 lerobot 源码/飞书端验证一致)
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE} AS base

# 架构注入 (buildx 自动; 单平台 build 取本机)
ARG TARGETPLATFORM
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# 系统依赖 (视频解码/图像/构建工具 — 数据加载与评测必需)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libgomp1 \
      git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- 阶段1: 训练 (GPU) --------------------------------------------------------
FROM base AS train
# torch 按平台: amd64 → CUDA wheel; arm64 → CPU wheel (Orin 用 JetPack 版可覆盖)
# 2026-08-08 飞书端: 本地 4060 全模型验证组合 torch 2.11.0+cu128 (requirements.lock 为准)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
RUN if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
      pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu; \
    else \
      pip install torch==2.11.0 torchvision==0.26.0 --index-url ${TORCH_INDEX}; \
    fi

# lerobot 工程 + 锁定依赖 (transformers 5.5.4 + torch 2.11.0 — 本地全模型验证)
COPY docker/requirements.lock /app/requirements.lock
# torch 显式 cu128 (本地 4060 验证: torch 2.11.0+cu128 + torchvision 0.26.0+cu128)
RUN pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128 && \
    pip install --no-cache-dir -r /app/requirements.lock

# 工程源码 (构建时注入; 运行时可 -v 挂载覆盖)
COPY . /app

# 训练入口
COPY docker/entrypoints/train.sh /usr/local/bin/zmax-train
RUN chmod +x /usr/local/bin/zmax-train
ENTRYPOINT ["zmax-train"]

# ---- 阶段2: 推理 (轻量, 多平台) ------------------------------------------------
FROM base AS infer
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
      pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    else \
      pip install torch==2.4.1 torchvision --index-url ${TORCH_INDEX}; \
    fi
COPY requirements.lock /app/requirements.lock
RUN pip install -r /app/requirements.lock
COPY . /app
COPY docker/entrypoints/infer.sh /usr/local/bin/zmax-infer
RUN chmod +x /usr/local/bin/zmax-infer
ENTRYPOINT ["zmax-infer"]
