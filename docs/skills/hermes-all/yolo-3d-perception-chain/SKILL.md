---
name: yolo-3d-perception-chain
description: YOLO 2D→3D→state 感知链, 含 ultralytics BGR 坑与同构评估原则。
---

# YOLO 3D 感知链 (仿真=真机同构)

## 🚀 sim→real 无缝移植 (2026-09-17 落地, Orin 已跑通真机相机)

**架构 = 差异点收口**: 仿真与真机只差 5 处 (图像来源 / 内参 / 深度 / 外参 / 朝向·通道口径),
全部收口到 `src/lerobot/policies/yolo_3d/frame_source.py` 的 `FrameSource`; 检测+反投影**只有一份代码**
(`YoloStateAligner.estimate_3d`), 仿真原实现保留成 `_detect_3d_sim_legacy` 走 sim 源 (零回退)。
四源: `SimFrameSource(env)` · `RosFrameSource(话题)` · `UvcFrameSource(/dev/videoN)` · `FileFrameSource(目录)`。
源 profile 声明: `train_rot_k` (仿真训练集是 rot90 k=2 → 真机 0) · `rgb_order` (ultralytics 吃 BGR) ·
`depth_metric` (米制深度=1.0 / 预测深度=套 DEPTH_SCALE) · `class_map(peg→光模块)` · `frame(world/base_link/camera)`。
统一入口: `tools/real_yolo_perceive.py --source sim|ros|uvc:N|file:DIR` → 39D 契约 + 取证 json + `meta.gaps`。

**实测取证 (reports/sim2real_20260917)**: 仿真零回退 **0.00e+00** (同进程同帧新旧实现) ·
通用几何 vs legacy **2.22e-16** (同帧同深度, 证明"真机那套"不是第二套实现) ·
**Orin 真跑** D405 UVC `/dev/video2` → YOLO GPU **36ms/帧 (27.7FPS)** / CPU 892ms。

**关键坑 (都踩过)**:
- **域差是硬缺口**: 仿真权重在真机 D405 帧 **0 检出** (4 种朝向全 0, 峰值分 0.0105 vs 阈值 0.25;
  对照组仿真帧 0.95~0.97) → 代码接通 ≠ 能感知, **必须真机数据微调/重训** (或教师蒸馏: 生产栈
  FoundationPose/vision_tag 的 3D 位姿投影回图像生成伪标签)。
- **别用"帧里有没有 depth"判断口径**: 预测深度也要套尺度校准 → 用**源声明** `depth_metric` 决定;
  且 YOLO depth head **只在 sim 源**用 (它按仿真渲染标定, 拿它预测真机像素=假证据)。
