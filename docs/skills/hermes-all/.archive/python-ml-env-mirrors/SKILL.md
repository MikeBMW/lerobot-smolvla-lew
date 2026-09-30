---
name: python-ml-env-mirrors
description: "Use when pip/pytorch.org is slow: use aliyun mirrors."
trigger: "Use when installing torch/torchvision/lerobot/transformers in a China-network or restricted-network environment: pip hangs, pytorch.org crawls (KB/s), or pip keeps resolving CPU torch. Also the go-to for recreating the 4060 WSL venv or prepping Orin/4090 boxes."
---

# Python ML Env Setup via Mirrors (China / restricted network)

Direct pypi.org / download.pytorch.org are effectively unusable on this user's network (measured 70 B/s on pytorch.org). Pip's index resolution also hangs for long stretches. The reliable path is **aliyun mirrors + curl for big wheels + `--no-deps`**.

## Speed-check first (never guess)

```bash
# Pick whichever mirror answers fast; aliyun is the proven one (2.3 MB/s+)
timeout 15 curl -sL -o /dev/null -w "aliyun cu124: %{http_code} %{speed_download}B/s\n" \
  "https://mirrors.aliyun.com/pytorch-wheels/cu124/" 2>/dev/null
timeout 15 curl -sL -o /dev/null -w "tsinghua: %{speed_download} B/s\n" \
  "https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels/cu124/" --range 0-5000000 2>/dev/null
```
Known results: pytorch.org ~70 B/s (dead), tuna 403 on directory listing, sjtu 302/0 B/s, **aliyun = 200 + 2.3 MB/s**, aliyun pypi simple = ~1 MB/s.

## Proven recipe (torch 2.6 + cu124 + lerobot on Python 3.12, 2026-08)

### 1. Python 3.12 (project requires >=3.12; system often only has 3.11/3.14)

```bash
export PATH="$HOME/.hermes/bin:$PATH"   # uv lives here, not ~/.local/bin
uv python install 3.12                  # ~4 min download
/home/xspace/.local/bin/python3.12 -m venv ~/.venvs/<name>
```

### 2. torch/torchvision — curl the wheel, install locally (pip -i hangs)

pip with `-i https://mirrors.aliyun.com/pytorch-wheels/cu124/` hangs; direct curl works:

```bash
mkdir -p /tmp/wheels && cd /tmp/wheels
# list available versions first:
timeout 20 curl -sL "https://mirrors.aliyun.com/pytorch-wheels/cu124/" | grep -oE 'torch-2\.[0-9.]+&#43;cu124-cp312-cp312-linux_x86_64\.whl' | sort -uV | tail
# download (torch ~2.4GB @ 2.3MB/s ≈ 15-20 min; run as background process with notify_on_complete)
curl -sL -o "torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl" \
  "https://mirrors.aliyun.com/pytorch-wheels/cu124/torch-2.6.0%2Bcu124-cp312-cp312-linux_x86_64.whl"
# ALWAYS verify: python3 -c "import zipfile; zipfile.ZipFile('x.whl')" — truncated downloads are common, pip then says "invalid wheel"
~/.venvs/act/bin/pip install --no-deps torch-*.whl torchvision-*.whl
```

**CRITICAL — torch+cu124 needs the nvidia runtime wheels, install them ALL with --no-deps:**
`nvidia_cuda_runtime_cu12 nvidia_cuda_nvrtc_cu12 nvidia_cudnn_cu12 nvidia_cufft_cu12 nvidia_curand_cu12 nvidia_cusolver_cu12 nvidia_cusparse_cu12 nvidia_cusparselt_cu12 nvidia_nccl_cu12 nvidia_nvjitlink_cu12 nvidia_nvtx_cu12 nvidia_cuda_cupti_cu12` (cublas too).
Missing any → `ValueError: libcublas.so.*[0-9] not found` / `libcudnn.so` at import. Download each from the same cu124 listing (cudnn ~665MB, cufft ~211MB — big, run in background). Verify:
```bash
~/.venvs/act/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
# → 2.6.0+cu124 True NVIDIA GeForce RTX 4060 Laptop GPU
```

### 3. lerobot + deps

