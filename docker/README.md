# Z-MAX 标准容器框架 (2026-08-08 老倪设计)

> **一个标准容器环境，四处运行**：远程 GPU 训练 / 本地推理测试 / Mac 数据推理 / Orin 真机部署。
> 训练、推理、评测全部容器化 —— 环境永远一致，不再有"我这能跑你那不行"。

## 架构

```
docker/
├── Dockerfile               # 多阶段: base → train(GPU) / infer(轻量, 多平台)
├── requirements.lock        # 锁定依赖 (transformers 4.44.2 + torch 2.4.1 — 飞书端 v6 验证稳定)
├── entrypoints/
│   ├── train.sh             # 训练入口 (zmax-train --config_path xxx.yaml)
│   └── infer.sh             # 推理入口 (zmax-infer --policy act / --video / --report)
└── deploy/
    └── push.sh              # 推送: ./deploy/push.sh {remote|mac|orin}
```

## 四处运行

| 目标 | 架构 | 用途 | 命令 |
|---|---|---|---|
| 远程 GPU 服务器 (V100) | amd64+CUDA | **训练** | `./deploy/push.sh remote` |
| 本地 (4060 WSL) | amd64+CUDA | **推理测试** | `docker run zmax-std:1.0 zmax-infer --policy act` |
| Mac M1 (小芳) | arm64+CPU | 数据/推理 | `./deploy/push.sh mac` |
| Orin (部署) | arm64+JetPack | **真机推理** | `./deploy/push.sh orin` |

## 构建

```bash
# 当前架构单平台 (最快)
docker build --target train -t zmax-std:1.0 -f docker/Dockerfile .

# 多平台 (推 Mac/Orin 用 — buildx)
docker buildx build --platform linux/amd64,linux/arm64 --target train -t zmax-std:1.0 -f docker/Dockerfile .
```

## 训练 (远程)

```bash
docker run --rm --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1 \
  -v $(pwd):/app \
  zmax-std:1.0 zmax-train --config_path configs/policies/act/config_act_peg_novae.yaml
```
（免 nvidia-container-toolkit — `--device` 直通 + libcuda 挂载，全平台实测可用）

## 推理/评测

```bash
docker run zmax-std:1.0 zmax-infer --policy act --ckpt outputs/train/act_xxx/checkpoints/last
docker run zmax-std:1.0 zmax-infer --video        # 7 模型仿真对比视频
docker run zmax-std:1.0 zmax-infer --report       # Model Zoo PDF 报告
```

## 版本锁定原则

- `requirements.lock` 是唯一真相 — 升级版本 = 改 lock 文件 → 重新 build → 四处同步
- 当前基线 (踩坑换来的稳定组合):
  - transformers **4.44.2** (5.x 的 accelerate/torch 集成坑, 4.49/4.51 缺 TextConfig — 别动)
  - torch **2.4.1** (与驱动 550/CUDA12.4 匹配; arm64 自动切 CPU wheel)
  - Python 3.12 (lerobot 源码 PEP695 已去 — 3.10 容器也兼容)
- 数据统一: 容器内 `data/metaworld_peg_grab6` (train.sh 自动 sed root)

## GUI 集成

模型引擎 → 🐳 训练容器区: 上传/构建状态实时显示; 训练明确在标准容器中执行。
