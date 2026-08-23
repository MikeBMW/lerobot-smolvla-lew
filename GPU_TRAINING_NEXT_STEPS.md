# GPU 训练续接清单 (2026-08-24 静静)

目标：状态空间 YOLO 深度感知真闭环训练。4060 GPU 已全通。

## ✅ 已完成 (08-24 本次重启后)
- nvidia 驱动 580.126.09 全通 (内核模块 = 用户态版本, 匹配)
- 设备节点持久化: systemd 服务 nvidia-device-nodes.service (跑 /sbin/ub-device-create)
  - 根因: LiveUSB 重启后 /dev 是 tmpfs, /dev/nvidia* 节点丢; udev 规则(71-nvidia.rules→ub-device-create)没在模块加载时触发
  - 手动 mknod 救急一次, 服务已 enable 持久化 (重启自愈)
- torch 2.7.1+cu128 装进 gui-venv311 (替换 cpu 版, pip 补装 ensurepip)
  - 缺 nvidia-cufile-cu12 + cusparselt rpath bug → /etc/ld.so.conf.d/nvidia-pip.conf + ldconfig 持久化
- CUDA 验证: cuda_available=True, RTX 4060 Laptop GPU, matmul 实测通过 (非假 is_available)

## 🔄 进行中
- 深度模型 GPU 训练 (warm-start from last.pt, --device 0 --batch 16 --epochs 50)
  命令: DISPLAY=:0 gui-venv311/bin/python src/lerobot/policies/yolo_3d/train_depth.py --epochs 50 --batch 16 --device 0 --name peg_depth_v1 --resume
  - CPU→GPU resume 报空 GradScaler → 改 warm-start (YOLO(last.pt) + 正常 train, 已 commit 31a431bc)

## 剩余步骤
1. 深度训练完成 → 验证 best.pt 更新 (outputs/yolo_peg_depth/peg_depth_v1/weights/best.pt)
2. 深度 o_model 重训双脑:
   DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/train_full_pipeline.py --eps 30 --epochs 800
   (train_full_pipeline.py 已改好: _build_aligner 深度权重 _DEPTH_WEIGHTS_CANDS 指向 peg_depth_v1/best.pt + 真闭环吃 o_model)
3. 真闭环验证拿真实数字

## 关键背景 (勿重踩)
- 旧 full_pipeline.pt 是"写死 z 时代", 归一化 xs 有 24 维≈0, 深度反投影会爆炸 (act_z 282~1066) → 必须深度 o_model 重训
- 深度数据 3600 张: data/yolo_peg_depth/ (387M)
- DEPTH_SCALE peg/hole=1.685, hand=1.566
- CPU→GPU 迁移坑 + torch cu128 依赖缺口 → 技能 python-ml-env-mirrors
- 深度感知链全流程 → 技能 yolo-3d-perception-chain