- **相机系约定**: 标准光学系 +x右/+y下/**+z朝前**; mujoco `cam_mat0` 是"看向 -z" → 标准系要乘
  `S=diag(1,-1,-1)` (det=+1 合法旋转), 且沿光轴深度的 cosθ 用**相机系**归一化射线 z 分量。
  少了这步: 3D 点整体偏 ~0.17m (实测)。
- **真机 D405 当前只能走 UVC**: Orin 上 `realsense2_camera` 驱动没装 → `/realsense/*` **Publisher=0**
  (图里有订阅者 ≠ 有帧! 先跑 `tools/ros_scan_image_topics.py` 看 pub count); D405 `/dev/video2`、
  `/dev/video4` 可读 640x480 MJPG, `video0/1/3/5` 被占用。
- **Orin 上 ultralytics 起不来 = torch/torchvision C++ ABI 不匹配** (Jetson torch 2.5.0a0+nv24.08 +
  通用 torchvision 0.20.0): `Couldn't load custom C++ ops` 崩在 NMS。Orin 无外网 → ①本机
  `pip download --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.10 --no-deps`
  下纯 python 轮子 (ultralytics/ultralytics-thop/polars/py-cpuinfo), scp 过去 `pip3 install --user --no-index` ;
  ②`yolo_3d/tv_ops_shim.py` 用纯 torch 实现 nms/batched_nms/box_iou 兜底 (只在 ops 真崩时打补丁)。
- **真机 3D 的两个前置**: 相机内参 K + 手眼外参 T_base_cam + 台面 plane_z → `tools/calib_real_cam.py`
  (棋盘格 `--intrinsics` / 手眼 `--handeye`), 写 `models/real_cam_calib.json`; 未标定时 `meta.gaps` 显式报
  "无外参 → 输出相机系", **绝不用仿真值冒充**。
- **真机 hand 用 `/robot/tcp_pose` 真值** (frame_id=base_link, 50Hz), 不用 YOLO hand (R1 契约: 末端=编码器)。
- 红线: Orin 侧**零自启** (只放 /home/tashan 用户目录文件); 采数据走 **4060 侧 Docker ros:humble --net host
  只读订阅** (`tools/ros_record_realsense.py`)。


## 🧪 域随机化 (DR) 能修域差吗? — 实测**不能**, 必须真机数据 (2026-09-17)

老倪: 「运行在 orin 上, 能够感知实际的机器人环境」。链路已通(上节), 但模型在真机 0 检出。
本轮把这条缺口做成**同口径 A/B 的三臂对照** (`docs/design/zmax_sim2real_dr_experiment.md`):

| 臂 | 训练数据 | 真机 19 帧×4 朝向 | 真机最高 conf | 仿真 hold-out |
|---|---|---|---|---|
| `peg_v1` (生产) | 仿真 1800 | 0 帧 / 0 框 | 0.0107 | 3.00 框/帧 · 60/60 · 0.96~0.97 |
| `ctrl_sim` (控变量) | 仿真 1800 重训 | 0 / 0 | 0.0301 | 3.00 · 60/60 · 0.96~0.97 |
| `dr_mix` (DR) | 仿真 1800 + DR 8100 | 0 / 0 | 0.0177 | 3.00 · 60/60 · 0.92~0.94 |

**结论: 纯仿真域随机化不足以跨到产线真机** (峰值 conf 只从 0.0107 抬到 ~0.03, 阈值 0.25 的 1/10;
76 次推理 0 检出), 且三臂仿真侧零回退。⇒ 必做 = 真机数据微调 或 教师蒸馏(FoundationPose 位姿投影回图像),
二者都要 Orin 在线。**DR 数据不白做**: 它是真机微调时的防遗忘混合集。

**DR 怎么做** (`gen_yolo_data.py --dr`, **默认关 = 零回退**): ①场景层 `--dr-scene`: 光照位置/方向/强度/色温/
环境光 · **全部材质颜色随机** · 纹理换随机噪声 · 相机 ±3cm/±5% fovy/±5° 旋转 (投影读同一份 model → 图像与标注天然同步)
②图像层: 亮度/伽马/对比/色偏 · 高斯噪声 · 运动/离焦/降采样模糊 · 暗角 · 随机遮挡 · 缩放裁切(框同步) ·
小角旋转 ±8°(框同步) · **灰底 114 letterbox**(复刻 640x480 真机帧送进 imgsz=480 的版式)。
判据工具: `tools/eval_sim2real_yolo.py` (多臂同口径: 真机 4 朝向 + 仿真 hold-out, 逐臂 json + 目检图) ·
`tools/analyze_real_det.py` (位置先验: 光模块现场在画面**下方正中** x∈[0.25,0.75] y∈[0.55,1.0]; 朝向一致性:
真检出应集中在同一 rot; 分帧组) · `tools/real_frame_selfcheck.py` (测集自检: 目标区到底有没有结构, 判定
"0 检出"是模型锅还是测集锅 — 本轮实测 11/19 帧目标区几乎无结构) · `tools/verify_dr_labels_geometry.py`。

**⚠️ 三个大坑 (都实测踩过)**:
1. **跨进程"逐位比对"在这套生成器上根本不成立**: metaworld 的场景随机向量走**全局 np.random**,
   `env.reset(seed=ep)` 不生效 → 同一份旧代码跑两次, 300/300 图**全不一样**。后果:
   (a) 零回退只能用**同进程等价性**证明(同 env 同帧, 新公式 vs 旧公式逐字符比 → 本轮 120/120 一致);
   (b) 训练/评测必须用**落盘固定数据集**, 别信"同 seed 重生成";
   (c) 要可复现必须显式 `--scene-seed`(新加, DR 模式默认带上; 实测同种子 300/300 文件逐位一致)。
2. **模板匹配验证标签一致性时, 底图必须放"唯一标记"**: 用规则矩形/规则纹理当底图 → `matchTemplate`
   歧义(匹配度 0.05~0.17) → **假失败**; 且 patch 的**缩放因子**(96×480/cw)与**旋转中心**(patch 自身中心,
   不是图像中心) 必须算对, 否则又是假失败(本轮前后踩了两次, 都是验证脚本 bug, 不是生成器)。
   正解: 唯一粗粒噪声标记 + patch 走同一几何变换链 → 60/60 通过, 最大错位 7.3px(中位 0.7px)。
3. **"0 检出"必须先做测集自检再下结论**: 真机帧可能有一半根本没对准目标区(纯背景/虚焦/纯黑) —
   拿它当分母会把"采集问题"误判成"模型不行"。测集自检: ROI 梯度密度 vs 全图 + ROI 内最大边缘连通块
   (>50px 才算有结构) + 3x3 区带物体化分布 + 退化帧(std<5)剔除。



老倪: 「现在要采集真机图片训练 YOLO。在右键打开的窗口增加标定功能: 标定工程师根据图像圈选光模块、
输入类别、保存当前图片, 而且 YOLO 模型可以通过保存的图片进行模型训练」(现场: 光模块只出现在画面**最下方正中**)

**三个件 (代码位置固定, 别另起炉灶)**:
| 文件 | 职责 |
|---|---|
| `tools/gui/yolo_label_widget.py` | 可拖框画面控件: 拖框/移动/四角缩放/右键删/撤销; **框永远存"原始帧像素坐标"** |
| `tools/yolo_annot_dataset.py` | 目录规范 + 保存 + 构建 + 体检 (库 + CLI): `--init/--build/--check/--stats/--import-yolo-dir` |
| `tools/yolo_annot_train.py` | 体检 → 选基座(auto=现有仿真权重微调) → ultralytics 训练 → **训练后真推理验证** |
| `tools/gui/yolo_input_viewer.py` | 「打开输入图像」窗口: ✏️标定模式 / 类别combo+新类别 / 💾保存 / ⏭保存并下一帧 / 🏷改选中类别 / 撤销 / 删选中 / 清空 / 🧊冻结 / 📦构建数据集 / 🔍体检 / 🚀训练 / 📂数据目录 |

**目录契约 (`data/yolo_annot`, data/ 已 .gitignore → 数据不进代码库)**:
`classes.txt`(行号=class id) · `sessions/<会话>/{frames,labels,session.json}`(溯源: 相机身份/seq/帧龄/标定员) ·
`annotations.jsonl`(追加式流水: 像素框+类别+来源) · `dataset/{images,labels}/{train,val}` + `data.yaml` + `stats.json`(构建层, **训练唯一入口**) · `meta.json`。
两层设计的原因: 会话层保**溯源**(防拿旧图冒充), 构建层保**可复现**(改 val 比例只重跑 --build)。

**必须记住的坑 (都实测踩过)**:
- **旋转窗标注要换算回原始帧**: 工程师可能在 180°/90° 旋转窗上圈选 → `unmap_box()` 换算; 存错=标签镜像的脏数据。
  实测: 0/90/180/270 拖框拆出的框都精确落回目标 (±3px)。
- **两个子窗共享同一组框** (都存原始坐标) → 任一窗改动同步到另一窗, 否则"在旋转窗标的框左窗看不见"。
- **类别 combo 打字别顺手改选中框**: 原实现把 combo 变更同步到 selected box → 工程师只想切"下一个框的类别"
  却把当前框改了 (实测踩到: 本想标 optical_module 的框变成 fiber_connector, class id 直接错)。
  正解 = 单独「🏷 改选中类别」按钮, combo 只管"新建框用什么类"。
- **小样本 val 兜底**: ultralytics 必须有非空 val; 样本<8 时 val 复用 train → **必须在 stats 里显式标注
  `val_overlap_train=true` + note"mAP 不可信"**, 统计别按两遍算 (框数会翻倍误导)。≥8 张时按文件名哈希划分 (可复现),
  并兜底强制至少一张进 val。
- **`--build` 后用硬链接** (跨盘自动退回拷贝) → 数据集不重复占盘。
- **体检必须能抓错** (反向验证): 注入 `class id 越界` + `中心>1` 两行 → check 必须报 2 个错, 恢复后 0 误报;
  纯"跑通"不算证据。体检项: 配对/字段数/类别范围/坐标范围/退化框/重复图 md5/空标注(背景样本)/data.yaml nc 一致性。
- **保存口径**: 图片 = 窗口那一帧的像素 (真机源从 Orin JPEG 解码后 q95 重编码), **不旋转**, 与推理输入同向;
  0 框也保存 (背景负样本, 空 .txt)。
- **窗口改码后要先在真桌面 (192DPI) 量一遍**: 标定行 13 个按钮实测不截断 (实际宽 ≥ sizeHint); offscreen 96DPI 会误判。
- **chk_rot 在 connect 之前 setChecked(True)** → toggled 不触发 → 右窗(构造时已 hide)永远不显示;
  必须显式调一次 `_apply_rot_vis()`。凡是"默认开 + 靠 toggled 生效"的开关都有这个坑。
- **GUI 与数据层解耦**: GUI `import yolo_annot_dataset as yad`, 保存走 `yad.save_sample()` —— 加新入口
  (网页/命令行/批处理) 复用同一落盘逻辑, 别在 GUI 里手写文件。
- **⚠️ 入口控件绝不能藏 (2026-09-17 用户实测: 「窗口的标定按钮怎么没有找到? 无法拉出边界框啊」)**: 首版
  `_set_annot_visible(False)` 把「✏️ 标定模式」**勾选框自己也 hide 了** → 界面上没有任何标定入口, 用户永远打不开
  标定 (死锁)。**offscreen 取证照样全绿** —— 因为断言是程序化 `setChecked(True)`, 绕过了"人能不能点到"。
  铁律: **开关类入口控件恒常显**, 只隐它的下级控件; 并在旁边给一句常显提示"下一步点哪"
  (自解释)。取证必须加一条**入口可达性断言**: 默认状态 `chk_annot.isVisible() and isEnabled()`
  + 打开后逐个按钮 `isVisible() and width()>20`。
- **⚠️ 长文本 QLabel 会顶宽整个窗口 (真桌面才暴露)**: 数据行(lbl_data: 长路径+类别表)与提示语用默认
  SizePolicy 时, QLabel 的 minimumSizeHint = 整行文字宽 → 把窗口撑到 **2436px**, 在 1920 屏上直接出屏
  (用户看到"窗口跑到屏幕外面")。修: `setWordWrap(True)` + `horizontalPolicy=QSizePolicy.Ignored`。
  **拔外接显示器/换分辨率后窗口会留在屏外** → `showEvent` + `_tick` 每 5s 复查 `availableGeometry()`,
  越界才 `setGeometry` 拉回 (不动用户手动缩放)。判据: 真桌面跑一遍断言
  `窗口完整在屏内 (x/y/w/h 都在 availableGeometry 内)`。⚠️ 我这台本机屏幕在会话中从 **3200x2000@192DPI
  变成 1920x1200@96DPI** (拔了外接屏) → 同一脚本两次运行结果不同, 别把环境变化误判成代码 bug。
- **快捷键**: Enter=保存 · N=保存并下一帧 · F=冻结 (画面控件内 Del=删选中 · Ctrl+Z=撤销 · 1-9=选类别);
  **必须加输入框守卫** (焦点在 QLineEdit/可编辑 combo 时不抢键), 否则标定员名字打不出来。

**取证 (全绿, 脚本在 ~/zmax_data/)**: `verify_yolo_annot.py` (坐标映射 0/90/180/270 + 窗口集成落盘 + 标签数值手算比对 +
体检反向验证 + 快捷键) · `verify_annot_ui_real.py` (真桌面 192DPI: 按钮不截断/两窗并排/截图) ·
`annot_smoke_real.py` (真机 D405 帧 → 标定 → 构建, 8 张) + `yolo_annot_train.py --epochs 2 --device 0`
→ **真 GPU 训练跑通**: box_loss 3.75→3.03, best.pt 落 `runs/detect/outputs/yolo_annot_smoke/.../weights/best.pt`。
⚠️ 精度仍未验证: 首次标定需人工 (建议首轮 ≥100-300 张, 覆盖不同位置/光照), 我做的烟雾框是**程序化占位框**只证管线。


- YOLO 检测 → 3D 坐标 → state 对齐
- 仿真数据要模拟真机感知（不白给坐标）

## 关键坑 (实测 2026-08-07)

### ① ultralytics BGR 数组坑（最重要）
- `model.predict(rgb_array)` 对 **RGB numpy 数组检测返回 0 框**！
- 必须 `cv2.cvtColor(img, cv2.COLOR_RGB2BGR)` 转 BGR 再 predict
- 文件路径 predict 正常（内部处理）；数组必须 BGR
- 速度：内存 BGR 方式 ~10ms/帧，临时文件方式 ~1s/帧（慢 100 倍）

### ② 相机 2D→3D 反投影
```python
from scipy.spatial.transform import Rotation
q = env.model.cam_quat[cam_id]
R = Rotation.from_quat(q).as_matrix()
fwd, right, up = -R[:,2], R[:,0], R[:,1]
f = (H/2) / np.tan(np.radians(fovy)/2)
ndc_x, ndc_y = (u-W/2)/f, (v-H/2)/f   # 注意 y 方向
dir_ = fwd + ndc_x*right + ndc_y*up
# 高度: 用真实高度 (仿真) 或深度相机 (真机); 假设误差大
t = (plane_z - cam_pos[2]) / dir_[2]
pt = cam_pos + t*dir_
# 标定偏移: X 常量修正 (实测 peg ~0.04, 需重新标定)
```
- peg 在画面中心 → 3D 精度 ±4cm（够抓取）
- hole 在边缘 → 投影误差大，用插入点推断
- 39D state 段位: hand=[0:3], peg=[18:21], hole=[36:39]

### ③ 训练/评估必须同构
- 训练用 YOLO 检测 state（带噪声）→ 评估也必须用 YOLO 检测 state
- 否则分布不匹配 → 假 0% 抓取（eval 喂真实坐标）
- eval_insert.py: `run_episode(policy, seed, yolo_aligner=...)`

### ④ 数据生成 --yolo 模式
- `tools/gen_metaworld_data.py --eps N --yolo`
- YOLO 检测必须用 480 原图（128 resize 检测不准）
- 丢弃轨迹后 episode_index 必须重编号 0..N-1 + 重建 episodes

## 命令
```bash
# 训练 YOLO (数据: tools/gen_yolo_data.py 自动标注)
.venv/bin/python tools/train_yolo.py --data data/yolo_peg_full --epochs 50 --name peg_full

# 评估 (YOLO 感知模式)
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/eval_insert.py
```

## 验证
- `tools/yolo_state_aligner.py` 单跑: YOLO 检测 3D vs 真实坐标对比
- 检测数应 ≥3 (hand/peg/hole), peg 误差 <0.05m

## CPU 训练打通 (2026-08-23 无 GPU 环境实测, 本地 4060 有卡但驱动没装+SecureBoot)

### torch CPU wheel (uv 不认 aliyun Apache 目录)
- aliyun pytorch-wheels/cpu/ 是 Apache 目录列表(非 PEP503), uv `--index-url` 找不到包 → 只能 curl 直下 wheel 再 `--no-deps` 本地装:
  `curl -sL -o torch-2.7.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl "https://mirrors.aliyun.com/pytorch-wheels/cpu/torch-2.7.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl"`
- uv 从 pypi 装 torch 默认拉 CUDA 版(502MB+一堆 nvidia-* 共 1.5GB 无用) → 必须本地 CPU wheel。
- wheel 重命名会丢 ABI 标签 → uv 报 "invalid wheel filename"; 保留完整 `+cpu-cp312-...` 文件名。
- torchvision 0.22.1 对应 torch 2.7.1 (也下 cpu wheel)。
- yolov8n.pt 预训练权重 GitHub release 被墙 → ghfast.top 代理: `curl -sL -o yolov8n.pt "https://ghfast.top/https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt"` (6.5MB)。

### 训练 (CPU)
```
yolo-venv/bin/python train_yolo.py --data data/yolo_peg --epochs 25 --device cpu --model yolov8n.pt --name peg_v1
```
- 1800 图(12 eps × 150 步) 3 类, CPU 每 epoch ~75s, 25 epochs ~30min, mAP50 0.995。
- ⚠️ data.yaml train=val=images 同数据 → mAP 虚高(自训练集), 真评估须另分 val。

### 输出路径坑 (ultralytics settings)
- settings.json 的 `runs_dir` 会改输出: project="outputs/yolo_peg" 实际落到 `runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt`。加载权重要搜候选路径, 别硬编码。

### 投影标注 (gen_yolo_data 已改)
- mujoco cam_mat0 是列主序 → `.reshape(3,3).T`; 相机看向 -z, 深度 d=-pc[2]。
- 帧保存与标注都要 np.rot90(k=2) 一致(渲染方向修正), 投影后坐标 (W-px, H-py)。

### 真检测验证 (训练后)
- peg conf~0.95 / hole~0.88 / hand~0.83, 框中心 vs 真值投影误差 ~2-7px → 框+conf 都是模型真输出。

## 同构接入 (2026-08-23 补缺口: YOLO检测→解算→训练state)

### detect_3d 反投影 (yolo_state_aligner.py 原实现有致命 bug)
- 原 detect_3d 用 cam_quat(Rotation.from_quat)+经验反号(X/Y取反+X-0.04)反投影, **从未验证过**(best.pt 一直不存在→--yolo 没跑过), 实测 3D x 差 3 米。
- 正确: cam_mat0 是**列主序** `.reshape(3,3).T`, 相机看向 -z:
  ```python
  cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3,3).T
  ndc_x = (u-W/2)/f; ndc_y = (v-H/2)/f   # f=(H/2)/tan(fovy/2)
  pc = np.array([ndc_x, -ndc_y, -1.0])   # 相机系方向(看向-z)
  dir_w = cam_mat.T @ pc; dir_w /= norm
  t = (plane_z - cam_pos[2]) / dir_w[2]  # 平面假设求交
  pt = cam_pos + t*dir_w
  ```
  修后 hole 误差 6.4cm / hand 4cm (peg 20cm 是 plane_z=0.03 假设的固有缺陷, peg 抓取前高度会变)。

### 帧方向同构 (rot90 坑)
- gen_yolo_data 训练存 `np.rot90(img, k=2)` 帧; detect_3d 推理必须同样 rot90 再预测, **box 中心反投影前转回原始坐标 `(u,v)=(W-u,H-v)`**。不同向 → 倒置图只检出 peg 且位置错。

### gen_metaworld_data.py --yolo 两个坑
- `from lerobot.policies.yolo_3d.yolo_state_aligner import ...` 会触发 lerobot 包 __init__ (huggingface_hub 等重量级依赖) → 改 `sys.path.insert(0, .../yolo_3d)` + `import yolo_state_aligner` 直载文件。
- 成功过滤 `peg_z1-peg_z0>0.05`, --steps 太短(<50) peg 没抓起 → 整条轨迹丢弃 → all_frames 空 → pandas `KeyError: 'observation.state'` 假象 (别误判成 pandas bug)。

### 同构验证判据
- --yolo 生成的 state 的 hand/peg/hole 段 z **恒等于 plane_z**(0.155/0.03/0.129), 真值 z 会随运动变 → 这是"带 YOLO 噪声 state"的铁证。
- 全量 30 eps → 21 成功(约 70%) → 3780 帧, 存 data/metaworld_peg (data/ 在 .gitignore)。

## 评估侧接 YOLO (2026-08-23 闭环: eval_insert.py)

### ⚠️ metaworld 默认相机是 topview 不是 corner2
- `env.render()` camera_name=None 时默认渲染 **topview**; YOLO 反投影假设 corner2 视角 (训练数据 gen_yolo_data 也是 corner2)。
- 评估 env 若不显式 `camera_name="corner2"` → 检测框与反投影相机参数不匹配 → 3D 坐标错位。
- 修法: eval_insert.run_episode 里 env 构造加 `camera_name="corner2"` (视觉输入与训练也同视角, 更正确)。

### eval_insert.py 接法
- `run_episode` 本就有 `yolo_aligner=None` 参数 (第 182-188 行 detect_3d→align 替换 39D), 但 main() 一直没传 → 默认真值。
- 新增 `_build_yolo_aligner()`: 直载 yolo_state_aligner 文件 + 搜候选权重路径 + 用 seed=0 的 corner2 env 取 cam_id; 失败返回 None 自动回退真值 (打印提示)。
- main() 里 `aligner=_build_yolo_aligner()` 一次加载, `run_episode(..., yolo_aligner=aligner)` 传所有 seed (aligner 的 self.env 只读静态相机参数 cam_pos/cam_mat0/cam_fovy, 各 seed 一致)。

### 评估 smoke test 判据
- corner2 env + aligner.detect_3d(env.render()) 应检出 3 类 {hand,peg,hole}, hand 误差~4cm / hole~6.4cm / peg~20cm(plane_z=0.03 固有, 训练同源)。
- 同构闭环: 训练(--yolo) 与 评估(yolo_aligner) 用同一 detect_3d + 同一 plane_z 假设 → state 分布一致 → 不再假 0%。

## 评估流程真实跑通 (2026-08-23 闭环落地: BC policy + YOLO 感知)

### 环境关键 (LiveUSB 4060 控制节点)
- 完整评估环境是 **gui-venv311** (Py3.11): metaworld 3.1.1 + mujoco 3.3.0 + ultralytics + torch 2.7.1+cpu + cv2 + scipy 全有。
- **不是 yolo-venv** (只有 ultralytics+torch, 无 metaworld/mujoco)。误判坑: metaworld 无 `__version__` 属性 → `print(metaworld.__version__)` 报 AttributeError 被 `| head` 截断, 误以为 import 失败, 实际已装。
- 各依赖版本核验命令: `for m in ...: importlib.import_module(m)` 判存在, 别用 `__version__`。

### 5 模型权重不在本机 (关键认知)
- eval_insert.py 的 act/smolvla/smolvla_lew/vla_touch/awe_zflow 权重在远程 GPU `223.109.239.36:24424`, LiveUSB 重启后 ~/.zmax_ssh.json 丢失, 密码已失效 → 本机拿不到。
- ECS `39.102.211.79` (密码 Nix19789, 端口22) 可达但上面只有 smolvla_lew_10step, 无 5 模型完整权重。
- 本机同构闭环改走 BC: `tools/eval_yolo_bc.py` 用 data/metaworld_peg (YOLO噪声state) 训练 BC MLP (39D→4D, 512 hidden), 再用真实 best.pt 感知评估插拔。

### eval_yolo_bc.py 用法 + 实测结果
- `DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/eval_yolo_bc.py --epochs 400 --seeds 10` (加 --skip-train 复用 outputs/bc_yolo/model.pt)。
- 训练 3780帧/21ep, 400 epoch loss 1.00→0.046 (CPU 快); 评估 10 seed: 抓取40%/插入40%, 每帧检出 2.97 类 (YOLO 真推理铁证)。
- 失败 6 seed 全是 peg 没抬起 (peg_rise -0.005m) → BC 数据少(21轨迹)泛化有限, 是真实表现不是 bug。
- 同构铁律: 训练(gen --yolo) 与 评估(detect_3d+align) 必须用同一 YoloStateAligner 类 + 同一 plane_z + 同一 rot90 + 同一 480原图, 才保证 state 分布一致。

## 操作视频接 YOLO 感知 (2026-08-23)

### 老倪戳穿的假同构
- 交付的"操作视频"(reports/*MLP*.mp4, gen_insert_video.py 生成) 之前是 mujoco 真值 state: get_obs=env._get_obs() 纯真值 + 状态机判断用 env.data.site_xpos 真值坐标 → 模型吃真值, 非 YOLO 感知 → sim2real 不同构。

### gen_insert_video.py 接法 (双脑视频脚本)
- 喂 left/right 的 state 改 detect_3d+align (变量 o_model), 状态机判断保持真值 (训练时专家动作也是真值状态机生成, 同构)。
- 关键: 循环前 o_model 初始化要 render+detect_3d 一次; 每步 step 后 render→detect_3d→align 更新 o_model 供下一轮。
- ⚠️ 本机无双脑权重 (outputs/train/left_right_* 不存在, LiveUSB 重启丢, 远程 GPU 密码失效) → gen_insert_video 改完本机跑不了, 需远程权重。

### gen_yolo_op_video.py (本机可跑替代)
- BC 模型(outputs/bc_yolo/model.pt, YOLO噪声state训练) + 真实 best.pt 检测, 画面叠加 hand/peg/hole 框, state 用 detect_3d 解算喂 BC → 真机同构操作视频 reports/yolo_perception_op.mp4 (seed0 成功, 距孔0.011m, 每帧检出3.0类, 480x480 20fps)。

### 两个坑
- torch 2.6+ torch.load 默认 weights_only=True, checkpoint 存 numpy stats → UnpicklingError (Unsupported global numpy._core.multiarray._reconstruct), 须 weights_only=False。
- 视频颜色: ultralytics res.plot() 返回 BGR (在传入的 BGR 图上画框)。两个脚本约定不同: gen_yolo_op_video.py 的 frames 存 BGR 直接 imwrite; gen_insert_video.py 的 frames 存 RGB (写盘 cvtColor RGB2BGR), 叠框须 res.plot() 再 cvtColor BGR2RGB 转回 RGB 保持一致 (否则红蓝互换)。
- 老倪判据: 操作视频画面必须叠 YOLO 检测框 (否则与真值视频画面一样, 看不出感知差别 → "视频还是老的")。

## left_right 双脑+状态机接 YOLO 训练 (2026-08-23 参考工程策略)

### train_full_pipeline.py 接法
- 参考工程策略 (左脑MLP接近 + 右脑WM contact + 对位头 + 8状态机硬编码编排): collect_data/评估的 state 用 `_yolo_state`(detect_3d+align) 替换真值, 左脑/右脑吃 YOLO 解算 state, 状态机判断保持真值(专家层, 训练时专家动作也真值生成)。
- 加 --eps/--epochs/--no-yolo 参数。
- 训练: `DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/train_full_pipeline.py --eps 30 --epochs 800`
- 结果: 4046帧 contact正例2910, 右脑contact_acc=1.00, 评估**抓起8/8 插入6/8** (YOLO噪声state, 比真值7/8略低但真实同构), 存 outputs/rl_peg/full_pipeline.pt。

### gen_insert_video.py 三个坑 (本机跑通踩的)
- full_pipeline.pt 的 right 带 align_head (train_full_pipeline 版 RightBrainWM), 加载用 modeling_left_right 版(无align_head) → `right_sd={k:v for k,v in d["right"].items() if not k.startswith("align_head")}` + strict=False。
- `from lerobot.policies.left_right.modeling_left_right import RightBrainWM` 触发 lerobot 包 __init__(huggingface_hub) → 直载文件; 且 importlib.util 直载带 @dataclass 的模块报 AttributeError NoneType __dict__ → exec_module 前须 `sys.modules["modeling_left_right"]=mod`。
- safetensors 只在 left_right checkpoint 分支用, fallback full_pipeline.pt 不需要 → 延迟到 for 内 try import (gui-venv311 无 safetensors/huggingface_hub)。

## 视频朝向坑 (2026-08-23 视频需上下+左右翻转才能摆正)

### 根因 (实测锁定, 非猜) — 两层, 两层都要修
- **第①层(生成端)**: `env.render()` 原始输出**已是 top-down 正确方向**(mujoco renderer.py 第245行 `out[:]=np.flipud(out)` 实证, 见下)。但 gen_insert_video.py 历史遗留一段 ffmpeg `-vf transpose=2,transpose=2`(180°旋转), 把正确画面转成倒置。修复: 删掉那段 transpose, raw.mp4 直接作最终视频。
- **第②层(播放端)**: GUI 播放器 `MLPRolloutDialog.__init__` 默认 `self._rot=180`(simulink_module.py, 08-19 针对旧 Pillow 手绘 state_space 视频"画面反"的历史遗留), 把正确视频再转 180° → 倒置。修复: `self._rot=0`。
- 两层都修完才算正: 生成端 top-down + 播放端不旋转 = 正。旧链路是"生成端反(transpose) + 播放端转180 = 正"刚好抵消, 只修一层反而打破抵消变反。

### 决定性验证方法 (tools/diag_orient.py + verify_orient.py + verify_all_orient.py 已落地)
- mujoco renderer.py 第245行 `out[:]=np.flipud(out)` = render 后垂直翻转, 输出 top-down。用此实证 env.render() 方向, 别靠猜。
- 真值 hand 3D 标准投影 (px,py)=(237.6,219.2); 机械臂 sawyer 暗红色像素在 img 的 (px,H-py) 位置 → 标准投影公式是 bottom-up 坐标, img 是 top-down (翻转后)。
- 视频方向判据(最可靠): YOLO 只认 bottom-up(训练数据=img rot90(k=2))。视频帧**直接喂检出0类 + rot180喂检出hand** = 视频是 top-down(正); 反之 bottom-up(反)。verify_all_orient.py 验证 4 个视频(insert_success_demo/mlp_insert_success/mlp_best/yolo_perception_op)全 top-down。

### 关键认知 (勿再踩)
- YOLO 训练数据 gen_yolo_data 存 `np.rot90(img,k=2)`, 所以 YOLO **只认 img_rot180 方向**, detect_3d 内部 rot90(k=2) 只是为了匹配训练分布, **不代表 img 原始方向是倒的**。
- img 原始方向 = mujoco cam_mat0 标准投影方向 = 人眼正确方向(top-down)。帧存 img 原始、写盘只 cvtColor RGB→BGR 转颜色不转方向、ffmpeg 不旋转。
- 叠框: detect 在 img_rot180 上画框 → `np.rot90(vis,k=2)` 连框带画面一起转回 img 原始方向 → 框与物体保持对齐(两次 rot180=恒等)。

## YOLO depth head 深度感知 (2026-08-23 真闭环关键升级)

### 动机: 写死 z 是假闭环
- 原 `z_map={"hand":0.155,"peg":0.03,"hole":0.129}` 写死 z → hand-peg z 差恒 0.125 > 抓取阈 0.06 → 状态机永远进不了"抓取", 真闭环 0/12 卡"接近"。
- 方案2(检测框高反推深度) 信噪比太低: peg 抬升 0.15m 框高只变 ~2px, 被检测噪声淹没(深度误差 7-18cm) → 弃用。
- 终选: YOLO 加 depth head。ultralytics 8.4 内置 `DepthModel`(YOLO backbone + DPT depth head + SILog loss), **无需改 head.py/loss.py/data 源码**。

### 深度训练数据 (gen_depth_data.py)
- metaworld `rgbd_tuple` 返回 `(rgb, depth)`; depth 是 mujoco 深度 buffer 原始值(0.98~0.9999), 不是米制。
- 深度 buffer→米制拟合: `depth = A - B/z`, 实测 **A=1.0002 / B=0.0230**(跨 seed 稳定, 反推误差 mean≈3cm); 反推 `z = B/(A-depth)`。
- 存 16-bit PNG: `DEPTH_A=1.0002, DEPTH_B=0.0230, DEPTH_MAX=3.0, DEPTH_SCALE=256`。
- 3600 张 RGB+depth 对齐(12 eps), `data/yolo_peg_depth/`(data/ 在 .gitignore)。

### 深度训练 (train_depth.py)
- `gui-venv311/bin/python src/lerobot/policies/yolo_3d/train_depth.py --epochs 50 --batch 8 --name peg_depth_v1`
- 加载 `YOLO("yolo26n-depth.pt")`, loss 为 log-depth/SILog。
- CPU 1.1 it/s; epoch 16/50 时 abs_rel 1.6% / rmse 8cm / delta1 99.35% (best.pt 41MB, `outputs/yolo_peg_depth/peg_depth_v1/weights/`)。

### detect_3d 深度反投影 (yolo_state_aligner.py)
- 新增 `depth_weights` 参数 + `self.depth_model`; detect_3d 加载深度模型, 框内取**中位数深度**(抗噪)。
- 深度输出访问: `np.asarray(self.depth_model.predict(img_bgr, verbose=False)[0].depth.data).squeeze()` — 注意是 `.depth.data`, 不是 `.depth`。
- SILog 尺度不变 → 模型输出尺度漂移 → per-class 校准环境变量: peg/hole `DEPTH_SCALE=1.685`, hand `DEPTH_SCALE_HAND=1.566`(hand 细长臂末端, 尺度因子不同)。
- 校准后精度: hand 0.4-2.6cm / peg 0.2-1cm / hole 0.3-9cm。

### ⚠️ 深度闭环根因 (最重要教训, 勿重踩)
- 旧 full_pipeline.pt 是"写死 z 时代"训练: 归一化 `xs` 有 **24 个维度 = 1e-6**(写死 z 时 std=0, 训练保存加 1e-6), 对应 hand z / peg z / hole z 及常量维度。
- 深度反投影让这些维度出现真实变化 → `obs_n=(obs-xm)/xs` 除以 ~1e-6 → 输入爆炸 → 左脑输出 act_z 282~1066 → hand 乱飞。
- **结论: 深度反投影后必须用深度 o_model 重新收集数据 + 重训左脑/右脑**, 不能复用写死 z 时代权重。
- 诊断手段: 每步打印 hand_z/peg_z/d_hp/contact/act_z, 一眼看出 act_z 爆炸。

### train_full_pipeline.py 真闭环改造
- `_build_aligner` 加 `depth_weights`(DEPTH_CKPT 环境变量 或 `_DEPTH_WEIGHTS_CANDS` 候选)。
- 评估状态机判断 hand/peg/hole/peg_z0 全改 o_model 段(深度反投影), 不再用 `env.data.site_xpos` 真值。

## GPU 深度闭环 (2026-08-24, 4060 GPU 训练后新坑)

### ① cuda tensor bug (最重要, 勿重踩)
- GPU 训练后 depth 模型 `.depth.data` 返回 **cuda tensor**, `np.asarray(cuda_tensor)` 抛 TypeError 被 detect_3d 里 `except Exception` 吞掉 → depth_map=None → 回退写死 z_map → 评估 0/8 卡"接近"。
- 修: `np.asarray(_d.detach().cpu().numpy())` (yolo_state_aligner.py detect_3d)。

### ② depth scale 重新标定
- GPU 训练 + ultralytics 自动校准(log-affine: `d'=exp(a·log d+b)`, b=0.604 → ×1.829, 推理自动应用)后, 深度输出尺度变了。
- 旧 DEPTH_SCALE=1.685/hand=1.566 **作废**, 新标定: `DEPTH_SCALE=0.978`(peg/hole), `DEPTH_SCALE_HAND=0.885`(hand)。
- 标定脚本 tools/diag_depth_calib.py (真实沿光轴深度/depth_m, 多 seed 均值, std 极小说明稳定)。

### ③ 专家动作 clip bug
- metaworld scripted policy 输出超 [-1,1] 的动作(靠 env 内部 clip), collect_data 存的是未 clip 动作 → ys=[3.55,0.76,2.43,0.69] 超动作空间 → 左脑学超范围动作, 评估又 np.clip → 分布不匹配。
- 修: collect_data 里 `a = np.clip(a, -1, 1)`。

### ④ 已解决 (2026-08-24 晚打通, 视频生成 0/8→成功)
两层根因, 都不是模型问题, 是接近/抓取阶段的检测失真:

**(a) 接近逻辑 z 分量不足 → 拆"水平对位→垂直下降"**
- 左脑 MLP 初始输出 act_z=+0.882(朝上偏置, 专家初始动作朝上), 接近逻辑 `act*0.3+delta*2.0` 的 delta z 修正仅 -0.299 被 +0.26 抵消 → 净下降 -0.034 → hand 卡 z=0.14。
- 修: 状态机启用 ST_ALIGN/ST_DESCEND(头部定义但评估循环一直没用=死代码):
  APPROACH(水平接近,z保持0,`act[:2]=clip(delta_xy*2.0)`) → ALIGN(精确对位,d_xy<0.06进/d_xy<0.03转,`act[:2]=clip(delta_xy*3.0)`) → DESCEND(垂直下降,x/y锁0,z硬编码-0.8) → GRASP。z 方向全硬编码绕开左脑朝上偏置。

**(b) hand/peg 靠近时 YOLO 检测失真 → 抓取用 contact 判断**
- DESCEND 阶段物理真值 d_hp=0.054(<0.06 已到抓取距离), 但 YOLO 检测 d_hp=0.157(检测 d_xy 从 0.034 漂到 0.118, 真值 d_xy 稳 0.05) → hand/peg 物理靠近时检测/深度反投影严重失真。
- 修: DESCEND→GRASP 条件 `d_hp<0.06 and contact>0.5` → `contact>0.5`(右脑 contact acc 1.00, 物理接触时稳 0.999 可靠; 检测 d_hp 不可靠)。
- 诊断手段: 同时打印真值(o[0:3]/o[4:7])和检测(o_model[0:3]/[4:7])的 d_hp/d_xy, 一眼看出检测失真。

**(c) DEPTH_SCALE 固化进代码**
- 之前 scale 只在环境变量(GUI 点生成视频不带 → 默认 1.0 白修)。已固化 yolo_state_aligner.py 默认 `_depth_scale=0.978, _hand_scale=0.885`。
- gen_insert_video.py `_DEPTH_WEIGHTS_CANDS` 漏 `peg_depth_v1-2`(GPU 自动校准版), 一直加载旧 `peg_depth_v1`(41.9MB CPU 版, scale 1.685 作废) → v1-2 排第一。

**(d) CUDA unknown error (nvidia_uvm)**
- LiveUSB 重启后 nvidia_uvm 模块不加载 + /dev/nvidia-uvm 节点缺失 → torch CUDA unknown error(cuda available=False) → 推理退化。补 systemd 服务 nvidia-uvm-nodes.service(modprobe nvidia_uvm + mknod uvm/caps, 主设备号从 /proc/devices 动态读)。

**结果**: 修后 gen_insert_video.py seed0 一次成功(完成状态=完成,184步, 视频 3.1s/93帧), 对比之前失败 1.63s/49帧。
