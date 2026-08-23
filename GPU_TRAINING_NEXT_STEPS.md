# GPU 训练续接清单 (2026-08-23/24 静静)

重启后从这里继续。目标：状态空间 YOLO 深度感知真闭环训练。

## 当前状态
- GPU 驱动已装：linux-modules-nvidia-580-6.17.0-14-generic + nvidia-utils-580 + libnvidia-*(gl/compute/decode/encode/cfg1)
  - 都是 Canonical 签名，SecureBoot 零人工（不需要 MOK）
- nouveau 已 blacklist：/etc/modprobe.d/blacklist-nouveau.conf
- 重启后 nvidia 自动接管（modinfo nvidia 有 alias pci:v000010DEd*...bc03sc00i00*，匹配 4060 [0300]）
- CUDA torch wheel 已下载并 zip 校验 OK：/home/ubuntu/wheels-cu128/ (3.7G)
  - torch-2.7.1+cu128-cp311-cp311-manylinux_2_28_x86_64.whl
  - torchvision-0.22.1+cu128-cp311-cp311-manylinux_2_28_x86_64.whl
  - nvidia_*_cu12 全套 (cublas/cudnn/cufft/curand/cusolver/cusparse/cusparselt/nccl/nvjitlink/nvtx/cupti/cuda_runtime/cuda_nvrtc)

## 重启后步骤
1. 验证 GPU：`nvidia-smi`（应显示 RTX 4060 Max-Q）。若没自动加载：`sudo modprobe nvidia && sudo modprobe nvidia_uvm`
2. 装 CUDA torch 到 gui-venv311（替换 cpu 版）：
   ```
   export TMPDIR=/home/ubuntu/pip-tmp; mkdir -p $TMPDIR
   cd /home/ubuntu/wheels-cu128
   /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/pip install --no-deps --force-reinstall torch-2.7.1+cu128-*.whl torchvision-0.22.1+cu128-*.whl nvidia_*.whl
   ```
   （注意：pip 用 --no-deps 避免拉 CPU torch；TMPDIR 指磁盘防 /tmp tmpfs 撑爆）
3. 验证：`gui-venv311/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
4. 深度模型训练（GPU）：改 train_depth.py 的 device 或加 --device 0
   ```
   cd /home/ubuntu/lerobot-smolvla-lew
   DISPLAY=:0 gui-venv311/bin/python src/lerobot/policies/yolo_3d/train_depth.py --epochs 50 --batch 16 --device 0 --name peg_depth_v1
   ```
5. 深度 o_model 重训双脑：
   ```
   DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/train_full_pipeline.py --eps 30 --epochs 800
   ```
   （train_full_pipeline.py 已改好：_build_aligner 深度权重 + 评估真闭环吃 o_model）
6. 真闭环验证拿真实数字

## 关键背景（勿重踩）
- 旧 full_pipeline.pt（outputs/rl_peg/）是"写死 z 时代"训练，归一化 xs 有 24 维≈0，深度反投影输入会爆炸（act_z 飙 282~1066）。必须用深度 o_model 重训。
- 深度模型训练产物：outputs/yolo_peg_depth/peg_depth_v1/weights/best.pt（CPU 训练到 epoch15，abs_rel 1.6%）
- 深度数据 3600 张：data/yolo_peg_depth/ (387M)
- 深度反投影 per-class scale：peg/hole DEPTH_SCALE=1.685, hand DEPTH_SCALE_HAND=1.566
- 详见技能 yolo-3d-perception-chain
