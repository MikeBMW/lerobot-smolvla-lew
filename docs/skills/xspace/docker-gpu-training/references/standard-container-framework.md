# 标准容器框架 — 设计要点 (2026-08-08 老倪)

仓库 `docker/` 目录是活模板（lerobot-smolvla-lew/docker/）。目标：**一个标准容器环境，
一处构建，四处运行** —— 远程 GPU 训练 / 本地推理 / Mac(arm64) / Orin(arm64)。

## 目录结构

```
docker/
├── Dockerfile               # 多阶段: base → train(GPU) / infer(轻量)
├── requirements.lock        # 锁定依赖 (唯一真相)
├── entrypoints/
│   ├── train.sh             # zmax-train --config_path x.yaml [--steps --batch --lr]
│   └── infer.sh             # zmax-infer --policy act [--ckpt] / --video / --report
└── deploy/
    └── push.sh              # ./deploy/push.sh {remote|mac|orin}
```

## Dockerfile 多阶段骨架

```dockerfile
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE} AS base
ARG TARGETPLATFORM
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libgomp1 git curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base AS train
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
      pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    else \
      pip install torch==2.4.1 torchvision --index-url ${TORCH_INDEX}; \
    fi
COPY requirements.lock /app/requirements.lock
RUN pip install -r /app/requirements.lock
COPY . /app
COPY docker/entrypoints/train.sh /usr/local/bin/zmax-train
RUN chmod +x /usr/local/bin/zmax-train
ENTRYPOINT ["zmax-train"]
# 同理 AS infer (轻量) — infer.sh → zmax-infer
```

## requirements.lock 基线（踩坑换来的稳定组合 — 勿动）

**最终统一基线 (2026-08-08, 全 7 模型可训)**:
```
transformers==5.14.1      # qwen2_5_vl(SmolVLA) + torch_compilable_check 都有
torch==2.5.1              # 5.x 需 torch 2.5+ 的 DTensor; 匹配驱动 550/CUDA12.4, V100 sm_70
torchvision==0.20.1
torchaudio==2.5.1         # 三者同源同版本一次装齐 (cu124), 别混 cu121/cu124
accelerate==1.14.0
safetensors==0.8.0  tokenizers==0.21.4  sentencepiece==0.2.0  protobuf>=4.25,<6
datasets>=3.0,<6  av>=13,<15  opencv-python>=4.10,<5  numpy>=1.26,<2.2
tensorboard  termcolor  rich  hydra-core  omegaconf  einops  timm  tqdm  pyyaml
huggingface-hub>=0.24,<0.37  imageio  imageio-ffmpeg  matplotlib  Pillow
```

Dockerfile 必须先显式装 cu124 torch 再装 lock（PyPI 默认源无 CUDA wheel）:
```dockerfile
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
      --index-url https://download.pytorch.org/whl/cu124 && \
    pip install --no-cache-dir -r /app/requirements.lock
```

**版本演化史（为什么不是 4.44.2）**：
- 4.44.2+torch 2.4.1（v6 镜像）= 最稳但**只够 ACT/VLA-Touch/AWE**（这些不 import qwen2_5_vl）
- SmolVLA 需要 `transformers.models.qwen2_5_vl`（4.49+ 才引入）；4.49/4.50/4.51 又缺 `torch_compilable_check`（5.x 才有，eo1 策略顶层引用）；5.x 需要 torch 2.5+ 的 DTensor（2.4.1 缺）→ **最终组合 5.14.1 + torch 2.5.1** 全模型可训

升级原则：改 lock → 重建 → 四处同步（一处跑不起来全都不动）。

## 入口脚本要点

- train.sh：解析 `--config_path`（兼容 `--config-path` 旧写法）→ sed 数据 root 归一
  （`sed -i "s|^  root: .*|  root: data/metaworld_peg_grab6|"`）→ exec lerobot_train
- infer.sh：`--policy act [--ckpt]` / `--video`(7 模型对比视频) / `--report`(PDF)

## 无 registry 推送（push.sh）

```bash
docker buildx build --platform linux/$ARCH --target $TGT -o "type=docker,dest=/tmp/${IMG}-${ARCH}.tar" -f docker/Dockerfile .
sshpass -p "$PWD" scp -o Port=$PORT /tmp/${IMG}-${ARCH}.tar user@host:/tmp/
sshpass -p "$PWD" ssh -o Port=$PORT user@host "docker load -i /tmp/${IMG}-${ARCH}.tar"
```
- remote → amd64 + 三设备 GPU 透传起容器
- mac/orin → arm64（CPU torch；Orin 可再覆盖 JetPack 版 torch）

## GUI 容器集成模式（模型引擎 🐳 区）

1. **状态轮询**：连接远程成功后 QTimer 15s 调 `_poll_remote_container`——
   SSH `docker ps --filter name=zmax_train --format '{{.Status}}'` + `docker logs tail -3`，
   **状态串变化才 emit**（`key = f"{st}|{detail[:60]}"` 与上次不同才打日志——防刷屏），
   同时更新状态标签（运行中/已停止/未运行）。
2. **上传按钮**：先检测本地 docker（`subprocess.run(["docker","images",...])` returncode）——
   本地有镜像才走 save+scp+load；**本地无 docker CLI 自动 fallback 远程构建**
   （`git pull && docker build -t zmax-train:latest .`），日志明确提示"本地无 docker →
   远程构建（Dockerfile 与本地一致）"，不要让用户看到 `No such file: 'docker'`。
3. 训练明确显示容器（日志/状态"训练在该容器内执行"）。