```bash
~/.venvs/act/bin/pip install --no-deps -e .          # package itself
# Then deps with --no-deps per package from aliyun pypi:
#   numpy>=2.0,<2.3 (lerobot pins <2.3; 2.5.1 incompatible), transformers<5, huggingface_hub, timm, einops,
#   certifi charset_normalizer idna urllib3 requests filelock pyyaml regex tokenizers safetensors pillow tqdm
#   h11 httpcore httpx packaging typing-extensions
```
**Pitfall**: installing with deps enabled lets pip re-resolve `torch` from PyPI → replaces your CUDA build with CPU torch 2.13. Always `--no-deps` for anything that might touch torch, then fix ImportErrors one module at a time.
**tokenizers pin**: transformers 4.5x requires `tokenizers>=0.22.0,<=0.23.0`; 0.23.1 gets rejected at import ("tokenizers==0.23.1 ... required 0.23.0"). Pin `tokenizers==0.23.0`.

## Pitfalls

- **/tmp 是 tmpfs 内存盘, pip 大包安装会撑爆它 (2026-08-01 实测)**: WSL/容器里 `/tmp` 常是 tmpfs (如 7.8G), pip 解包 torch 等大 wheel 时临时文件全进 /tmp → `OSError: [Errno 28] No space left on device` (而根盘 `df -h /` 显示还有 900G+ 空闲, 容易误判)。症状: 后台 pip install 进程退出, 日志尾部 tempfile cleanup OSError。修: `export TMPDIR=/home/xspace/pip-tmp` (指向磁盘) 再跑 pip, 或在每个 pip 命令前加 `TMPDIR=<磁盘路径>`。清理: `rm -rf /tmp/wheels* /tmp/pip-unpack-* /tmp/tmp*`。诊断: `df -h /tmp` 看使用率 (97% 即中招)。
- **清华 pypi 镜像也会 403**: `https://pypi.tuna.tsinghua.edu.cn/simple/` 返回 403 (nginx) 时换 `https://mirrors.aliyun.com/pypi/simple/` — 阿里云实测 200。换镜像前先 `curl -sI <mirror>/simple/<pkg>/` 看 HTTP 码, 别盲试。
- `pip install` with a package that pulls torch/timm → silently starts downloading CPU torch 2.13 (526MB). `pkill -f "pip install"` and retry with `--no-deps`.
- Big wheels silently truncate: always `zipfile.testzip()` before pip install; re-download with `curl --retry 3` if invalid.
- `--range 0-10000000` curl range requests give a quick speed probe without full download.
- HF model downloads: set `HF_ENDPOINT=https://hf-mirror.com` before importing huggingface_hub in scripts (lerobot `infer_*.py` already does this).
- After install, run `act_infer.py` (see zmax-console skill §8) as the functional smoke test — import + CUDA + dummy inference, not just `import torch`.

## torch cu128 依赖缺口 + ldconfig (2026-08-24 实测)

- torch 2.7.1+cu128 比 cu124 多两个依赖: `nvidia-cufile-cu12`(libcufile.so.0) 和 `triton==3.3.1`。wheels 清单漏 cufile → `import torch` 报 `libcufile.so.0 not found`。triton 只 torch.compile 用, 训练可跳过。
- **cusparselt rpath bug**: torch slim wheel 的 `libtorch_global_deps.so` rpath 把 cusparselt 写成 `$ORIGIN/../../cusparselt/lib`(少了 `nvidia/` 前缀, 正确是 `nvidia/cusparselt/lib`) → `libcusparseLt.so.0 not found`。
- **一次解决所有 rpath 问题: ldconfig 全局持久化**(比 LD_LIBRARY_PATH 干净, 重启不丢):
  ```bash
  SP=<venv>/lib/python3.11/site-packages
  find $SP/nvidia -name lib -type d > /tmp/nvidia-libs.txt; echo "$SP/torch/lib" >> /tmp/nvidia-libs.txt
  sudo sh -c "cat /tmp/nvidia-libs.txt > /etc/ld.so.conf.d/nvidia-pip.conf"; sudo ldconfig
  ```
- 验证别只看 is_available, 跑真 matmul 确认 GPU 真在算: `x=torch.randn(1000,1000,device='cuda'); (x@x).sum()`。
- CPU 训的 ultralytics checkpoint 不能 `resume=True` 迁 GPU(空 GradScaler → `RuntimeError: source state dict is empty`), 要 `YOLO(last.pt)` 作 warm-start 权重 + 正常 `train()`。

## Reference

- Full wheel URL patterns + nvidia package list script: `references/aliyun-wheel-urls.md`
