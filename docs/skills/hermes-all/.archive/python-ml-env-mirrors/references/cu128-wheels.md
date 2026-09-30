# cu128 / torch 2.7.x wheel 下载 (2026-08-24 实测)

aliyun pytorch-wheels 目录: cu121/cu124/cu126/cu128/cu129/cu130/cu132

## 版本对应
- nvidia 驱动 580 → CUDA 12.8 → cu128 wheel
- py3.11 → cp311, py3.12 → cp312

## 文件名坑 (cu124 和 cu128 不同)
- cu124: `torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl`
- cu128: `torch-2.7.1+cu128-cp311-cp311-manylinux_2_28_x86_64.whl`  ← **manylinux_2_28, 不是 linux_x86_64**
- grep 用 `linux_x86_64` 会漏掉 cu128 的 wheel (只匹配 cu124 旧命名)。
- 目录页 HTML 里 `+` 显示为 `&#43;`, 下载 URL 用 `%2B` 转义。

## 实测下载清单 (cu128, py3.11, 共 3.7G, zip 校验全 OK)
- torch-2.7.1+cu128-cp311-cp311-manylinux_2_28_x86_64.whl (11502 files)
- torchvision-0.22.1+cu128-cp311-cp311-manylinux_2_28_x86_64.whl (291 files)
- nvidia_*_cu12 13 个 (12.8.x 系列): cublas 12.8.4.1 / cudnn 9.10.1.4 / cufft 11.4.0.6 /
  curand 10.3.9.90 / cusolver 11.7.3.90 / cusparse 12.5.8.93 / cusparselt 0.7.1 /
  nccl 2.27.3 / nvjitlink 12.8.93 / nvtx 12.8.90 / cupti 12.8.90 / cuda_runtime 12.9.37 / cuda_nvrtc 12.8.93

## 安装 (gui-venv311 py3.11, 替换 cpu 版 torch)
```bash
export TMPDIR=/home/ubuntu/pip-tmp; mkdir -p $TMPDIR   # /tmp 是 tmpfs, 防撑爆
cd /home/ubuntu/wheels-cu128
<venv>/bin/pip install --no-deps --force-reinstall torch-2.7.1+cu128-*.whl torchvision-0.22.1+cu128-*.whl nvidia_*.whl
```
- `--no-deps` 避免 pip 重新解析 torch 拉 CPU 版; `--force-reinstall` 覆盖现有 cpu torch。
- 验证: `<venv>/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
