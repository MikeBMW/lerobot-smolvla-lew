# YOLO 感知训练 — 自动标注数据生成 + YOLOv8s 训练 (2026-08-07)

## 目标
真机感知前端: 相机图像 → YOLO 检测 hand/peg/hole → 2D→3D 解算 → 39D state → 策略。
仿真里 39D 由模拟器直给(等价完美检测); 真机必须 YOLO 产出。**零人工标注**: 仿真渲染图 + 模拟器已知 3D 位置投影到 2D 自动生成标注。

## 数据生成 (tools/gen_yolo_data.py)
```
metaworld 渲染 (480x480, camera_name="corner2") + env 已知物体 3D 位置
  → 针孔投影到 2D 像素 → YOLO 格式标注 (cls xc yc w h 归一化)
```
- 3 类: `0=hand`(endEffector site), `1=peg`(pegGrasp site), `2=hole`(hole site)
- bbox 固定尺寸 (hand/peg/hole 用同一 40x60 像素框, 中心=投影点) — 够训练用
- 运行: `DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/gen_yolo_data.py --eps 30 --out data/yolo_peg_full`
- 450 张图/3eps 用时 ~2min; 每张图 3 个标注 (450 张全有 3 类 = 投影正确)

## metaworld env 坑 (数据生成脚本实测, 2026-08-07)
| 坑 | 现象 | 修复 |
|---|---|---|
| 必须 set_task | `RuntimeError: You must call env.set_task before using env.step` | `env.set_task(mt.train_tasks[0])` |
| **train_tasks 是 list 不是 dict** | `TypeError: list indices must be integers, not str` | `mt.train_tasks[0]` (50 个 task), 不能用 `["peg-insert-side-v3"]` |
| seeded_rand_vec 是 bool | `TypeError: 'bool' object is not subscriptable` | 不要当位置向量用; 相机跟随场景自动动, 不手动改 cam_pos |
| 手动改相机位置 | 多此一举 | metaworld 相机自动跟随场景, 直接 `env_cls(render_mode="rgb_array", camera_name="corner2")` |

## YOLO 训练 (tools/train_yolo.py)
- 依赖: `.venv/bin/python -m pip install ultralytics` (venv 里没有 pip 二进制, 用 -m pip)
- 命令: `DISPLAY=:0 .venv/bin/python tools/train_yolo.py --data data/yolo_peg --epochs 50 --name peg_v1`
- **输出目录坑**: ultralytics 自动加 `runs/detect/` 前缀 — 实际在 `runs/detect/outputs/yolo_peg/peg_v1/`, 不是 `outputs/yolo_peg/peg_v1` (设 project="outputs/yolo_peg" 也会被包一层)
- **进度监控**: verbose=False 时终端无输出, 看 `runs/detect/outputs/yolo_peg/peg_v1/results.csv` 每 epoch 一行 (epoch, loss, mAP); `tail -1 | cut -d',' -f1,6` 看当前 epoch + mAP50
- 450 张图 50 epochs ≈ 10 分钟 (与画布 lerobot_train 共存 GPU 80% 无碍)

## 结果 (2026-08-07, 450张/3eps/50epochs)
| 指标 | 值 |
|---|---|
| mAP50 | **0.994** |
| mAP50-95 | 0.905 |
| Precision | 0.951 |
| Recall | 0.985 |
| 推理 | 42ms/帧 (480x480) |

验证: `YOLO('runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt')` predict 训练集外图 → 3 目标全检出 conf≈0.96。

## ⚠️ 泛化陷阱: 小训练集 mAP 虚高, 未见过 seed 检测 0 (2026-08-07 实测)
**现象**: 3 eps (450 张) 训出的模型 mAP50 0.994, 但:
- 训练分布内图 (ep002_s100.png): 检出 3 个, conf 0.96 ✅
- **未见过的 seed0 场景** `model.predict(env.render(), conf=0.2)`: **检测 0 个** ❌ (直接数组传也 0)
- 同样 seed0 画面存成 PNG 再 predict: 检出 3 个 ✅ (数组 vs 文件预处理差异, 见下)
**根因**: 3 eps 只覆盖 3 个随机初始化, 对第 4 个场景的 peg/hole 外观/位置分布外 → 检测不到。**mAP 高 ≠ 泛化好**。
**修复**: 扩到 **30 eps (4500 张)** 重训 (`--eps 30 --out data/yolo_peg_full`), 训到 epoch 5 mAP50 即 0.936, 目标覆盖全场景。检测视频/对齐器一律用全量模型。

