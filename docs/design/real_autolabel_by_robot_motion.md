# 用机器人实际动作自动标注光模块（kinematic auto-labeling）

> 2026-09-17 · 老倪：「设计一下，如何通过机器人的实际动作，抓取光模块，自动标注。」
> 实现：`tools/real_autolabel.py`（数学核已自检通过）· 真值源 `tools/real_truth.py`

## 0. 一句话

**机器人自己就是标定物和真值源** —— 它夹着光模块动一动，就能同时解决"手眼标定"和"批量自动标注"两件事，
全程不需要人拖框、不需要棋盘格。

## 1. 为什么可行（不是拍脑袋）

现场已经具备三个事实：

| 事实 | 出处 / 实测 |
|---|---|
| 末端位姿是**真值**，≈50Hz | `/robot/tcp_pose`（base_link），实测 49.6Hz，落盘 `~/zmax_ss_remote/state_*.jsonl` |
| 相机画面已在**本机可取** | UVC `/dev/video2` 640×480@10fps → `live_frame.jpg`，实测 age<1s |
| 模块**随夹爪运动** | 抓取成立时"模块中心 = TCP + R·offset"，几何上是刚体约束 |

于是：**每一个"机器人带着模块走到的位姿"都是一个已知 3D 点的采样**，缺的只是"3D→像素"的映射；
而这个映射可以用同一批采样**反解出来**（手眼标定），反过来再用它批量投影生成 2D 框（自动标注）。

## 2. 三步走

### S0 探针运动（probe）—— 采标定数据
- 现场让机器人夹着光模块在相机视野内走 **9~12 个位姿**：画面四角 + 中心 + 2~3 个不同深度。
- 每个位姿自动记录：`TCP(x,y,z)+四元数`（真值，已有）+ 一帧图像 + 关节/力/夹爪状态。
- **模块的像素位置不用人框**：画面里只有夹爪+模块在动，相邻帧差分取最大运动连通域中心即可
  （`real_autolabel.motion_center`）——静止的孔口/工装天然被差分排除，不会混进来。
- ⚠️ **配对规则**：差分出来的运动域是"两帧之间"的位置，所以它的 3D 必须取**两帧 TCP 的中点**
  （不能直接用后一帧，否则引入半个采样周期的滞后偏置）。探针要**边走边采**（连续采样），
  不要只采静止点位 —— 静止时没有运动域，差分拿不到模块像素。

### S1 自标定（kinematic eye-hand calibration）
- 用 N 对 `(3D 真值 → 像素点)` 解 **3×4 投影矩阵 P**（DLT + Hartley 归一化，最少 6 对）。
- `P = K·[R|t]`，**已经含内参与手眼外参的乘积** —— 做 2D 标注完全够用；需要 3D 反投影时才拆 K。
- 产出 `models/real_cam_proj.json`：`{P, n_pairs, rms_px, K_est(fx,fy,cx,cy), K_est_valid}`。
- **口径与仿真一致**：仿真侧 `gen_yolo_data.project_3d_to_2d` 用 MuJoCo `cam_mat0/cam_pos/cam_fovy` 做真值投影；
  真机这一步就是它的现场自标定版 —— 两边都是"真值 3D → 像素框"。

### S2 批量自动标注（label）
- 之后任何"抓取 → 搬运 → 插入"过程都自动产标注：
  1. 模块中心 = `TCP + R(quat)·offset`；2. 模块 8 角点（物理尺寸 + 姿态）→ 投影 → AABB → YOLO 框（class `peg`）；
  3. 现场示教过 `goal` 点 → 同样投出 `hole` 框（class `hole`）。
- **只在"抓取确认成立"的时段标注**：判据 = 闭合后**抬升随动**（抬 h、模块随动 >h/2 才算夹住），
  与 `L4` 抬升试探同一口径 —— 绝不给"没夹住"的帧发标签。
- 落盘复用 `yolo_annot_dataset.save_sample` → `sessions/auto_<ts>/`，`annotator="auto:kinematic"`，
  与人工样本同结构 → 自动进 `dataset/truth.jsonl` 与训练集。

## 3. 与"复用仿真 YOLO 模型"的关系

仿真权重在真机 **0 检出**（实测：`peg_v1` 对真机帧 conf≥0.25 零检出），所以只有两条路：
1. **域适应微调**：真机标注 → `tools/yolo_annot_train.py --base auto`（已跑通，GPU 实测）；
2. **同口径自动标注**：S1 标定后，真机也能像仿真一样"真值投影出框"，数据量与口径直接对齐。

自动标注解决的是**数据量**（人拖框 100 张≈半小时，机器人走两趟就能出几千张），
但**不解决**"模型是否变好" —— 那由人工留出集上的指标裁决。

## 4. 诚实边界（不达标不进默认档）

| 项 | 现状 | 处理 |
|---|---|---|
| 模块物理尺寸 | 未实测 | `--size 40,16,12`（mm）必须显式给；输出 meta 标 `pending`，**不猜** |
| `offset`（模块中心相对 TCP） | 未标定 | 先按 0 解 P；`rms_px` 偏大 → 把 offset 纳入最小二乘（探针里姿态在变，二者可辨识）；不收敛就如实报 |
| 相机内参 K | `real_cam_calib.json` = `ready:false` | 由 P 的 RQ 分解**顺带得到** K_est（自检已精确还原 fx/fy/cx/cy） |
| 孔口 hole | 未示教几何 | 先只标 `peg`；示教后自动加 `hole` |
| **自动标注不能当 val** | — | 评估必须在**人工标注留出集**上做，否则自证循环 |

## 5. 验收标准

1. `real_autolabel.py --selftest` 全绿（数学核）：DLT 精确可逆、噪声不放大、姿态→框几何自洽。← **已过**
2. S1 标定 `rms_px` ≤ 2px（12 对点、覆盖画面）→ 判定标定有效，写入 `models/real_cam_proj.json`。
3. 几何自检：自动框 vs 图像中实际模块区域（运动域/深度）IoU 中位数 ≥ 0.5（抽样 30 帧）。
4. 训练验收：自动标注训练 → 在**人工留出集**上 mAP/召回**有提升**（不是"不回退"），才进默认档。

## 6. 命令

```bash
# 数学核自检 (无需现场)
gui-venv311/bin/python tools/real_autolabel.py --selftest

# S1: 由探针会话 (frames/ + truth.jsonl) 自动出点对并解投影矩阵
gui-venv311/bin/python tools/real_autolabel.py --probe data/yolo_annot/sessions/<探针会话>/frames \
    --truth data/yolo_annot/sessions/<探针会话>/truth.jsonl --out models/real_cam_proj.json

# S2: 用投影矩阵批量标注 (需给模块实测尺寸)
gui-venv311/bin/python tools/real_autolabel.py --label --proj models/real_cam_proj.json --size 40,16,12
```

## 7. 待办（按依赖顺序）

1. 现场确认模块物理尺寸（量一次，40×16×12mm 只是占位）。
2. 走一趟探针运动（9~12 位姿）→ S1 标定 → 看 `rms_px` 与 `K_est_valid`。
3. `ss_geom_calib --record peg_head/goal` 示教两点 → 才有"距孔口"与 `hole` 类。
4. S2 接产线/示教时段跑自动标注 → 人工抽检 → 训练 → **人工留出集**验收。
