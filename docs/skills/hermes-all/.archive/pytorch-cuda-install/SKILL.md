---
name: pytorch-cuda-install
description: Use when official PyTorch+CUDA wheel installs fail.
---

# PyTorch CUDA 安装（受限网络）

Trigger: pip install torch 卡死/极慢, download.pytorch.org 不可达, 需要 CUDA wheels（本用户环境 CN 网络，RTX 4060/4090/Orin 都会遇到）。

## 快速路径（已验证）
1. 确认 GPU: `nvidia-smi`（CUDA 12.7 → 可用 cu124 wheels）
2. Python ≥3.12: `uv python install 3.12`（uv 在 `~/.hermes/bin/uv`；系统 python3 常是 3.11/3.14 不满足）
3. **先测镜像速度，别盲装**：
   - 阿里云 pytorch-wheels: `https://mirrors.aliyun.com/pytorch-wheels/cu124/`（~2.3MB/s，首选；目录页可 grep 可用版本）
   - pytorch.org 官方: 通常 70B/s（废）；清华 403；中科大无 cu124
4. **curl 直链下载 wheel**（pip 索引解析会卡死或重定向到慢源）：
   ```bash
   mkdir -p /tmp/wheels && cd /tmp/wheels
   curl -sL --retry 3 -o torch.whl "https://mirrors.aliyun.com/pytorch-wheels/cu124/torch-2.6.0%2Bcu124-cp312-cp312-linux_x86_64.whl"
   mv torch.whl torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl   # 必须标准 wheel 名
   pip install --no-deps torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl
   ```
5. **--no-deps 后必须手动装 nvidia 运行时库**（否则 import torch 报 `libcublas/libcudnn not found`）。从同一镜像下载并逐个 `pip install --no-deps`：
   nvidia_cublas_cu12, nvidia_cuda_runtime_cu12, nvidia_cuda_nvrtc_cu12, nvidia_cudnn_cu12, nvidia_cufft_cu12, nvidia_curand_cu12, nvidia_cusolver_cu12, nvidia_cusparse_cu12, nvidia_cusparselt_cu12, nvidia_nccl_cu12, nvidia_nvjitlink_cu12, nvidia_nvtx_cu12, nvidia_cuda_cupti_cu12
6. 验证: `python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
7. 其余纯 Python 依赖走阿里 PyPI: `pip install -i https://mirrors.aliyun.com/pypi/simple/ <pkgs>`（小文件 pypi.org 直连也可）

## Pitfalls
- **pip 会把 torch 解析成 CPU 版替换 CUDA 版**（timm/transformers 声明依赖 torch 时）。凡涉及 torch 一律 `--no-deps`，torch 相关手动装。
- **curl 下载会被静默截断**。装前验证: `python -c "import zipfile; z=zipfile.ZipFile('x.whl'); z.testzip()"`，损坏就重下。
- 阿里云 cu124 镜像最高 torch 2.6.0；要 2.7+ 需另找源或接受 2.6（ACT 推理实测正常）。
- tokenizers==0.23.0 正式版**不存在**（只有 0.23.0rc0/0.23.1）→ 装 0.22.2 落在约束内。
- lerobot 0.5.2 要求 transformers>=5.4.0,<5.6.0（不是 4.x）；声明 torch>=2.7 但 2.6 实测可用。
- pip 依赖冲突报错是噪音，`--no-deps` 后以 `import` 实测为准。

## 支持文件
- references/lerobot-act-env.md — ACT 推理环境完整清单 + 验证配方
