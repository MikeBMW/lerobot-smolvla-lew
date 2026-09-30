# Z-MAX 感知层 sim→real 无缝移植 (YOLO · 2026-09-17)

老倪: 「这段代码原来是适配仿真程序的，现在引入真机的 realsense 相机，需要做什么修改？
目标是仿真运行完成后，要无缝移植到真机。你来设计流程，跑通 sim to real 流程；我要用 yolo
目标检测的模型，运行在 orin 上，能够感知实际的机器人环境。」

## 一、结论先说 (实测证据)

| 项 | 结果 | 证据 |
|---|---|---|
| 仿真路径零回退 | **逐位一致** (差 0.00e+00) | `verify_aligner_zero_regression.py` 4 seed 同帧新旧实现比对 |
| 真机/仿真几何同口径 | **差 2.22e-16** (机器精度) | `verify_sim2real_geometry_parity.py` 同一帧同一深度两条路径 |
| YOLO 在 Orin 上跑真机相机 | **✅ 真跑** 36ms/帧 GPU (27.7 FPS) · 892ms CPU | Orin 上 `tools/real_yolo_perceive.py --source uvc:2` |
| 真机像素来源 | ✅ D405 UVC 直读 (Orin `/dev/video2`, 640x480 MJPG), **零安装** | `d405_uvc_probe` 实测 |
| 真机 3D 定位 | ❌ **未打通**: 缺真机相机内参/外参标定 + 缺米制深度 | meta.gaps 显式报 |
| 仿真权重在真机的检测能力 | ❌ **0/4 帧, 4 种朝向全 0** (最高分 0.0105, 阈值 0.25) | `probe_sim2real_domain_gap.py` (对照组: 仿真帧 0.95~0.97) |

**一句话**: 代码与流程已经做到"换源即换世界"(仿真/真机同一份检测与反投影), 并已在 Orin 上
用真实 D405 跑通；但**模型本身还看不懂真机画面**(域差), 需要在真机数据上微调/重训才谈得上
"感知实际机器人环境"。这条缺口是数据问题, 不是接线问题。

## 二、差异点收口: 只有 5 处, 全在 FrameSource

`src/lerobot/policies/yolo_3d/frame_source.py` 把仿真与真机的全部差异收口到一个源:

| 差异 | 仿真 (SimFrameSource) | 真机 (RosFrameSource / UvcFrameSource) |
|---|---|---|
| 图像 | `env.render()` (mujoco corner2) | `/realsense/color/image_raw` 或 `/dev/videoN` |
| 内参 K | `cam_fovy` (白送) | `camera_info` / 标定文件 |
| 深度 | YOLO depth head (仿真标定尺度 0.9616) | RealSense 米制深度 (scale=1.0) |
| 外参 T_base_cam | `cam_pos`/`cam_mat0` (白送) | tf(base_link→camera) / 手眼标定 |
| 朝向/通道 | `train_rot_k=2` (训练集是 rot90 存盘), RGB→BGR | `train_rot_k=0`, UVC 本身 BGR |

检测与反投影**只有一份代码** (`YoloStateAligner.estimate_3d`), sim 源走原实现
(`_detect_3d_sim_legacy`, 逐位不变) —— 这就是"无缝"的含义: 不是两套实现对齐, 而是一套。

**不编造纪律**: 缺内参/外参/深度一律进 `meta["gaps"]`, 并在相机系给点, 绝不冒充 base 系。

## 三、跑通流程 (命令)

```bash
# ① 仿真 (回归基线, 与改造前逐位一致)
DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/real_yolo_perceive.py --source sim --frames 5

# ② 真机: 4060 侧 Docker 只读订阅 Orin 话题 (Orin 零程序红线)
sudo docker run --rm --network host -e ROS_DOMAIN_ID=0 ros:humble-ros-base \
  bash -c 'source /opt/ros/humble/setup.bash; python3 /repo/tools/ros_record_realsense.py --out /out --frames 12'

# ③ 真机: Orin 本机 UVC 直读 (无需任何 RealSense SDK/驱动)
ssh tashan@192.168.23.66 'cd /home/tashan/zmax_yolo && python3 tools/real_yolo_perceive.py \
  --source uvc:2 --frames 10 --weights weights/yolo_peg_best.pt --out out'

# ④ 标定 (真机 3D 的前置: 内参 → 外参 → 台面高度)
python3 tools/calib_real_cam.py --intrinsics <棋盘格图目录>     # K
python3 tools/calib_real_cam.py --handeye   <手眼标定图目录>     # T_base_cam + plane_z 人工量一次
```

