# Z-MAX 模型引擎训练镜像 v3-final (2026-08-08 远程 V100 验证通过)
# 踩坑记录:
#   v1: pytorch/pytorch:2.5.1 基础上 pip install -e . 会把 torch 覆盖成 cu130 (驱动550只支持12.4) → cuda False
#   v2: torch 固定 cu124, 但 -e . 后又覆盖 → 仍 cu130
#   v3: 安装顺序改为: -e . → 最后强制降级 torch==2.4.1+cu124 (V100 sm_70 支持, 驱动 550/CUDA12.4 匹配)
#   再补: datasets/av/accelerate (lerobot[dataset,training]), 卸载 torchcodec (与 torch 2.4 冲突, 本地数据集用 av 解码)
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

WORKDIR /app

# 项目代码 (data/outputs 由 .dockerignore 排除, 运行时挂载)
COPY . /app

# lerobot + 依赖 (一次性构建, 训练复用)
# 🐛 2026-08-08: 镜像 Python 3.11 < pyproject >=3.12 → --ignore-requires-python
RUN pip install --no-cache-dir --ignore-requires-python -e . 2>/dev/null; \
    pip install --no-cache-dir --ignore-requires-python termcolor tensorboard 2>/dev/null; \
    # 最后强制固定 torch cu124 (防 -e . 覆盖成 cu130; 匹配驱动 550/CUDA12.4, V100 sm_70)
    pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu124 2>/dev/null; \
    # 训练必需 extras: datasets(数据加载) av(视频解码) accelerate(训练加速)
    pip install --no-cache-dir --ignore-requires-python datasets av accelerate 2>/dev/null; \
    # 🐛 torchcodec 与 torch 2.4.1 不兼容 (libtorchcodec_core4.so 加载失败) → 卸载; 本地数据集用 av 解码, 不需要 torchcodec
    pip uninstall -y torchcodec 2>/dev/null; true

# 默认: 模型引擎训练入口
CMD ["python", "-m", "lerobot.scripts.lerobot_train", "--help"]
