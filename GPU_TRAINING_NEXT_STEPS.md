# GPU 训练续接清单 (2026-08-24 静静, 关机前保存)

目标：状态空间 YOLO 深度感知真闭环训练。

## ✅ 已完成 (08-24)
- 4060 GPU 全通 (驱动 580.126.09 + 设备节点 systemd 服务持久化 + torch cu128 + ldconfig)
- 深度模型 GPU 训练完成: outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt (abs_rel 0.94%, 自动校准 b=0.604)
- 双脑训练跑通 (但评估 0/8 未解决)

## 🔧 已修复的 3 个 bug (已 commit)
1. cuda tensor bug: depth.data 是 cuda tensor → np.asarray 抛异常被 except 吞 → 回退写死 z
   修: yolo_state_aligner.py detect_3d 加 .detach().cpu().numpy()
2. depth scale 重标定: GPU+自动校准后 scale 变了, 旧 1.685/1.566 作废
   新: DEPTH_SCALE=0.978 (peg/hole), DEPTH_SCALE_HAND=0.885 (hand)
   标定脚本 tools/diag_depth_calib.py
3. 专家动作 clip: metaworld policy 输出超 [-1,1] 动作, ys=[3.55,...] 超范围
   修: train_full_pipeline.py collect_data 加 a=np.clip(a,-1,1)

## ❌ 未解决 (下次继续)
- 评估仍 0/8 卡"接近", hand 卡 d_hp≈0.15 下不去
- 诊断: hand_z≈0.14 vs peg_z≈0.02 (z 差 0.12), act_z 已正常(-1.4 朝下)但 hand_z 卡 0.14 降不下去
- 疑似: 物理碰撞 / 水平对位没做好 / 接近逻辑 z 分量不够

## 下次步骤
1. 跑 tools/diag_eval_loop.py 看 hand 为什么卡 z=0.14 (物理碰撞? 对位?)
2. 对比 CPU 时代"抓起 8/8"的代码差异 (git log 找深度改造前的版本)
3. 可能: 接近逻辑 z 分量增强, 或先水平对位再下降
4. 真闭环验证拿真实数字

## 关键路径
- 深度模型: outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt (GPU, 自动校准)
- 检测模型: runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt
- 双脑: outputs/rl_peg/full_pipeline.pt (当前 0/8 版本)
- 训练命令:
  DEPTH_SCALE=0.978 DEPTH_SCALE_HAND=0.885 DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/train_full_pipeline.py --eps 30 --epochs 800
- 详见技能 yolo-3d-perception-chain §GPU 深度闭环 + python-ml-env-mirrors §cu128