## 四、真机侧当前事实 (2026-09-17 实测)

- **Orin 上有 D405 相机** (`lsusb`: Intel RealSense D405)，但 **`realsense2_camera` ROS 驱动没装**:
  `/realsense/*` 话题 Publisher count = **0** (只有 vision_tag / ss_remote_tap 在订阅) ⇒ 走 ROS 拿不到帧。
- 因此真机像素走 **UVC 直读** `/dev/video2`、`/dev/video4` (640x480 MJPG 有画面, video0/1/3/5 被占用)。
  这是零安装路径, 也是当前唯一能拿到真像素的路。
- `/robot/tcp_pose` 50Hz 真值在线 (frame_id=base_link) → 真机 hand 位姿用它 (R1 契约: 末端=编码器)。
- `/vision_tag` 在生产栈里跑 (FoundationPose), 发布 `/foundationpose/tray_reference/debug_image`
  与 `/visualization_marker_array` → **可作为自动标注的教师源** (见第六节)。
- Orin 无外网: ultralytics 用离线轮子装进 `~/.local` (`/home/tashan/zmax_yolo/wheels`)。
- Orin 的 torch 2.5.0a0+nv24.08 与 torchvision 0.20.0 C++ ABI 不匹配 → ultralytics NMS 崩;
  已用纯 torch 备用实现兜住 (`tv_ops_shim.py`), 根治=装匹配的 NVIDIA torchvision。

## 五、真机 3D 的两个前置 (还没做, 各 10 分钟)

1. **内参 K**: `tools/calib_real_cam.py --intrinsics`(棋盘格) 或 RealSense SDK 直读工厂标定。
2. **外参 + 台面高度**: `--handeye`(机器人带板走位姿) + `plane_z` 人工量一次。
   在 `models/real_cam_calib.json` 填好后, `real_yolo_perceive` 的 `ext_src` 会从
   "无外参 → 输出相机系" 变成 "T_base_cam(tf/标定)", 3D 直接落在 base_link 系, 可与 tcp_pose 对齐。
3. (可选, 更强) 起 RealSense ROS 驱动 → 直接拿米制深度 + `*_aligned_depth*` → 无需 plane_z 回退。

## 六、把"0 检出"变成"能感知": 三条路 (按性价比)

1. **真机数据微调 (必做)**: 采 300~500 张真机帧 (含光模块/孔位在画面内的位姿), 标注 → 在
   `yolo_peg_v1` 权重上微调 (和仿真数据混合, 防遗忘) → 换权重即生效 (代码零改动)。
2. **教师蒸馏自动标注 (省人力)**: 生产栈的 FoundationPose/vision_tag 已在做真机定位 →
   把它的 3D 位姿投影回图像生成框 (或用 `/visualization_marker_array`), 批量伪标注 + 人工抽检。
3. **域随机化补仿真**: 在 `gen_yolo_data.py` 里加真实光照/纹理/相机噪声/背景干扰随机化再重训,
   缩小域差 (成本最低, 但天花板低于真机数据)。

## 七、文件清单 (本次新增)

| 文件 | 作用 |
|---|---|
| `src/lerobot/policies/yolo_3d/frame_source.py` | 四种输入源 + 口径声明 (唯一差异点收口) |
| `src/lerobot/policies/yolo_3d/yolo_state_aligner.py` | 统一入口 `detect_3d`/`detect_3d_meta`/`estimate_3d`; 原仿真实现保留为 legacy 分支 |
| `src/lerobot/policies/yolo_3d/tv_ops_shim.py` | Jetson torch/torchvision ABI 不匹配时的纯 torch NMS/IoU 兜底 |
| `tools/real_yolo_perceive.py` | 真机/仿真统一感知入口 (sim/ros/uvc/file) → 39D 契约 + 取证 json |
| `tools/ros_record_realsense.py` | 4060 侧 Docker 只读采真机帧 (Orin 零程序) |
| `tools/ros_scan_image_topics.py` | 扫"哪路像素真有 publisher" (避免假设有帧) |
| `tools/calib_real_cam.py` | 真机内参/手眼标定 → `models/real_cam_calib.json` |
| `models/real_cam_calib.json` | 标定文件 (当前未标定, 显式 reason) |
| Orin `/home/tashan/zmax_yolo/` | ultralytics 离线轮子 + 同一份代码 + 权重 (仅用户目录, 非自启) |
