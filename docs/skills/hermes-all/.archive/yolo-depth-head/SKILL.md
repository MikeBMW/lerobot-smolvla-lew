---
name: yolo-depth-head
description: 给 YOLO 加 depth head 恢复 z 深度, 替代写死深度平面。
---

# YOLO Depth Head — 单目深度估计恢复 z (替代写死深度平面)

## 触发
- YOLO 检测 2D 框要反投影 3D 时, 发现 z 是写死的 (如 `z_map={"hand":0.155,"peg":0.03,"hole":0.129}`), 导致 z 方向判断(抬起/插入深度)全盲
- 真机同构: 仿真里不能白给 z 真值, 要让感知模型自己估深度
- 给现有检测 YOLO 加深度输出

## 核心认知: 写死 z 平面 = z 方向盲 (2026-08-23 实测)
- 用固定 z 平面反投影 2D 框 → 3D 的 z 恒等于写死值, 与物体真实高度无关。
- 后果: 状态机 z 判据 (peg 抬起 `peg[2]-peg_z0>0.02`、插入 `d_ph<0.05`) 永远不触发 → 卡死在接近/抓取阶段, 成功率 0。
- 真闭环 (状态机判断+动作调制吃 YOLO 解算 state, 不吃仿真器真值 `env.data.site_xpos`) 的前提是 z 必须来自深度估计。
- 铁律: 状态机判断/动作调制若吃仿真器真值坐标 = 假同构 (真机拿不到真值)。

## ultralytics 8.4 内置 depth 任务 (不用改源码!)
- `DepthModel` (nn/tasks.py) = YOLO backbone + FPN + **DPT-style dense depth head** (Depth Anything 风格), 参数量 yolo26n-depth ≈ 5.17M。
- `DepthLoss26` (utils/loss.py) = **SILog** (scale-invariant log) + 多尺度梯度匹配 loss。SILog 是 scale-invariant → 模型有尺度歧义, 训练后自动校准。
- head 内部 `depth = torch.exp(out.clamp(-4.0, 5.0))` → 输出米制深度(正数)。
- 训练自动 scale-calibration: 结束写 `cal_a/cal_b` 进 best.pt (`scale-only`, e.g. a=1.0 b=0.58 即乘 e^0.58 校正尺度)。

### 数据格式 (DepthDataset)
- 目录: `images/` + `depth/` 配对, 深度是 **16-bit PNG**, `depth_scale` 表示 1 米 = N PNG 值。
- data.yaml:
  ```yaml
  path: <root>
  train: images
  val: images
  nc: 1
  names: {0: depth}
  channels: 3
  depth_scale: 256   # PNG value 256 = 1 米
  ```
- 无效深度: SILog loss 用 `valid = gt_depth > 0.001` 过滤 (depth≈0 不参与)。

### 训练命令 (CPU 可跑)
```python
from ultralytics import YOLO
model = YOLO("yolo26n-depth.yaml")   # 从零训, 无 depth 预训练权重
model.train(data=".../data.yaml", epochs=50, imgsz=480, batch=8, device="cpu")
```
- 1800 图 (12 eps × 150 步), CPU 3.1 it/s ≈ 72s/epoch, 2 epoch 冒烟就 delta1=0.97 / abs_rel=5.3%。

## mujoco/metaworld 深度图生成 (真值监督)
- metaworld `render_mode="rgbd_tuple"` 一次 render 返回 `(rgb, depth)` **逐像素对齐** (480×480)。比两个 env 分别 render 省心且不跑偏。
- mujoco depth buffer 是**透视归一化** [0,1] (0=近 1=远), 不是线性米制。
- 反推米制公式 (实测拟合, 各 seed 稳定): `depth = A - B/z` → `z = B / (A - depth)`。
  - peg-insert corner2 相机实测: **A=1.0002, B=0.0230**, 反推误差 mean≈3cm。
  - 拟合方法: 渲染 depth_array + `mujoco.mj_ray` 测已知物体真值深度, 最小二乘拟合 A/B。
- ⚠️ 背景 depth→1 时 `1/(A-depth)` 爆炸 (z 冲到 20-70m) → **clip 到 DEPTH_MAX** (如 3m) 或设 0 表无效。
- 存盘: `depth_u16 = clip(z * depth_scale, 0, 65535).astype(uint16)`, `cv2.imwrite(..., depth_u16)`。
- 帧方向对齐: RGB 和 depth 都要同样 `np.rot90(img, k=2)` (与检测训练数据一致), 否则检测框与深度图错位。

## 推理端取深度 + 3D 反投影
- `result.depth` 是 `DepthMap` 对象 (BaseTensor 子类), **深度数据在 `result.depth.data`** (H,W 米制)。
  - 🐛 直接 `np.asarray(result.depth)` 得 shape (H,W,0) 空数组 → 取 [vi,ui] 报 out-of-bounds。必须 `.depth.data`。
- 3D 反投影 (沿光轴深度 d → 沿 dir_w 距离 t):
  ```python
  forward = cam_mat.T @ np.array([0.0, 0.0, -1.0]); forward /= norm   # 光轴世界方向
  cos_t = float(np.dot(dir_w, forward))
  t = depth_m / cos_t if abs(cos_t) > 1e-4 else depth_m
  pt = cam_pos + t * dir_w
  ```
  (旧写死 z 的做法是 `t=(plane_z-cam_pos[2])/dir_w[2]`, 两者只差在深度来源。)

## 精度实测 (2 epoch 冒烟模型, 正式 50 epoch 会更好)
- peg z 误差 **1.3~2.5cm** (抬起判断 >2cm 够用)
- hole z 误差 3~10cm
- hand 偏差 12~17cm (细长机械臂末端, 深度模型在此处不准)
- 教训: 细长/边缘物体 (机械臂末端) 单目深度不可靠, 抓取触发别依赖 hand 深度, 改用「右脑 contact 持续 + peg 深度骤降」等非 hand 深度信号, 或取框内深度中位数而非中心点。

## 参考
- 39D obs 权威段位与 align peg 段 bug (真 peg=[4:7]/[22:25], 旧版误写 [18:21]=prev_hand) 见 `yolo-3d-perception-chain` 技能。