## ⚠️ env.render() 数组 vs 文件路径 — ultralytics 预处理差异 (2026-08-07 实测)
**现象**: 同一帧 `model.predict(path)` 检出 3 目标, `model.predict(np_array)` 检出 0 — ndarray 与文件路径走了不同预处理分支。
**修复 (YoloStateAligner.detect_3d)**: 
```python
from PIL import Image as _PIL
img = np.asarray(_PIL.fromarray(img).convert("RGB"))  # 必须 PIL 转, 直传 env.render() 数组会漏检
res = self.model.predict(img, conf=conf, verbose=False)[0]
```
检测数在 0/1/3 间波动 = 先怀疑数组直传问题, 不是模型坏。

## YOLO 输出 → 39D 对齐 (2026-08-07 老倪: "Yolo的输出跟39D对齐")
**工具**: `tools/yolo_state_aligner.py` — YOLO 2D 框 → 相机反投影 → 3D → 填 39D 对应段 (真机同构, 不用模拟器直给)。
- 39D 结构: `[0:3]=hand, [18:21]=peg, [36:39]=hole`; 对齐 = 替换这三段
- 反投影: cam_quat→Rotation 矩阵 (fwd=-R[:,2], right=R[:,0], up=R[:,1]) + 像素偏移 ndc + 水平面求交 (hole z≈0.03 / hand/peg 近似 z≈0.25)
- **⚠️ mujoco 新版本无 cam_target 属性** — 用 cam_quat 算方向
- **⚠️ 高度近似误差大** (hand 反投影 [0.401,-0.462] vs 真实 [0.004,0.601]): 要精确需把真实 z 存进标注/元数据做先验 (仿真可读模拟器真实 z; 真机用深度/标定)

## Rollout 检测视频 (tools/yolo_rollout_video.py)
- 逐帧 `model.predict(env.render(), conf=0.4)` → `res.plot()` 叠加框 → cv2 VideoWriter (mp4v, 20fps)
- **⚠️⚠️ 2026-08-07 实测纠正**: **不要"先旋转帧再检测"** — `res.plot()` 无论喂什么方向都输出原始方向 (PIL 转换也没用, rot3 vs 原帧差异仅 4.0)。**正确流程**: YOLO 检测**原帧** (框坐标正确) → cv2 写出 → **cv2 VideoWriter 写出的视频自带正确180°方向** (绿色重心实测 (208,181)≈正确旋转帧), 无需再 ffmpeg 转; 再转反而错 (老倪抓: "hand 0.66这个检测框也反了" 就是转错方向)
- **方向验证用绿色 peg 重心量化**: `green_center(img)` = 像素 (G>120 & R<100 & B<100) 均值坐标; 原帧 (269,290) → 正确180 (209,188)。抽帧验证重心≈旋转帧即正确, 别靠肉眼
- 纯画面无框视频批量旋转 180°: `ffmpeg -i in.mp4 -vf "transpose=2,transpose=2"` (180° = 两次 transpose) — 但只适用 ffmpeg 从 PNG 拼的视频 (方向"反"), cv2 写出的已正确别转
- 改生成管线 (cv2 vs ffmpeg-PNG) 后必须重新验证方向, 管线隐式方向不同

## 下一步方向
- 数据扩 30 eps (4500 张) 重训 → 精度更高 + 泛化更好
- YOLO 检测 → 2D→3D 解算 (相机内参/深度) → 拼 39D state → 喂蒸馏 MLP (expert_mlp.pt) 完整真机链路
- best.pt (21.5MB) 推 ECS 静态 URL 供 MAC 部署
