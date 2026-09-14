---
name: yolo-3d-perception-chain
description: YOLO 2D→3D→state 感知链, 含 ultralytics BGR 坑与同构评估原则。
---

# YOLO 3D 感知链 (仿真=真机同构)

## 触发
- peg-insert 插拔模型训练/评估
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
