# Z-MAX 统一 Docker 环境 (三端对齐)

> 标准镜像: **zmax-train:v7** (远程4060已验证) → 升级 v8 中
> 2026-08-08 · 同步: Orin / Mac / 工控机 / 4060

## 1. 标准镜像 (zmax-train)

| 项 | 值 |
|:---|:---|
| 镜像名 | zmax-train:v7 (→v8 最终版) |
| 基础 | lerobot + torch + CUDA |
| 关键依赖 | transformers 4.50.3 / qwen / torch_compilable_check ✅ |
| 架构 | linux/arm64 (Orin) + linux/amd64 (4060) |
| 验证 | qwen + torch_compilable_check 均 OK |

## 2. 三端 Docker 现状

| 端 | 架构 | Docker | 状态 |
|:---|:---|:---:|:---|
| **Orin** | aarch64 | 29.6.2 | ✅ 装好, ⚠️ tashan 需加 docker 组 |
| **Mac** | arm64 | 24.0.5 | ✅ CLI, ⚠️ Docker Desktop 需启动/升级 |
| **工控机** | x86_64 | 待查 | 需确认 |
| **4060** | x86_64 | 有 | ✅ 标准镜像源 |

## 3. 统一安装步骤

### 3.1 Orin (aarch64)
```bash
# 授权 tashan (Orin终端执行)
sudo usermod -aG docker tashan
newgrp docker

# 验证
docker info | grep "Server Version"
docker run --rm hello-world
```

### 3.2 Mac (arm64)
```bash
# 启动 Docker Desktop
open -a Docker
# 等待 daemon 就绪
docker info | grep "Server Version"

# 拉取标准镜像 (同架构 arm64)
docker pull zmax-train:v7
docker images | grep zmax-train
```

### 3.3 工控机 (Windows x86_64)
```cmd
:: 检查
docker --version
:: 未装则装 Docker Desktop for Windows (WSL2后端)
:: 拉取标准镜像
docker pull zmax-train:v7
```

### 3.4 4060 (标准源)
```bash
# 静静: v7 验证后 commit v8 最终版
docker commit <container> zmax-train:v8
# 导出镜像供其他端 (同架构可直传, 跨架构用 registry)
docker save zmax-train:v8 | gzip > zmax-train-v8.tar.gz
```

## 4. 镜像分发方案

| 场景 | 方式 |
|:---|:---|
| Orin ← 4060 (不同架构 x86→arm) | 需重新构建 (Dockerfile) 或多架构 manifest |
| Mac ← 4060 (同 arm64) | docker save/load 或 registry |
| 工控机 ← 4060 (同 x86_64) | docker save/load 或 registry |

**推荐**: 用 Dockerfile 三端各自构建 (保证依赖一致), 或推私有 registry。

## 5. 统一验证命令

```bash
# 三端执行相同验证
docker run --rm zmax-train:v7 python -c "
import torch, transformers
print('torch:', torch.__version__)
print('transformers:', transformers.__version__)
print('cuda:', torch.cuda.is_available())
"
```
期望输出: torch 2.x / transformers 4.50.3 / cuda True (4060) 或 False (Orin/Mac无GPU推理)

---
*统一 Docker 环境 · 小芳端侧同步* | *标准: zmax-train:v7(→v8)* | *@xspace 确认 v8 commit 后更新本文档*
