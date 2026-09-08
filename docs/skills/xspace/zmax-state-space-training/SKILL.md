---
name: zmax-state-space-training
description: state_space 训练失败(lerobot-venv 缺/tasks.parquet 缺)时重建环境.
---

# Z-MAX state_space 训练环境重建 + 数据集修复

state_space(状态空间·仿真蒸馏) 训练走 `~/lerobot-venv/bin/python -m lerobot.scripts.lerobot_train`，
不用 docker/远程。LiveUSB overlay 重启后 `~/lerobot-venv` 会丢，需重建。

## 症状 → 根因对照

| 日志 | 根因 |
|------|------|
| `❌ 本地 CPU 训练环境缺失 (~/lerobot-venv)` | venv 丢了, 重建(见下) |
| `httpx.ConnectError: Network is unreachable` + 堆栈在 `get_safe_version` | 数据集缺 `meta/tasks.parquet`(lerobot 0.5.2 load_tasks 必需), _load_metadata 抛 FileNotFoundError 误走 HF Hub |
| `ModuleNotFoundError: No module named 'typing_extensions'` | torch 用 --no-deps 装漏了运行时依赖 |

## 环境重建 (~/lerobot-venv)

1. **必须 Python 3.12**(lerobot `requires-python>=3.12`, 3.11 会警告且后续失败):
   ```bash
   /home/ubuntu/.hermes/bin/uv venv ~/lerobot-venv --python 3.12
   ```
2. **固定 torch==2.7.1+cu128**(不是 uv 默认解析的 2.11! 2.11 要新版 nvidia 库 2.9GB 下载)。
   下载 torch cp312 wheel 用 **aliyun 镜像**(比 pytorch.org 快一个量级):
   ```bash
   cd /home/ubuntu/wheels-cu128
   curl -sL -o torch-2.7.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl \
     "https://mirrors.aliyun.com/pytorch-wheels/cu128/torch-2.7.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl"
   curl -sL -o torchvision-0.22.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl \
     "https://mirrors.aliyun.com/pytorch-wheels/cu128/torchvision-0.22.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl"
   ```
3. 装 torch/torchvision(本地 wheel, --no-deps):
   ```bash
   uv pip install --python ~/lerobot-venv/bin/python --no-deps \
     /home/ubuntu/wheels-cu128/torch-2.7.1+cu128-cp312-*.whl \
     /home/ubuntu/wheels-cu128/torchvision-0.22.1+cu128-cp312-*.whl
   ```
4. **复用 gui-venv311 的 nvidia 库**(py3-none 通用, 跨 python 版本)+ **伪造 dist-info 版本号**匹配 torch 2.7.1 的 `==` pin(否则 uv 严格按 pin 重下 2.9GB):
   ```bash
   SRC=gui-venv311/lib/python3.11/site-packages/; SP=~/lerobot-venv/lib/python3.12/site-packages/
   cp -a "$SRC/nvidia" "$SP/" && cp -a "$SRC"/nvidia_*.dist-info "$SP/"
   ```
   然后 Python 脚本批量改 dist-info: 目录名 + METADATA `Version:` 行改成 torch 2.7.1 pin 值
   (cudnn→9.7.1.26, cublas→12.8.3.14, cufft→11.3.3.41, curand→10.3.9.55, cusolver→11.7.2.55,
   cusparse→12.5.7.53, cusparselt→0.6.3, nccl→2.26.2, nvtx→12.8.55, nvjitlink→12.8.61,
   nvrtc→12.8.61, cuda_runtime→12.8.57, cuda_cupti→12.8.57; cufile 1.13.0.11 已匹配)。
   nvidia 库向后兼容, 9.10.1.4 的 .so 伪装成 9.7.1.26 完全能跑(见下方验证)。
5. 装剩余训练依赖(固定 torch 让 uv 跳过 nvidia 下载):
   ```bash
   cd /home/ubuntu/lerobot-smolvla-lew
   uv pip install --python ~/lerobot-venv/bin/python -e ".[training]" "torch==2.7.1+cu128" "torchvision==0.22.1+cu128"
   ```

## 数据集 tasks.parquet 缺失

lerobot 0.5.2 `LeRobotDatasetMetadata._load_metadata` 顺序:
`load_info → check_version_compatibility → load_tasks(meta/tasks.parquet) → load_episodes`。
缺 tasks.parquet → load_tasks 抛 FileNotFoundError → 走 `get_safe_version(repo_id)` 访问 HF Hub → 离线报 Network unreachable。

补写(state-only 无语言任务, 单个占位 task):
```python
import pandas as pd
pd.DataFrame({'task_index':[0]}, index=pd.Index(['insert_peg'], name='task')).to_parquet('data/ss_insert_lerobot/meta/tasks.parquet')
```
`tools/build_ss_dataset.py` 已补写(根治, 以后生成不会再缺)。

## 验证

```bash
# CUDA + lerobot 导入
~/lerobot-venv/bin/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0)); import lerobot"
# 3 步 smoke test(全链路: dataset→policy→optimizer→训练循环)
# 写 /tmp/ss_smoke.yaml(steps:3, root 绝对路径 data/ss_insert_lerobot), 然后:
~/lerobot-venv/bin/python -m lerobot.scripts.lerobot_train --config_path /tmp/ss_smoke.yaml
```
成功标志: `Creating dataset → Creating policy → num_learnable_params=635180 → Training .../3 → End of training`。

## 坑

- torch 2.7.1+cu128 的 METADATA 里 nvidia 是 `==` 精确 pin, uv 严格匹配 → 复用本地更高版本库必须伪造 dist-info。
- torch 本体是 cp312 ABI 特定, 不能从 gui-venv311(cp311) 复制; 但 nvidia 库是 py3-none 可复制。
- triton 是 cp312 特定, 必须从 PyPI 下载(179MB), 不能复用。
- uv 后台跑要先确认 PATH 有 uv(它装在 ~/.hermes/bin/uv, 后台 shell 可能没有 → 用完整路径)。
