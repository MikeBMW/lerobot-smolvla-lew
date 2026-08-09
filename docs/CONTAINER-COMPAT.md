# Z-MAX 容器方案兼容性报告 (三端对齐)

> 2026-08-08 · 小芳端侧 · 配合静静 Docker 框架 (zmax-std:1.0)

## 1. 三端硬件/环境事实

| 端 | 架构 | CUDA | torch | 容器角色 |
|:---|:---|:---|:---|:---|
| **远程 V100** | amd64 | ✅ CUDA | 2.4.1 cu124 | 训练 |
| **4060** | amd64 | ✅ CUDA | 2.4.1 cu124 | 推理测试 |
| **Mac (小芳)** | arm64 | ❌ 无 | CPU | 数据/轻推理 |
| **Orin** | aarch64 | ✅ **CUDA 12.6** (JetPack 6.0) | **2.5.0a0 nv24.08** | 真机推理 |

**关键矛盾**: Orin 有 GPU 且真机推理必须 CUDA, 但框架 arm64 分支装 CPU torch → 会丢失 Orin GPU 加速!

## 2. 兼容方案 (三端统一)

### 方案: 镜像分 3 变体 (按用途), 依赖同一 requirements.lock

```
zmax-std:1.0-train    amd64+CUDA   → 远程V100 / 4060 训练
zmax-std:1.0-infer-x86 amd64+CUDA  → 4060 推理测试
zmax-std:1.0-infer-mac arm64+CPU   → Mac 数据/轻推理
zmax-std:1.0-infer-orin aarch64+CUDA(JetPack) → Orin 真机推理 ★
```

### Orin 特殊处理 (★ 核心)

```dockerfile
# Dockerfile 增加 orin stage (基于 JetPack 镜像, 保留系统 CUDA torch)
FROM nvcr.io/nvidia/l4t-jetpack:r36.5.0 AS orin
# 不重装 torch! 使用 JetPack 自带 CUDA torch 2.5.0a0
# 只装框架其余依赖 (transformers 等)
COPY requirements.lock /app/requirements.lock
RUN pip install -r /app/requirements.lock --no-deps  # 跳过torch重装
# 或挂载: docker run -v /usr/lib/python3/dist-packages/torch:/app/torch
```

### 或更简单: Orin 用挂载而非镜像内置 torch

```bash
# Orin 运行 infer 容器时挂载系统 torch (保留 CUDA)
docker run -v /usr/lib/python3/dist-packages:/sys_py \
  -e PYTHONPATH=/sys_py:${PYTHONPATH} zmax-std:1.0-infer ...
```

## 3. 端侧落地清单 (Orin)

| 项 | 方案 |
|:---|:---|
| Docker 授权 | sudo usermod -aG docker tashan (待执行) |
| 镜像变体 | zmax-std:1.0-infer-orin (JetPack CUDA torch) |
| 真机推理 | 容器内跑 orin_infer_service.py (挂载 ~/.zmax) |
| GPU 验证 | torch.cuda.is_available() = True |
| 产线保护 | 容器 --cpus=2 --memory=2g 限制, 不抢产线 |

## 4. 兼容性原则 (三端共识)

1. **requirements.lock 是唯一真相** (transformers 4.44.2 + torch 2.4.1)
2. **torch 按端定制**: amd64=CUDA / arm64 Mac=CPU / arm64 Orin=JetPack CUDA
3. **同一 entrypoint 接口** (zmax-train / zmax-infer), 容器内实现差异
4. **镜像变体命名**: zmax-std:1.0-{train|infer}-{x86|mac|orin}
5. **分发**: buildx 多平台 → save → scp → load (无 registry 环境)

## 5. 待静静确认

- [ ] Dockerfile 增加 orin stage (JetPack 基础镜像) 或采用挂载方案
- [ ] v8 验证完成后更新本报告
- [ ] push.sh 明文密码改 SSH 密钥 (安全)

---
*三端兼容方案 · 小芳* | *与静静 zmax-std 框架对齐* | *Orin 真机推理必须 JetPack CUDA torch*
