---
name: metaworld-sim-eval
description: Metaworld 仿真 rollout 视频 + 多模型对比评估。生成 sim 视频时用。
---

# Metaworld 仿真 Rollout 与多模型对比评估

## 触发条件
需要生成 metaworld 仿真 rollout 视频、跑多模型对比评估（ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE-zFlow）、或任何在 WSL 里渲染 mujoco/metaworld 画面的任务。

## Metaworld 渲染黑屏 (最常见坑, 2026-08-05 实测)
**根因**: metaworld V3 环境默认 `render_mode=None` → `env.render()` 抛 AttributeError 或返回全零帧 (var=0.0, unique=1)。

**修复 (两条缺一不可)**:
```python
import os
os.environ.setdefault("DISPLAY", ":0")       # WSLg X0 socket
os.environ.setdefault("MUJOCO_GL", "glfw")   # 必须在 import mujoco/metaworld 之前设置!
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")
from metaworld.env_dict import ALL_V3_ENVIRONMENTS
env = ALL_V3_ENVIRONMENTS["push-v3"](render_mode="rgb_array")  # ← 关键: 必须显式 rgb_array
env.set_task(mt1.train_tasks[0])
env.reset(seed=seed)
rgb = env.render()  # 真渲染: (480,480,3) var≈4375 unique=256
```
- 渲染验证: `np.asarray(img).var() > 1000` 且 `len(np.unique(img)) > 50` 才是真图; var≈0 即黑屏
- **⚠️ obs 结构随环境/版本而异, 别写死 (2026-08-07 实测修正本节的旧结论)**: 旧结论"obs 是 numpy 数组不是 dict (V3 无 observation.image)" **在本项目 (peg-insert-side-v3, 本项目 metaworld 版本) 是错的** — 实测 `env.reset()` 返回 **dict** (`observation.state` 39D + `observation.image` 相机图)。**rollout 侧必须双兼容**:
```python
if isinstance(obs, dict):
    _st_raw = np.asarray(obs.get("observation.state", np.zeros(st_dim, dtype=np.float32)), dtype=np.float32)
    # 帧图可优先取 obs["observation.image"] (真渲染), 兜底 env.render()
else:
    _st_raw = np.asarray(obs, dtype=np.float32)
```
`np.asarray(dict)` 得到 0 维对象数组 → `ndim==1` 判断 False → **state 全零** → 模型推理异常 (act/vla/awe 全报 mat1/mat2 broadcast) → 动作均值 0.0。这是 2026-08-07 "所有模型动作≈0" 的元凶, 修一处全通
- 训练数据生成 (gen_metaworld_data.py) 与 rollout (rollout_video.py) 都需要这套 env vars
- 快速自检: `scripts/check_mujoco_render.py` (对比 rgb_array vs default 模式, 输出 var/unique 判定真图)

## 训练数据真相: nut-on-peg 套环 ≠ 插销 (2026-08-07 老倪"不是插销的数据"逐层挖)
- **data/metaworld_mt50**: 官方 MT50 基准下载 (info.json 声明 2500 eps/204806 帧/49 任务), **实际只下载了 chunk-000 的 2 个分片 = task 0 (nut-on-peg \"拿螺母放销钉\") 的 10 个成功演示, 879 帧** — info.json 声明 vs 实际天差地别, 判别看 parquet 实际行数
- **data/metaworld_act 696 帧 = 这 879 帧的 80%** (prepare_metaworld 转换) → **七模型训练用的全是\"套环\"数据, 不是插销** — 图像里是螺母套销钉 (老倪一眼看出)
- success 率 1.1% **不是失败轨迹**: metaworld 只在 episode 完成最后一帧标 success=1, 中间帧=0 — 10/10 全是成功演示 (别误读)
- **data/metaworld_peg (8-06 旧版) 只有 state+action 无 observation.image 列 → VLA 不能训**; 真插销数据必须自己生成 (见下节)

## Rollout 视频生成
- 帧存 `frame_%04d.png` + `actions.npy` + `info.json`
- 拼视频: `ffmpeg -y -framerate 15 -i cmp_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 26 out.mp4`
- 5 模型并排对比: 每帧 canvas = 5 列 (每模型 256x256) + 顶部模型名标签
- **⚠️ ffmpeg xstack 拼接 0 字节 (2026-08-25 实测, simulink_module._auto_finalize_work)**: 多模型对比视频 (Model Zoo_rollout_*.mp4 / 五模型对比_rollout_*.mp4) 全是 0 字节 = xstack layout 变量名写错 — `w_0_0`/`0_h_0`/`w_0+w_1_0` 应为 `w0_0`/`0_h0`/`w0+w1_0` (xstack 变量名是 w0/h0/w1 **无下划线**, 多写下划线 → ffmpeg `Failed to configure output pad` + `Nothing was written into output file` → 0 字节空文件)。自 08-06 引入, 所有对比视频一直空。正确: `xstack=inputs=3:layout=0_0|w0_0|w0+w1_0`。修复实测: 5 模型拼接 960x480@3s 113KB 正常 (旧 0 字节)。**验证: ffprobe 看 width/height/duration/size 非 0, 或 stat -c%s > 0**
- **7 模型对比 = 4×2 网格 + 每格底部距离趋势 (2026-08-09 老倪"应该是七个视频的对比"实测)**: 5 模型只是 Scope 图表范围——老倪要的对比视频是**全部 7 模型** (5 视觉 + MLP 蒸馏 + 官方专家)。`tools/gen_compare7_video.py` 模式: `COLS,ROWS=4,2`, 每格 `CW,CH=360,240` (画面 360×200 + 底部 40px 距离趋势带), 每格左上角叠 `模型名 (抓起 x/N)` 标签; 循环 `for i,(label,color,frames,dists) in enumerate(clips): r,c = i//COLS, i%COLS`。**坑: EVAL 结果字典必须用 label 做 key 且直接 `EVAL[label]` 查**——写 `EVAL[dict(MODELS)[label]]` 会在 `dict(MODELS)` 上抛 `ValueError: dictionary update sequence element #0 has length 3; 2 is required` (MODELS 是 (key,label,color) 三元组, dict() 只吃二元组)。**规则: 对比视频的标注数据字典按显示名 label 为 key, 别从模型元组反查**。官方专家 rollout 用 `SawyerPegInsertionSideV3Policy` + `env._get_obs()` 走 get_action (与评估同款), 100 帧能见 0.152→0.019m 插入成功——7 模型视频里专家是"能成"的对照锚点
- 10 步快速验证模型动作均值≈0 (未学会), 视频画面不动属正常 — 对比要"会动"需正式训练 (2000步; 2026-08-06 老倪: 链路验证默认 10 步, 跑通后再加)
- 单独视频: `ffmpeg -framerate 12 -i frame_%04d.png ... rollout_<policy>.mp4` (老倪要分开的, 不是只有并排)
- **单独视频必须加水印标记模型名** (老倪要求"分清哪个模型对应哪个视频"): `tools/watermark_video.py <in.mp4> <模型名>` 或 ffmpeg drawtext (fontsize 32, 左上角, box 黑底半透明)
- **换场景**: `rollout_video.py --policy X --task peg-insert-side-v3 --out reports/rollout_peg_X` (--task 参数支持任意 MT1 任务)
- **产物目录多候选约定 (2026-08-06)**: 同一 policy 可能有多个 rollout 目录并存 — `rollout_final_<p>` (正式/最新) > `rollout_peg_<p>` (peg 场景) > `rollout_<p>` (默认)。GUI 视频窗口和 have 检查按此优先级加载, 生成新场景时用 `rollout_final_<p>` 或明确的新前缀, 别覆盖旧目录; 所有读 rollout_* 的代码都要多候选 (只读默认目录会「数据丢失」观感)
- **⚠️ 画面「没动」≠ 模型没动 (2026-08-08 老倪「这视频也没动啊/我要看到趋势」)**: metaworld 速度控制衰减使手位移 ~0.06m 在 480px 画面只有几个像素 — 真实画面看不出接近趋势。**解决: 双面板视频 (左真实画面 + 右实时趋势曲线)**:
  - 右面板深色底 (480x300), 画坐标轴 + 距离曲线: x=时间步 (0..N), y=距离 (0..0.15m 固定轴), 每帧 append 当前 hand→peg 距离 (`np.linalg.norm(hand-peg)`), 逐点连线 (黄色), 绿色虚线画目标阈值 (如插入阈值 0.05m), 当前点画实心圆
  - 曲线用 `min(d, MAXD)` 截断防爆轴; 目标线标注文字让「趋势是否达标」一眼可见
  - 左面板: `cv2.putText` 叠 step 数 + 当前距离 + 夹爪状态 (CLOSED/open) — 信息带时间戳 (老倪偏好)
  - 拼合 `np.hstack([vis, panel])` 再写视频; **ffmpeg drawtext 中文冒号解析失败 → 用 ASCII 文本或英文标注** (`fontcolor=#58a6ff` + box 黑底)
  - 验证: 首尾帧像素差异可能 <5 (画面没动), 但曲线距离下降 (0.181→0.116) 证明方向性 — 趋势面板是「方向性学会了吗」的判定工具, 别靠肉眼
- **出「成功演示」视频先扫 seed (2026-08-08)**: 找能插拔的 seed 再录视频 — MLP 15 seeds 里 seed1/5/10/14 插入成功 (seed14 距孔 0.004m 最佳), seed0 硬跑 250 步无插入。扫 seed 脚本: 每 seed 跑 rollout 记录 lifted/min_dist_to_hole, 命中 <0.05m 的 seed 再出视频

## Rollout 推理动作全零 — 真正根因 (2026-08-06, 2000步训练后仍全 0 排查链)
**即使 2000 步正式训练, rollout 动作均值也可能 0.0** — 不是欠训练! 逐层排查:

| 症状 | 根因 | 修复 |
|---|---|---|
| 动作均值 0.0 + 视频静止 | **推理异常被 except 吞掉** | 排查时在 except 里 print 异常 (不要静默 pass!) |
| `can't convert cuda:0 tensor to numpy` | pred 是 CUDA tensor | `pred.detach().cpu()` 再 `np.asarray` |
| 缺 `observation.state` 输入 | 只喂了 image, ACT/SmolVLA 需要 state | `batch = {"observation.image":..., "observation.state": torch.from_numpy(st).unsqueeze(0).to(dev)}` |
| state 维度错 | ACT state=2D (pusht 模板), 别写死 4 | `policy.config.input_features["observation.state"].shape[0]` |
| `'InterpolantPolicy' object has no attribute 'config'` | vla_touch/awe 无 config | 从 model.pt cfg 推断: `pol.state_dim = int(cfg["state_dim"])` 挂属性 |
| `mat1 and mat2 shapes cannot be multiplied` | 精简模型 st_dim 推断错 | 默认 2 (pusht), 不是 4; vla_touch `_cond` 拼 state+tactile |

**精简模型推理适配 (无 select_action)**:
```python
if hasattr(policy, "select_action"):
    pred = policy.select_action(batch)
elif hasattr(policy, "_cond"):  # vla_touch: interpolant 采样
    tac = torch.zeros((1,3), device=dev)
    cond = policy._cond(batch["observation.state"], tac, None)
    # 🐛 2026-08-06 关键: x0 必须用上一帧动作 (act_hist), 不能 randn 噪声!
    #   训练时 q_sample(x0=轨迹前帧, x1=目标帧) — 推理从噪声出发走不到动作空间,
    #   动作幅度被压到 std≈0.10 (视频"几乎不动"); 用上帧动作作插值起点 → std 0.46
    if act_hist is not None:
        x0 = act_hist.to(dev).float()
    else:
        x0 = torch.zeros((1, act_dim), dtype=torch.float32, device=dev)
    pred = policy.sample(x0, cond, diffuse_steps=10)
else:  # awe_zflow: 直接 forward(state, tactile, act_hist, vision_feat)
    pred = policy(state, tac_zero, ah_zero, None)
```

**关键验证**: 动作均值 > 0.05 才算推理真正生效。修复后重跑看 `info.json` 的 action_mean。

**⚠️ rollout 验证必须用 60 帧 (2026-08-06 实测)**: 30 帧只覆盖轨迹前段 (接近阶段, 动作本来就小, std≈0.24), 60 帧才覆盖到抓取/抬起阶段 (std 0.46)。验证动作幅度时 `--steps 60` 与正式产物一致, 30 帧会误判"没修复"。

**✅ 数据修复后 5 模型动作幅度基准 (2026-08-06, 200-500步训练)**: ACT std 0.26/max 0.42 · SmolVLA 0.72/2.08 (最佳) · SmolVLA+LEW 0.65/1.72 · VLA-Touch 0.46/1.05 (x0修复后) · AWE 1.61/3.17 (未clip, 预测值超 [-1,1] 属正常, env.step 内部clip)。对比修复前 0.03-0.13 — 任何模型 std<0.15 仍属动作压扁, 查数据或推理路径。

## 归一化 var 误解 (2026-08-06 重大认知修正)
LeRobotDataset 解码返回 **0-1 归一化 float32**, `img.numpy().var()` ≈ **0.066 是正常图像** (不是黑屏!)。
还原原始方差: `var * 255 * 255 ≈ 4318` — 与 PyAV/ffmpeg 直解一致。
**判定黑屏的可靠标准** (不管归一化与否):
- 原始域: var > 1000 且 unique > 50 → 真图
- 归一化域: var > 0.02 且 mean 0.3~0.7 → 真图; var ≈ 0.0001 且 unique=1 → 黑屏
不要拿归一化 var 当原始 var 误判黑屏 (本次就误判过, 实际图像完全正常)。

## 插拔学不会的根因 = 输入信息缺失, 不是架构 (2026-08-06 老倪追问链: "为什么ACT训不出来/那其他模型能吗/为什么RL就能")
**老倪连问为什么 → 根因级答案 (实测数据支撑)**:
| | ACT/SmolVLA 系 (抓取率 0%) | 蒸馏 MLP (抓起 90%) |
|---|---|---|
| 输入 | 3D 末端位置 + 128 图像 (**不知道 peg 在哪**) | **39 维完整 obs** (`env._get_obs()`, 含 hand/peg/hole 精确坐标) |
| 动作 | 7 步 chunk 连续回归 → 学成平均 (夹爪恒 0.45) | 单步直接回归专家映射 |
- **图像是 2D 投影丢深度**: 128×128 里销钉只有几十像素, 亚像素级 3D 定位超出行为克隆能力 — "看得到"≠"知道精确位置"
- 夹爪闭合是**离散二值事件** (0.6闭/-1开), 连续回归学成均值 → 永不闭合
- **信息到位简单 MLP 也能学会; 信息缺失再强 Transformer 也白搭** — 选型报告核心论点
- **给 5 个模型也喂 39D**: 生成器 state 改 `np.asarray(env._get_obs(), dtype=np.float32).ravel()` (39D), info.json 的 `observation.state.shape` 必须同步 [3]→[39] 否则 `CastError: Couldn't cast` (table_cast 按 info features 强转 parquet 失败)
- **老倪架构洞察**: 真机没有上帝视角传感器, 39D 必须由 **YOLO 目标检测 (感知前端) + 2D→3D 解算 + State Adapter** 产出 — 完整模型 = 感知(YOLO) + 决策(策略) 两段式, 仿真里模拟器直给 39D 等价完美检测 (见 zmax-model-compare-report "YOLO 感知前端" 节)

## 插拔可实现的实证 + 两条训练路线 (2026-08-06 老倪: "必须能插拔, 完不成不要停")
**官方专家策略是可行性基准** (metaworld 内置 `SawyerPegInsertionSideV3Policy`):
- 实测 **19/20 抓起 17/20 插入 (85%)** — 插拔任务本身可实现
- 用法: `pol.get_action(env._get_obs().astype(np.float64))` → 4D 动作 (delta_pos 位置控制 + grab_effort 夹爪)
- **必须 `env._freeze_rand_vec = False` + `env.reset(seed=N)`** 多 seed 采样; 之前测 3/5 是没放开随机初始化

**路线A 专家蒸馏 (成功, 首选)**: `tools/distill_expert.py` — 官方专家跑 300 episodes 生成 (39D obs, 4D action) 数据 → BC 训练 MLP (512×3 层) → **抓起 18/20 (90%) 插入 11/20 (55%)**, 模型仅 2MB (`outputs/rl_peg/expert_mlp.pt`)。评估脚本 `tools/eval_distill.py` (20 seed 算抓起/插入率)。**这是第一个能独立插拔的神经网络**。
**⚠️ 插销数据 (peg_lerobot) 训练再证实 (2026-08-07 晚)**: ACT 用插销数据 4000 步 (loss 64→0.585 收敛) 后 `rollout_peg_check` 仍 **0/5 未抬起** (最近孔距 0.245m — 学到动作但没学会完整插入链); 同晚 distill_expert (300 eps 专家数据) → **2/5 插入成功 (40%), 5/5 全部抬起, 最小孔距 0.011m** (判定 <0.05 = 真插进)。**插销任务上 MLP 蒸馏 > ACT 长训** — 数据少 (24 eps) 时 ACT 的 chunk 回归学不成离散抓取, 专家 BC 单步回归直接成功。报告/选型引用"蒸馏路线"用这组新数据 (55% 是套环数据旧值, 插销数据实测 40%)。
**路线B 纯 RL (失败)**: `tools/train_peg_rl.py` PPO — 60 轮 0% (奖励 -9.9→-4.7 只学到接近)。教训: **纯 RL 探索不足+奖励稀疏学不会离散抓取; 成功的是 BC 蒸馏不是 RL** — 汇报时别把"蒸馏"说成"强化学习" (老倪误解过)。若真要 RL: 先 BC warm-start (专家数据初始化 actor) + 就位奖励塑形, 再 PPO 微调。
**⚠️⚠️ RL+grip_assist 组合也失败 (2026-08-08 老倪"上组合"实测)**: 夹爪改规则触发 (d_hp<0.08 闭合, RL 只学 3D 位置动作) 后 PPO 60 轮仍 **0/7 抓起, 奖励 -9.9 卡死** — 位置动作 RL 也学不成 (动作空间 3D 连续 + 奖励 -0.02d 塑形仍探索不动)。**结论: 插拔任务 RL 路线 (纯 PPO / warm-start / grip_assist 组合) 三连败, 唯一可行 = BC 蒸馏 MLP (39D 坐标直接映射) 或官方专家**。老倪问"为什么 RL 参数不多却能写出来" → 回答: RL 难点不在参数在**奖励稀疏** (99% 探索碰不到"刚好捏住"瞬间), BC 至少照专家视频学。

**插销专用数据集生成 (2026-08-07, 含图像, 官方专家采样)**: `tools/gen_peg_data.py --eps 30 --out data/metaworld_peg_v2` — `SawyerPegInsertionSideV3Policy` 在 peg-insert-side-v3 多 seed 采样, **只留插入成功轨迹** (`peg_z-peg_z0>0.05 且距 hole<0.05`), 存 npz (图像 128×128 corner2 视角 + state 39D `env._get_obs()` + action 4D)。实测 30 成功/41 尝试 (73%), 5850 帧。**→ 转 lerobot 格式**: `npz_to_lerobot.py --npz .../train.npz --out data/metaworld_peg_lerobot --task "Z-MAX 插销插拔" --fps 10 --episode-frames 200` → config `root: data/metaworld_peg_lerobot` 训练。**坑**: ① 失败轨迹 300 步跑完很慢 — `max_steps = 150 if ep_idx % 4 else 300` 提前终止 ② 系统 python3 无 pandas/pyarrow — GUI 读图用 numpy npz 路径 (见数据集管理节) ③ 训练后 rollout 动作均值 0.564 (插销模型) vs 旧数据 0.18 — 动作幅度是判断"学的是不是插销动作"的快速信号

**插拔成功率评估标准** (`tools/eval_insert.py`): 每 seed 跑 200 步, `peg_z - peg_z0 > 0.05` = 抓起, 抓起且距 hole < 0.05 = 插入。**评估管道 3 个致命 bug 已修**: ①模型加载绝对路径→相对路径 ②state 归一化 (用数据 stats) ③**动作反归一化后才能 env.step** (否则归一化空间动作≈0 实际没动, 距孔恒定 0.362 与随机一致)。

**rollout 画面"peg 没被拿起"的两种可能**: ①数据没学成 (夹爪不闭合) ②**纯看画面误判** — 用 `actions.npy` 的夹爪列验证: 闭合率<5% = 模型没学到闭合; peg z 位置变化需从 mujoco data 读 (rollout 只存帧)。

- **成功轨迹过滤 (gen_metaworld_data.py, 2026-08-06)**: 只保留「抓起 peg」的轨迹 (`peg_z1 - peg_z0 > 0.05`), 失败轨迹从 all_frames 剔除 + 不入 ep_imgs_all (视频合成自动跳过)。**⚠️ 致命坑: peg_z0 必须在轨迹开头 (env.reset() 后立即) 记录 — 若在轨迹结束处重复定义, 覆盖成最终值 → z1-z0 恒 0 → 20/20 轨迹全被误丢弃**。丢弃后 **episode_index 必须重编号** (0..N-1 连续) + 重建 episodes parquet (列格式: `videos/observation.image/file_index` 而非 frame_index, 含 data/chunk_index 等标准列), 否则 `IndexError: Invalid key: 12 is out of bounds` / `CastError`。**⚠️ 三处都要重建 (2026-08-07 v7 实测, 只改 parquet 不够)**: ①`data/chunk-000/file-000.parquet` 的 episode_index 列重映射 ②`meta/episodes/chunk-000/file-000.parquet` 重建 (length/dataset_from_index/dataset_to_index/videos frame 索引全按新编号) ③**`meta/info.json` 的 `episodes` 数组也必须是新编号列表** — fix 脚本只跑 parquet 时 info.episodes 为空/旧 → LeRobotDataset 加载帧数对但 episode 元数据错 (`IndexError: Invalid key: 1458 is out of bounds for size 1400` / `Invalid key: 7 is out of bounds for size 7` 是 episodes 计数 vs 实际 episode_index 不符)。生成器自身应直接写连续编号 (丢弃时从 all_frames 剔除后重新 enumerate), 别依赖事后 fix 脚本。
- **⚠️ config 里显式 `dataset.episodes: [0..11]` 列表 → KeyError 1800 (2026-08-08 SmolVLA 实测)**: YAML 显式列出 episodes 会让 dataset_reader 走 `_absolute_to_relative_idx[idx]` 相对索引映射, 数据 12 条但映射缺项 → `KeyError: 1800` 训练 0% 即崩。**修: 去掉 `dataset.episodes` 字段 (默认用全部)**, 或确保列表与 meta/episodes 完全一致。ACT 训练用同一数据 (无显式 episodes) 正常 — 差异就在显式列表触发 reader 相对索引路径。

## YOLO 感知训练 (自动标注 → YOLOv8s, 2026-08-07)
真机感知前端: 相机图像 → YOLO 检测 hand/peg/hole → 2D→3D → 39D state → 策略。
**零人工标注**: `tools/gen_yolo_data.py` 用 metaworld 渲染图 + 模拟器 3D 位置针孔投影到 2D 自动生成 YOLO 标注 (3 类: hand/peg/hole); `tools/train_yolo.py` 训 YOLOv8s → **mAP50 0.994 / 42ms 推理**。
**关键坑**: ①`env.set_task(mt.train_tasks[0])` 必须 (train_tasks 是 **list** 不是 dict, `["name"]` 索引报 TypeError) ②`env.seeded_rand_vec` 是 **bool** 不是位置向量, 相机自动跟随场景别手动改 cam_pos ③ultralytics 输出自动加 `runs/detect/` 前缀 (实际在 `runs/detect/outputs/yolo_peg/<name>/`) ④verbose=False 时看 `results.csv` 每 epoch 一行监控进度。
**⚠️⚠️ 小训练集 mAP 虚高 + 未见过场景检测 0 (2026-08-07 实测, 老倪踩坑)**: 3 episodes (450张) 训出 mAP50 0.994, 但对**训练集外的 seed 场景** `model.predict(env.render(), conf=0.2)` 检测 **0 个目标** (训练图能检出 0.96, 未见过场景 0) — mAP 高只说明训练分布内拟合好, **不保证泛化**。检测目标检测到 0 → 2D→3D 反投影空 → state 对齐失败。**修复: 数据扩到 30 episodes (4500张) 重训**, 覆盖多 seed 初始化。
**⚠️ env.render() 数组 vs 文件路径检测差异 — 真根因是 RGB/BGR (2026-08-07 实测推翻 PIL 方案)**: 同一帧存成 PNG 文件 `model.predict(path)` 检出 3 目标, 但 `model.predict(env.render() 数组)` 检出 0。**中间的"PIL 转换 RGB 数组再 predict"方案也无效** (实测 `PIL数组方式: []` 仍 0)。**唯一有效: 转 BGR 数组** — ultralytics 内部用 BGR:
```python
import cv2
if img.dtype != np.uint8: img = (img*255).astype(np.uint8)
img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)   # ← 关键
res = model.predict(img_bgr, conf=0.4, verbose=False)[0]
```
**速度**: 存临时文件再 predict 路径 = 1.12s/帧 (太慢, 4500 帧要 84 分钟); BGR 内存方式 ≈ 实时 (快 100 倍)。检测数不稳定 (0/1/3 波动) 时先查 RGB/BGR。
完整流程/结果/下一步: `references/yolo-training.md`

## YOLO 输出对齐 39D (2026-08-07 老倪: "Yolo的输出跟39D对齐", 纠正"用模拟器直给39D")
**老倪纠正**: 不是让模拟器直给 39D (等价完美检测), 而是**仿真也要模拟真机感知链** — YOLO 2D 检测 → 反投影 3D → 填入 39D 观测的对应段。这样仿真/真机同构 (真机也只有 YOLO 2D 检测, 没有上帝视角)。**工具**: `tools/yolo_state_aligner.py`:
- **39D 观测结构** (`env._get_obs()`): `[0:3]=hand 位置, [18:21]=peg 位置, [36:39]=hole/goal 位置` (实测 seed0: hand [0.005,0.601,0.195], peg 同 hand, hole [-0.274,0.587,0.13])
- **2D→3D 反投影**: `cam_quat` 转 Rotation 矩阵 → `cam_forward=-R[:,2]`, `cam_right=R[:,0]`, `cam_up=R[:,1]`; 像素偏移 `ndc_x=(u-W/2)/f, ndc_y=(H/2-v)/f` (f=(H/2)/tan(fovy/2)); 光线 `dir = fwd + ndc_x*right + ndc_y*up` 归一化; 与水平面求交 `t=(plane_z-cam_pos[2])/dir[2]`
- **⚠️ 高度假设**: hole 在桌面 z≈0.03; hand/peg 悬空 z≈0.25 是**近似** — 实测反投影 hand [0.401,-0.462,0.25] vs 真实 [0.004,0.601,0.155] 误差大 (hand 真实 z=0.155 非 0.25)。**要精确: 生成训练数据时把真实 z 也记进标注/元数据, 反投影用真实高度** (YOLO 只给 2D 框, 3D 需要深度先验 — 仿真里可用模拟器真实 z 做先验, 真机用深度相机/标定)
- **2D→3D 精度分布 (2026-08-07 标定实测)**: 画面中心区准 (peg X 偏移仅 0.039, YOLO [0.205,0.521,0.03] vs 真实 [0.166,0.568,0.03]), **画面边缘误差大** (hole X 偏移 1.269 — 针孔近似在边缘失真)。**插拔任务 peg 是关键目标且居中 → 定位已够用 (±4cm); hole 边缘误差大可用 peg 插入点间接推断**。修正系数按标定写死 (`pt[0]-0.04`), 别用之前 -2.98 的旧值 (BGR 检测框位置与文件方式不同, 系数会变)
- 对齐函数: `aligned = obs39.copy(); aligned[0:3]=det3d["hand"]; aligned[18:21]=det3d["peg"]; aligned[36:39]=det3d["hole"]`
- **⚠️ 生成器 --yolo 模式: YOLO 检测必须用 480 原图, 不能用 ep_imgs 的 128×128 resize 帧** (检测精度骤降/失败)。gen_metaworld_data.py 里 `yolo_img = img` (env.render() 原图) 单独存, 别复用 `ep_imgs[-1]`; 视频合成仍用 128 帧
- **--yolo 生成速度**: 每帧 1 次 YOLO 检测 (~42ms 推理 + 预处理), 8 episodes×200 帧 ≈ 5-8 分钟, 可接受; 若用临时文件方式则 1.12s/帧 不可行 (见 BGR 修复)
- **mujoco 版本坑**: 新版本无 `cam_target` 属性 (`AttributeError: 'MjModel' object has no attribute 'cam_target'`) — 用 cam_quat 算方向, 别用 cam_target
- **⚠️⚠️ 评估侧也必须喂 YOLO 检测 state (2026-08-07 实测: ACT-v7 0% 的元凶之一)**: 训练数据 state 是 YOLO 检测的**带噪声坐标** (±4cm), 但 `eval_insert.py run_episode` 默认喂 `env` 返回的**真实 obs** → 训练/推理分布不匹配 → 模型学的是\"噪声位置→动作\"映射, 给真实位置对不上 → 抓起 0/10。**修复**: `run_episode(policy, seed, steps, yolo_aligner=None)` 加参数, 循环里 `det3d = yolo_aligner.detect_3d(np.asarray(env.render())); st_raw = yolo_aligner.align(st_raw, det3d)` 后再归一化。**评估条件必须与训练条件同构** (真机只有 YOLO, 没有上帝视角)。但注意: YOLO 检测每步 ~42ms+预处理, 10 seeds×200 步会拖慢评估 — 可用 5 seeds 或接受慢。
- **YOLO 噪声对抓取精度的硬约束**: peg 3D 定位 ±4cm (画面中心) 对\"接近\"够用, 但**抓取销钉需要 <1cm** — YOLO 2D→3D 反投影噪声可能成为插拔上限 (模型学的是噪声坐标, 真实抓取误差叠加)。若 39D+YOLO 训练仍 0%: 先怀疑 ①评估没喂 YOLO state ②YOLO 噪声太大需深度相机/标定外参 (不是模型没学会)。

## 视频方向修正 (2026-08-06 老倪: "逆时针水平转90度, 你现在的视频是倒着看的"; 2026-08-07 大改)
- metaworld 默认 topview 俯视看不出插销立体结构 → 换 **corner2** 相机 (`env_cls(render_mode="rgb_array", camera_name="corner2")` 构造时传, 事后赋值无效)
- **帧旋转 `np.rot90(rgb, k=2)` = 共逆时针180°** (老倪确认方向: 先转90°还不够, 再转90°; k=2 是最终定稿)
- 验证: 渲染帧与 topview 差异 >50; 布局特征 (corner2 工作区纹理 std 最高 54.5)
- 视角验证先发单帧确认方向, 再批量生成 (老倪会看方向对不对)
- **✅ 方向验证必用"绿色 peg 重心"量化, 不能靠肉眼/像素差异**: 原帧绿色重心 (269,290) → 正确旋转180后 (209,188)。`green_center(img)` = 像素 (G>120 & R<100 & B<100) 的均值坐标。像素差异均值会因检测框/水印干扰失真, 重心法只看目标物体位置, 一锤定音
- **⚠️⚠️ 重生成子集视频必须精确匹配参照视频的相机+旋转参数 (2026-08-07 老倪终审: "所有视频与后两个保持一致, MLP和专家视角正确, 前五个虽然正向但看不到插槽")**: 只重生成部分模型时 (如换 checkpoint 后刷前 5 个), 命令行默认 `--camera corner` (看不到插槽) 与参照 (MLP/专家, GUI `_run_rollouts` 用 **`--camera corner2 --rotate-ccw`**) 不一致 → 老倪对比参照后打回"视角不对"。**正确配置 = `rollout_video.py --policy X --steps 60 --task peg-insert-side-v3 --camera corner2 --rotate-ccw --out reports/rollout_final_X`** (与 _run_rollouts 完全同款, 别用默认 corner)。重生成后**与已知正确的参照帧做亮度分布对比验证**: 上半/下半 mean 应一致 (corner2 实测 136/128, 7 个模型全同; corner 是 113/94)。"正向但没有插槽" = 相机参数错, 不是旋转错 — 先对相机再谈方向
- **⚠️⚠️ 2026-08-07 实测推翻"先旋转帧再检测"**: 之前 skill 写"必须先旋转帧再检测, 检测后 ffmpeg 转会让框错位" — **此结论错误**。实测: ①`img[::-1,::-1]` 旋转帧 + 甚至 PIL 转换后再 `model.predict`, `res.plot()` **仍输出原始方向** (rot3 vs 原帧差异仅 4.0, 根本没转) ②`cv2.VideoWriter` (mp4v) 写出的视频**自带正确方向** — 检测原帧写出, 绿色重心已是 (208,181)≈正确旋转帧, 无需再 ffmpeg 转; 若再转反而错
- **✅ 正确流程 (检测视频)**: YOLO 检测**原帧** (框坐标正确) → `res.plot()` 叠加 → cv2 VideoWriter 写出 → **抽帧用绿色重心验证** → 重心≈旋转帧即已正确, 别再 ffmpeg 转。5 模型纯画面视频 (ffmpeg 从 PNG 拼) 方向是"反"的, 才需要 `ffmpeg -vf "transpose=2,transpose=2"` (180°=两次 transpose)
- **管线隐式方向不同**: cv2 写视频 (自带180°) vs ffmpeg 拼 PNG (原方向) — 改生成管线后必须重新验证方向, 不能假设

## ⚠️⚠️⚠️ 坐标叠加架构 (2026-08-08 老倪核心架构修正: "图像是背景, 坐标是逻辑, 你得叠加上坐标, 而不是让图像和坐标混合")
**老倪纠正**: 不能让 state 坐标和图像 token **混合** (现状: ACT 把 state 投影成 1 个 token 拼进 [latent, state, *49图像token] 序列 → 坐标被 49 个图像 token 淹没, transformer 注意力被图像主导) — 要**叠加**: 坐标是**逻辑主线**, 图像是**背景旁路**。
**为什么 MLP 成功而视觉大模型全败**: MLP 输入纯 39D 坐标直接映射动作; ACT/SmolVLA 图像+坐标混合, 坐标信息被稀释。**信息到位简单 MLP 也能学会; 信息缺失再强 Transformer 也白搭** (见"插拔学不会的根因"节)。
**ACT 模型改动 (src/lerobot/policies/act/modeling_act.py, 训练+推理共用 forward)**:
```python
# 改前 (混合): encoder_in_tokens = [latent_proj, state_proj, *cam_tokens]
# 改后 (叠加): latent_embed = encoder_latent_input_proj(latent_sample)
#              latent_embed = latent_embed + encoder_robot_state_input_proj(batch[OBS_STATE])  # 坐标叠加进 latent
#              encoder_in_tokens = [latent_embed]  # 只剩 1 个 latent token, 图像 token 照旧当背景
```
**配套改动**: `n_1d_tokens` 从 `1+robot_state+env_state` 改回 `1` (state 已叠加进 latent 不再占独立 token) — 否则 pos_embed 18 vs 实际 17 报 `size of tensor a (17) must match b (18)`。VAE encoder 的 robot_state 保持原样 (训练辅助重构用, 不动)。
**控制台 simulink 功能块 (2026-08-08)**: 5 模型行 State Adapter 后加蓝色 **🧩 坐标叠加** 节点 (NODE_TYPES 注册 `coord_overlay` + node_logic.py `node_coord_overlay` + 绘制 `latent += state×gate (45D)`)。**新节点三处注册缺一不可**: ①`NODE_TYPES` (颜色/中文名) ②node_logic.py `_reg("coord_overlay", ["坐标叠加","CoordOverlay"], ...)` + `node_coord_overlay(ctx)` (框架动作 `module._set_coord_overlay_ctx` 用 `getattr(..., None)` 容错 — simulink_module 可能没有该方法) ③画布默认结构行插入 (5 模型行的 "🔌 State Adapter" 后)。验证: `/usr/bin/python3 -c "import node_logic; print('coord_overlay' in node_logic.NODE_LOGIC)"` + match_node("🧩 坐标叠加")。
**⚠️ 叠加架构训练后 ACT 仍 0/10 但行为变了**: overlay 训练 loss 0.727 收敛但输出**恒定动作 [-0.34,-0.35,-0.03]** (5 步完全一样) = 学到"预测平均动作" — **叠加架构没解决数据平均化** (问题在数据: 45D seg 数据轨迹仍含转移段方向反转), 治本靠分段数据 (stop_after_grab, 见三件套节)。**架构正确 + 数据干净 才同时具备**。

## 视频交付格式 (2026-08-08 老倪: "视频反了; 旋转180度再给我; 而且要把已经有的视频, 一起发给我; 别一个一个发")
- **旋转**: 老倪反馈"反了"时 `ffmpeg -vf "transpose=2,transpose=2"` (180°) 再发; 之前 5 模型视频确认"原版不旋转"是另一批 — **以当次反馈为准**
- **一次发齐**: 多个视频在**一条消息**里多个 `MEDIA:/path` 发 (别一个个发, 老倪会催"视频发我啊/你只发了一个")
- **每视频配一行说明** (模型名+结果+距孔), 别只发文件不带字
- **优先发成功视频**: 只有成功插拔的视频才叫"结果"; 失败模型也出"后退"对比视频证明结论 (见老倪汇报风格铁律节)

## 编辑大 GUI 文件铁律 (2026-08-06 实测把 simulink_module.py 截断; 2026-08-07 又把 studio.py 截断)
**禁止 read_file(limit)+write_file 全量回写大文件**: `read_file(path, limit=2000)` 读 1771+ 行大文件 → 内容截断 → write_file 写回 → **文件尾部丢失** (`IndentationError` 在 1773 行, SimulinkModule 类全没, 控制台启动崩 `cannot import name`)。**必须用 patch (old/new) 或 execute_code 里先全量读再替换再写**; 改完 `ast.parse` 验证 + `wc -l` 对比。**恢复**: `git show HEAD~3:tools/gui/simulink_module.py > 文件` (5423 行完整版 vs 截断版 1771 行) 再重应用 patch。
**⚠️⚠️ 2026-08-07 studio.py 截断事故 (execute_code 字符串索引错位)**: 用 execute_code 做**大段删除** (DATASETS 列表删 10 条目) 时, 字符串 `src.index(...)` 多步拼接错位 (`seg[len(seg):]`/`meta_end2` 定位错) → 写回后文件从 8057 行变 1266 行 — **文件尾部 (TrainingModule 以后全部) 丢失**。教训:
1. **大段删除首选 patch (old/new 精确块)**, 别用 execute_code 字符串索引拼接 (索引一步错=整文件毁)
2. 必须用 execute_code 时: 每次写回前 **`ast.parse(src2)` + 行数断言** (`src2.count(chr(10)) > 7500`) 再 open().write()
3. **恢复流程**: `git checkout tools/gui/studio.py` (回到最近 HEAD, 含当天上午已提交的改动) + **重应用 HEAD 之后的 patch** (本会话 8 处: _is_cached 特判/_on_view_dataset 非模态/当前数据集卡片/_local_datasets/_populate_table 本地行/信息按钮本地分支/DataSpaceModule+modules dict+首页卡片/DATASETS 删减) — 每处 patch 后验证; 恢复完跑 offscreen 构造 DatasetModule/DataSpaceModule 断言表格行数/摘要
4. patch 工具报 \&quot;file was modified since last read\&quot; 警告 = 有未记录的写入, 先 re-read 再 patch

## 重训后必须更新 train_curve_*.json 的 ckpt (2026-08-06)
`rollout_video.py`/`compare_models.py` 都读 `reports/train_curve_<policy>.json` 的 `ckpt` 定位模型。
**重训后 ACT/SmolVLA/SmolVLA+LEW 的曲线文件仍指向旧 checkpoint** (config 训练不自动更新曲线文件!)
→ 视频"看起来在动"但用的是旧模型。vla_touch/awe 训练脚本会自动写最新 ts, 无需手动。
```python
# 重训后手动更新 (sed/python):
d["ckpt"] = "outputs/train/<policy>_final/checkpoints"
```
同批对比必须全部指向同一轮训练产物, 否则横比不公平。

⚠️ **VLA-Touch/AWE 脚本硬编码保存目录 `checkpoints/000050/pretrained_model`** (2026-08-06 实测):
`--steps 500` 训完也存 000050 — 目录名不反映步数, 但内容是最新权重, rollout 能加载 (无碍);
`train_curve_<p>.json` 的 `step_s` 是真实步速 (33.3), 不要被目录名 000050 误导以为只训了 50 步。

## 多模型对比管道 (compare_models.py 体系)
### 训练曲线文件 (train_curve_<policy>.json) — 评估可见性的关键
- `find_ckpt` 读 `reports/train_curve_<policy>.json` 的 `ckpt` 字段定位 checkpoint; 缺曲线文件 = 模型不可见 (有 checkpoint 也跳过)
- **必须含 `curve: [[step, loss], ...]`** (不是纯 loss 数组!)
- 训练脚本的 `_log_loss` 若只 print 不 append 列表 → curve 缺失 → 报告生成器崩 `TypeError: 'float' object is not subscriptable` (AWE 踩过)
- 补曲线文件格式: `{"ts","ckpt":"outputs/train/<policy>_<ts>/checkpoints","step_s":15.0,"curve":[[0,1.6],[10,1.4],...]}`

### 模型加载 (5 模型 3 种加载方式)
- ACT: `ACTPolicy.from_pretrained(pm, local_files_only=True)` (LeRobot factory)
- SmolVLA/SmolVLA+LEW: `SmolVLALewPolicy.from_pretrained(...)` (同 factory)
- **VLA-Touch/AWE-zFlow: 自定义 model.pt, 不用 factory** — importlib 加载 tools/train_*.py 模块, `torch.load(model.pt)` 取 state_dict+config 手动构造:
  ```python
  spec = importlib.util.spec_from_file_location("train_awe_zflow", os.path.join(ROOT,"tools","train_awe_zflow.py"))
  mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
  data = torch.load(Path(pm)/"model.pt", map_location="cpu"); cfg = data["config"]
  # AWE 必须传 d_z 潜空间 (cfg 键是 "d_z"=[d_z1,d_z2,d_z3], 不是 latent_dims)!
  # 漏传 → 默认 [256,256,256] → load_state_dict size mismatch (head_z1 128vs256 / act_proj 320vs448)
  pol = mod.AWEZFlowModel(cfg["action_dim"],cfg["state_dim"],cfg["tactile_dim"],cfg["vis_dim"],
                          d_z1=cfg["d_z"][0], d_z2=cfg["d_z"][1], d_z3=cfg["d_z"][2], hidden=cfg["hidden"])
  pol.load_state_dict(data["state_dict"]); pol.eval()
  # AWE 输入输出在归一化空间: 输入 state 需 (s-s_mean)/s_std, 输出需 *a_std+a_mean 反归一化
  # model.pt 的 stats 键 = a_mean/a_std/s_mean/s_std (2026-08-06 修复后是原始统计; a_std 应≈数据真实std 非1.0)
  pol.stats = data.get("stats", {})
  ```

### ExpertMLP (distill 蒸馏模型) 加载链 — 3 个坑 (2026-08-07 实测, rollout 动作 0.0 排查)
`expert_mlp` 是 `tools/distill_expert.py` 产出的 **.pt 文件** (非 lerobot checkpoint 目录), load_policy/rollout 需特判:
1. **ckpt 是 .pt 文件不是目录**: `train_curve_expert_mlp.json` 的 ckpt=`outputs/rl_peg/expert_mlp.pt` → `os.path.isdir(base_dir)` False → 兜底 glob 也找不到 → `FileNotFoundError`。修: load_policy 开头 `if policy == "expert_mlp" and os.path.isfile(base_dir):` 特判 (importlib 加载 distill_expert 模块 → `mod.ExpertMLP(data["obs_dim"], data["act_dim"])` → `load_state_dict(data["model"])` — **dict 键是 `"model"` 不是 `"state_dict"`** (distill 保存 `torch.save({"model":..., "obs_dim":..., "act_dim":...})`)
2. **无 select_action → forward 分支**: ExpertMLP 只有 `forward(x)` (39D→4D)。rollout 推理加 `elif hasattr(policy, "obs_dim") and not hasattr(policy, "model"): pred = policy(batch["observation.state"])`; rollout_peg_check 同理 (`elif hasattr(pol, "forward") and hasattr(pol, "obs_dim")`)。不加 → 走到 awe 分支 (4 参数调用) 或直接 break → 循环 0 次/动作 0.0
3. **⚠️ state_dim 默认 2 陷阱**: st_dim 推断 `getattr(policy, "state_dim", 2) or 2` — ExpertMLP 只挂 `obs_dim` 不挂 `state_dim` → st_dim=2 → `zeros(2)` → forward `mat1 (1x2) and mat2 (39x512)` 失败 → 动作 0.0。**修: 加载后必须 `pol.state_dim = pol.obs_dim` (39)**。症状: rollout 报 `RuntimeError: mat1 and mat2 shapes cannot be multiplied (1x2 and 39x512)` 或动作均值 0.0 但插入检测 (rollout_peg_check) 正常 — 两处加载/推理都要同步
4. argparse `--policy choices` 必须含 `expert_mlp`/`expert_policy` (原只列 5 模型 → `invalid choice`)

### 其他坑
- **argparse choices 必须列全部 5 模型** — 只列 3 个 → `invalid choice: 'vla_touch'`
- **⚠️ compare_models.py 默认 data-root 不存在 → Scope 评估秒崩 (2026-08-08 实测)**: 默认
  `data_root="data/metaworld_act"`（早被清理）→ `FileNotFoundError: Provided directory does
  not contain any parquet file`（dataset_reader 加载 parquet 失败）。**必须显式传
  `--data-root data/metaworld_peg_grab6`**（当前有效数据）。Scope 输出:
  `reports/model_compare_<ts>.json`（keys: ts/dataset/frames/models）+ `reports/model_compare_images.png`。
  ⚠️ **compare_models.py 只评估 5 个视觉模型**（models dict 只有 act/smolvla/smolvla_lew/
  vla_touch/awe_zflow）——MLP/官方专家是独立评估（eval_distill.py / eval_insert.py），
  老倪要"7 个对比"时 Scope 图表 + 7 模型视频要分开交付，别让 Scope 少 2 个模型显得漏了。
- ckpt 候选目录加 `000050/pretrained_model` (快速验证版只有 50 步, 默认 last/000150/000300 找不到)
- **AWE-zFlow MSE 异常大 (16532 vs 其他 ~1.0) = 评估管道 action 空间不匹配** (zFlow 三层潜空间 vs 统一 2D 归一化), 不是模型坏 — 报告需标注不可比
- 同数据公平对比: 统一测试集 + 归一化空间评估 (模型输出即归一化空间, gt 用同统计归一化)
- 训练 steps: 链路验证默认 10 (2026-08-06 老倪), 正式 2000: config 用 sed 改 `^steps:`, 输出目录带 `_final` 后缀防 FileExistsError (output_dir 已存在且 resume=False 会崩)

## ⚠️⚠️ 长轨迹(300步)数据 → 行为克隆"平均化" — 所有 BC 模型都会中招 (2026-08-08 实测)
**症状**: ACT/AWE 用 300 步完整专家轨迹 (接近→抓取→转移→插入) 训练收敛后, rollout **方向学反/远离目标** (ACT 0.255→0.379, AWE 0.133→0.591)。短数据时 ACT 接近 0.133→0.024 正常。
**根因**: 轨迹内各阶段速度指令方向相反 (Phase1 接近 vs Phase5 插入), BC 回归学**全轨迹平均** → 方向≈0 或漂移。ACT chunk 回归 + AWE diffusion 都中招; **唯一免疫 = 蒸馏 MLP (39D 坐标直接映射, 单步条件反射)**。
**教训**: 提升插拔别盲目加长轨迹 — 用短轨迹 (只含接近+抓取段) 或走 MLP 蒸馏路线。
**metaworld 远起点 (--far) 不可行** (三条路全失败): env.step 手动移手受关节限制移不远; 官方专家远起点状态机失效 (拉不回); 手写多阶段专家远移后 10/10 全丢弃。起点距离上限 ≈0.24m (task 索引变化范围) — "学更长接近"靠数据多样性 (不同 task 索引) 而非远起点。

## ⚠️⚠️ 长轨迹数据修复三件套 (2026-08-08 老倪"全做": 分段数据 + 目标条件化 + 夹爪头分离)
长轨迹平均化确认后, 老倪要"改数据和架构" → 三件套落地 (gen_metaworld_data.py + eval_insert.py):
1. **① 分段数据 (`--stop-after-grab`)**: 官方专家轨迹 **抓起 peg 后保持 30 帧即停止记录** (循环内 `if grabbed_frames >= 30: break`) — 无转移/插入段 → 方向不再反转。检测: 每步 `peg_z_now > peg_z0 + 0.04` 则 grabbed_frames++。**官方专家保证抓起 (12/12 成功), 是分段数据唯一可靠来源** — 手写多阶段专家 grab-only 模式抓取率差 (20 条全丢弃)。
2. **③ 目标条件化 (`--rel-vec`)**: state 39D 尾部追加 6D 相对向量 = `[peg_pos-hand_pos, hole_pos-peg_pos]` → **45D** (MLP 成功核心: 每步知道目标相对位置)。**45D 改动必须同步 4 处, 漏一处就 CastError/广播错**:
   - `config_*.yaml`: `state_dim: 39`→`45` (+ 如有 `[39]` 形状列表也改)
   - `data/<root>/meta/info.json`: `features.observation.state.shape` `[39]`→`[45]` (漏 = CastError "Couldn't cast"; 生成器不自动更新 info.json, 手动改)
   - **评估侧 st_raw 补向量**: eval_insert 里 `if st_dim == 45 and st_raw.size == 39:` 用 `env.data.site_xpos[endEffector/pegGrasp/hole]` 现场算 rel_vec 拼上 (否则 `mat1 (1x39) and (45x256)` 崩)
   - `_load_stats` 候选加 seg 目录 (`act_peg_seg` 等) + fallback 加 `data/metaworld_peg_seg` — **VLA-Touch/AWE checkpoint 无 preprocessor (只有 config.json+model.pt) → 直接用数据 stats.json** (数据 45D, 别从旧 39D checkpoint 读)
3. **④ 夹爪头分离 (grip_assist)**: 启发式强制闭合**破坏纯模型评估** (MLP 6/10→0/10) — 只在"模型位置动作已对但夹爪决策缺失"时用 (如 ACT 方向性已学成); 纯模型评估用 `clip(act, -1, 1)` + 模型自己出夹爪。
**45D 训练结果 (2026-08-08 实测)**: ACT-seg 距孔变化 (0.357→0.214, 从"不动"到"会动") 但仍 0 抓起; VLA-Touch/AWE-seg 2000 步 0/8 — 方向性修复了但夹爪/完整插拔仍没学成, **插拔主力仍是蒸馏 MLP**。

**⚠️⚠️ stop_after_grab 截断实现 4 坑 (2026-08-08 实测, 轨迹恒 300 帧排查链)**: 加了 `if grabbed_frames >= 30: break` 但轨迹还是满 300 帧, 逐层挖出 4 个独立 bug:
1. **官方专家路径的 `continue` 跳过循环开头 break**: gen_metaworld_data.py 里官方专家分支 (use_official) append 后 `continue` → 循环开头 `if ... break` 永远执行不到。**修: continue 前再检查一次 `if stop_after_grab and grabbed_frames >= 30: break`** (两处检查: 循环开头 + continue 前)
2. **锁存逻辑 `grabbed_frames = max(grabbed_frames, 1)` 在 peg 持续升高时永不增长**: 官方专家抓住 peg 后保持升高 → 每帧都走 `peg_z > 阈值` 分支 `max(1,1)=1`, 只有回落才 `+=1` → 永不达 30。**修: 锁存后每帧无条件 `if grabbed_frames >= 1: grabbed_frames += 1`** (不依赖 peg 是否保持)
3. **阈值 0.04 太高**: 实测抓起瞬间 peg_z 只升到 0.065 (+0.035), `peg_z0(0.03) + 0.04 = 0.07` 差一点不触发 (第 80 步 0.065 未触发, 第 100 步 0.130 才触发)。**修: 阈值 0.03**
4. **截断后 meta 三处不同步 → IndexError/KeyError**: ①`all_eps.append({"length": args.steps})` 写死 300 — 截断后实际帧数 <300 → `IndexError: Invalid key: 1800 out of bounds for size 1015`。**修: length 用实际帧数 `len([f for f in all_frames if f["episode_index"]==ep])`** ②info.json `total_frames` 改了但 **`splits: {"train": "0:1888"}` 没改** → 同款越界 (grep 1800 查 meta 文件) ③手动重建 episodes parquet 缺标准列 → `KeyError: 'videos/observation.image/chunk_index'` → 需要 `chunk_index` + `chunk-000/index` + `chunk-000/from_frame` + `file_index` 等全套字段 (对照生成器 312-327 行格式)。**教训: 截断/过滤后元数据 (episodes parquet length + info.json total_frames/splits + 数据 episode_index 重编号) 必须三处同步, 别只改一处**
5. **判定数据是否截断成功**: `df.groupby("episode_index").size()` 应 < 300 (实测 93/104/84 帧); 轨迹恒 300 = 截断没生效, 先查上面 4 坑
6. **生成器主 env 必须 corner2**: `env_cls(render_mode="rgb_array", camera_name="corner2")` — 主 env 没 corner2 时官方专家动作时序乱 (85% 配方, 见官方专家节)

## ⚠️⚠️ AWE/VLA-Touch 评估反归一化 — eval_insert.py 两个分支都漏过 (2026-08-08 实测)
**症状**: AWE 评估 10/10 全 0, 距孔恒定 0.362 (与随机一致), 多次评估结果完全相同 (动作没生效)。
**根因**: ①`hasattr(policy,"_cond")` diffusion 分支输出后无反归一化 (ACT 分支有 `act*asd+am`, diffusion 分支漏了) ②**AWE 实测没有 `_cond` 属性** → 走 else 分支 (直接 forward), else 分支也漏 ③state 归一化用全局 stats.json 而非 checkpoint 自己的 s_mean/s_std。
**修复**: 归一化 `if "s_mean" in policy.stats: _sm=policy.stats["s_mean"][:st_dim]`; 反归一化 **_cond 分支 AND else 分支都要加** `act = act*_std + _mean` (键名 `a_mean/a_std/s_mean/s_std`, 非 action.mean/std)。细节+代码: `references/20260808-longtraj-eval-normalization.md`
**夹爪辅助 (grip_assist) 反而破坏纯模型评估**: MLP 纯模型 抓起 6/10 → 加启发式强制闭合后 0/10 (覆盖模型输出致整体错乱) — MLP 自己学会了夹爪时机, 评估用纯模型输出 + clip [-1,1]。
**MLP 插拔成功视频先扫 seed**: 15 seeds 里 seed1/5/10/14 插入成功 (seed14 距孔 0.004m) — 出"成功演示"先扫 seed 找成功帧, 别硬跑 seed0。
**训练/评估进程卡死排查**: ①grep 管道缓冲吞日志 → 重定向文件 (`python -u > /tmp/x.log`) ②importlib.reload 破坏模块状态 (reload 后 load_policy 返回 None) ③HF 大权重下载不稳 → `hf_hub_download` 单文件断点续传, **别 rm -rf *.incomplete** (误删已下载 blobs, 2.4G→245M); AWE SigLIP 缓存完整 (768M) 离线模式 (HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1) 直接成功。④**"Creating dataset" 卡住 (0% CPU 但进程活着) = `rm -rf ~/.cache/huggingface/datasets` 后 HF datasets 缓存重建** (3600 帧视频解码 + mmap, 首次要几分钟; 之后秒开) — 别训练前随手删 datasets 缓存, 只有 2D 污染 (坑19) 才删。⑤**HF 权重下载卡死的完整处理模式 (2026-08-08 SmolVLM2 实测)**: snapshot_download 卡 0% 留下 27-35 个 `.incomplete` 时, ①后台长跑重试循环: `for i in $(seq 1 30); do timeout 500 python -c "snapshot_download(..., max_workers=16)" && break; sleep 30; done >> /tmp/dl.log 2>&1` (notify_on_complete=true) ②`hf_hub_download` 单文件断点续传 (比 snapshot 稳, 大分片 500M/976M/1080M 逐个续) ③**权重完整性判定**: `find ... -name '*.incomplete' | wc -l` = 0 才算完整; 离线加载报 "does not appear to have model.safetensors" = 缓存不完整 (blobs 有 .incomplete), 需补全而非清缓存重下 (清 = 2.4G 归零重来)。**AWE 训练 max_frames 默认 200 太少**: load_data 只取 200 帧 (3600 帧数据用 5.6%) — 加 `--max-frames` 参数 (默认 2000), 全量传 3600。

## 训练配置要点 (Z-MAX 三阶段)
- S1: lr1e-4 / backbone冻结 / kl10 / chunk100 / n_action50
- S3: lr1e-5 / backbone1e-6 / kl10 / chunk100 / n_action1 (ensemble 硬性) / ensemble0.01
- 数据: metaworld_act (2D 状态, pusht 模板) / metaworld_cartesian (state3D→action4D 笛卡尔, 跨机器人泛化)
- Sim-to-Real 影子模式: 仿真模型只推理不下发, 输出 4D action 与真机对比量化 Reality Gap

## ⚠️ 垃圾 checkpoint 覆盖有效 checkpoint — 视频"没学到"的隐藏根因 (2026-08-07 实测)
**症状**: 某模型视频不动/动作≈0，但该模型明明训练收敛过（loss 低）。**评分与视频脱节**（评分最高但视频没动）。
**根因**: rollout/评估按 `train_curve_<policy>.json` 的 `ckpt` 兜底 glob **最新 mtime 目录**——**被中断的训练**（如 50-150 步被杀）目录 mtime 更新 → 加载垃圾权重。典型: 15:0x 多轮中断训练（act 150 步/vla 50 步/awe 50 步）比 14:15 的 1000 步有效训练"新" → 全加载垃圾。
**修复**:
1. 中断训练目录立即删: `rm -rf outputs/train/<policy>_<中断时间戳>`（保留有效训练目录）
2. `train_curve_<p>.json` 的 `ckpt` 字段**显式指向有效目录**（别依赖 glob 最新）: `d["ckpt"]="outputs/train/<policy>_<ts>/checkpoints"`
3. 辨别有效/垃圾: 目录名时间戳 + checkpoint 保存时间 vs 训练时长（1000 步训练应 ~5-40 分钟，50 步=几分钟内被杀）
4. **⚠️ 注意: vla_touch/awe 的 `checkpoints/000050/pretrained_model` 目录名恒为 000050**（保存逻辑写死）——目录名≠步数，看**文件 mtime** 与训练时长判断，别见 000050 就删
5. 重新 rollout 验证动作均值 >0.05（见上"关键验证"）
- 磁盘清理规则: 保留命名目录（act_peg_v7 等被 GUI/曲线引用）+ 有效时间戳目录；删旧实验（v6/v3/final/metaworld 前缀）+ 每目录只留最后 ckpt（`sorted(ckpts)[-1]` + last 软链重建）——smolvla_peg_v7 19G→1.4G

## ⚠️⚠️ 磁盘铁律: 训练产物绝对不允许增加 (2026-08-07 老倪 mid-turn 硬性警告 "你得保护好自己, 磁盘绝对不允许增加")
**量级**: smolvla/smolvla_lew 系每个 checkpoint **~1.4G** (SmolVLM2 500M + 优化器状态) — 4000 步训练存 ~25 个 ckpt = **35G/模型**, 两模型 72G; act 6.7G。一个训练链能把磁盘从 35G(4%) 干到 133G(14%)。
**铁律流程 (训练后必须立即执行, 不等用户提醒)**:
```bash
for d in outputs/train/<policy>_*/; do
  ck="$d/checkpoints"; last=$(ls $ck | grep -E '^[0-9]+$' | sort -n | tail -1)
  for c in $(ls $ck | grep -E '^[0-9]+$'); do [ "$c" != "$last" ] && rm -rf "$ck/$c"; done
  [ -e "$ck/last" ] && rm -f "$ck/last"; ln -s "$last" "$ck/last"
done
```
- **每目录只留最后 ckpt** (rollout/评估按 glob 最新或 last 软链加载, 删中间 ckpt 无损); 实测一轮清理 103G→8.9G
- 训练脚本 (resume_insert/gen 链) 尾部**自带清理**; 大模型续训前先估算 ckpt 数×大小
- /tmp 训练日志保留 (曲线恢复用, 见下), 但 /tmp 大临时产物 (peg_test/rollout 诊断目录) 随手删

## ACT 39D 完整观测 = robot(3) + env(36) — rollout 广播 (39,) vs (3,) 根因 (2026-08-07)
**症状**: ACT rollout 报 `operands could not be broadcast together with shapes (39,) (3,)` + 动作均值 0.0（即使 checkpoint 有效）。
**根因**: ACTPolicy 期望 **两个** state 输入: `observation.state`(robot 3D) + `observation.environment_state`(env 36D)（`encoder_robot_state_input_proj` + `encoder_env_state_input_proj`）。rollout 只传了 39D 合并 state → 模型内部广播失败。
**修复**（从权重维度推断，不依赖 config——config 可能无 input_features）:
```python
_env_proj = None
if hasattr(policy, "model") and hasattr(policy.model, "encoder_env_state_input_proj"):
    _env_proj = policy.model.encoder_env_state_input_proj.weight.shape[1]
if _env_proj and st.shape[0] >= 3 + _env_proj:
    batch["observation.state"] = torch.from_numpy(st[:3]).float().unsqueeze(0).to(dev)
    batch["observation.environment_state"] = torch.from_numpy(st[3:3 + _env_proj]).float().unsqueeze(0).to(dev)
```
39D 布局: `[0:3]=hand, [18:21]=peg, [36:39]=hole`（见 YOLO 对齐节）。

## 曲线数据丢失 → 从 /tmp 训练日志秒级恢复 (2026-08-07 两次覆盖后)
**背景**: GUI 重启时 auto_run 触发训练链 → 训练启动瞬间清空/覆盖 `reports/train_curve_*.json` → **有效训练成果的曲线全丢**（v10 报告后数据没了）。重训 1.5h 不可接受。
**恢复**: /tmp 下保留训练日志（stdout 重定向）→ 正则解析落盘（秒级）:
```python
import re, json, time
log = open("/tmp/vla4.log", encoding="utf-8").read()
pts = [[i*5+5, float(m.group(1))] for i, m in enumerate(re.finditer(r"action_loss:([\d.eE+-]+)", log))]
json.dump({"policy": "vla_touch", "ts": time.strftime("%Y%m%d_%H%M%S"), "curve": pts, ...},
          open("reports/train_curve_vla_touch.json", "w"), ensure_ascii=False)
```
- 已知可用日志: `/tmp/vla4.log`(vla 1000步) `/tmp/retrain_awe.log`(awe 1000步) `/tmp/mlp3.log`(distill 15 epochs `epoch (\d+): loss=([\d.eE+-]+)`)
- **⚠️ lerobot_train 日志 "step:1K" bug (2026-08-07)**: 1000 步显示 `step:1K` → 正则匹配到 `step:1` → 曲线尾点 step=1 错。**先展开**: `log = re.sub(r"step:(\d+)K\b", r"step:\1"+"000", log)` 再解析; 正则用 `step[:=]?\s*(\d+)\b`（\b 防 1K 的 1 误匹配）+ 去重排序
- 日志格式: lerobot `INFO ... step:990 ... loss:1.818 ...`（冒号分隔）; train_vla_touch/train_awe_zflow 用 `action_loss:xxx`
- 教训: **训练日志务必重定向到 /tmp 文件**（GUI 捕获的输出进程退出即丢）; auto_run 已改默认不训练（ZMAX_AUTO_TRAIN=1 才训练），避免重启再覆盖
- **⚠️ 重写/合并曲线文件时 ts 必须写真实训练完成时间, 别写当前时间 (2026-08-07 白屏事故)**: 手动修正曲线 (K 展开/ft 合并) 时若 `ts = time.strftime(...)` 用当下时间 → 曲线 ts 比视频帧 mtime 新 → `_check_newer_ckpt` 每次打开视频都判"新 checkpoint"→ 自动重生成 → **视频打开白屏/卡生成**。修: ts 写训练实际完成时刻 (act 16:18/smolvla 16:49/lew 17:24 这类), 或与视频帧同批处理; 曲线修改后检查 ts 与 rollout 帧 mtime 的相对关系

## 续训提升插拔 — 别用 resume, 用 --policy.path 微调 (2026-08-07 实测)
**老倪"继续训练, 要能插拔" → 1000 步续到 4000 步**。两条路实测:
- ❌ **lerobot resume 机制不可用**: config 加 `resume: true` 后报 `ValueError: A config_path is expected when resuming a run` — draccus 版 resume 分支要 `parser.parse_arg("config_path")` (config 里的 `config_path:` 字段指向含 train.yaml 的目录结构), 单 yaml 文件配置没这个字段 → 别折腾
- ✅ **微调续训 = 加载 checkpoint + 新目录 + 更长 steps** (等价续训, loss 从旧末点继续降):
```bash
# config 派生: 改 output_dir/job_name 新时间戳 + steps: 4000 (从 restore/原版 config)
./.venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_ft.yaml \
    --policy.path=outputs/train/act_<ts>/checkpoints/$(ls .../checkpoints | grep -E '^[0-9]+$' | sort -n | tail -1)/pretrained_model
```
- **曲线合并 (step 偏移 +1000)**: 新训练从 0 开始 → 新曲线 step 全部 +1000 拼到旧曲线后 (`pts[1000+int(s)] = loss`), 旧步 `setdefault` 不覆盖; 排序后 400 点
- 微调续训验证: `/tmp/ft_<policy>.log` 的 loss 起点 ≈ 旧训练末点 (act 1.99 续), 训练速度不变 (17-20 step/s)
- 续训目录命名 `<policy>_ft_<ts>` 防 FileExistsError (output_dir 已存在且 resume=False 会崩)
- 顺序: 先补曲线/恢复数据 (1000 步, 见\"曲线数据丢失\"节) 再续训 — 两件事别混

## 常见错误速查
| 症状 | 根因 | 修复 |
|---|---|---|
| 视频全黑 | render_mode=None | `env_cls(render_mode="rgb_array")` |
| rollout 视频不动 | 欠训练 (2026-08-06 起默认10步链路验证) 或 推理异常被吞 | 正式训练加 steps (2000) + except 里 print 异常 |
| 动作均值 0.0 但训练正常 | CUDA tensor 转 numpy / 缺 state 输入 | `pred.detach().cpu()` + 补 observation.state |
| **动作均值 0.0 + mat1/mat2 broadcast 异常 (2026-08-07 元凶)** | **obs 是 dict (observation.state/image), `np.asarray(dict)` → state 全零** | **`if isinstance(obs, dict): st = np.asarray(obs.get("observation.state", zeros))` 解包; 别写死 obs 是向量** |
| 视频在动但用旧模型 | train_curve ckpt 未更新 | 重训后手动更新曲线文件 ckpt |
| 误判 var=0.066 黑屏 | 归一化域 var 本来就小 | var×255² 还原, 或 unique>50 即真图 |
| invalid choice | argparse 没列全 | choices 加 vla_touch/awe_zflow |
| 'float' not subscriptable | curve 格式错 | `[[step,loss],...]` |
| 模型跳过评估 | 曲线文件缺失 | 补 train_curve_<policy>.json |
| FileExistsError | output_dir 已存在 | 换 _final 后缀目录 |
| 精简模型无 config/select_action | 自定义 model.pt | importlib 加载 + cfg 推断维度 + _cond/sample 适配 |
| 换场景数据 action.std()≈0 | 朴素直线专家在接触任务被环境衰减 | 多阶段专家策略 (接近→插入→保持+夹爪) |
| **视频"没拿起来"/动作幅度小 (std<0.15)** | **① 训练数据动作被压扁 (生成器存位移×30 而非专家指令) ② vla_touch x0=randn 噪声** | **① 数据侧: 存 clip(专家速度指令) [-1,1] (见 lerobot-dataset-engineering #13) ② rollout 侧: x0=上帧动作 (见上文精简模型适配)** |
| 训练后 rollout 动作幅度小但训练正常 | 推理路径与训练路径不一致 (x0 起点/归一化/条件) | 逐项对齐: 训练 q_sample 的 x0=x_{t-1}, 推理 x0=act_hist; 输入归一化 (s-s_mean)/s_std 输出反归一化 |
| 单独视频分不清模型 | 无水印 | drawtext/watermark_video.py 叠模型名 |
| AWE 输出饱和恒定大动作 (幅度0.7/平滑≈0/远离目标) | 输入未归一化 或 反归一化 stats 是错的 (a_std≈1 存了归一化后统计) | 输入 (s-s_mean)/s_std; 校验 model.pt stats 的 a_std≈数据真实std; 训练脚本 load_data 返回归一化前原始统计 |
| SmolVLA/LEW rollout 长时间无输出 (卡 8+ 分钟) | 加载 checkpoint 时内部仍访问 HF Hub 拉 VLM 权重, 未设 HF_TOKEN 被限速 | 后台跑 + timeout 500s; 确认 ~/.cache/huggingface/hub 有 snapshot; 进程活着=在加载, 别杀 |
| camera_name 设置无效 (像素差异 0.0) | gym 包装忽略事后属性赋值 | env_cls(render_mode="rgb_array", camera_name="corner") 构造时传; 验证新旧帧 diff>50 |
| **`mat1 and mat2 shapes cannot be multiplied (1x3 and 2x256)` / (1x2 and 4x256)** | **config.json 说 state[3]/action[4] 但权重实际是 2D — 训练被旧 ~/.cache/huggingface/datasets 缓存污染, 模型按缓存初始化成 2D** | **`rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub` 后重训; 诊断: load_file(model.safetensors) 查 `model.action_head.weight` 应 (4,256) / `model.encoder_robot_state_input_proj.weight` 应 (256,3); rollout 侧防御: st_dim 以权重为准 `policy.model.encoder_robot_state_input_proj.weight.shape[1]`, 不信 config** |
| **`from_pretrained` 抛 HFValidationError (Repo id must be 'repo_name' or 'namespace/repo_name')** | **绝对路径被 HF 校验拒绝** | **必须相对路径: `rel = os.path.relpath(cands[-1], ROOT)` 再 `from_pretrained(rel, local_files_only=True)`; eval/rollout 都如此, 手动 -c 命令别抄绝对路径** |
| **动作反归一化爆炸 (幅度 248/307)** | checkpoint preprocessor stats 坏 (action.mean 存成像素级 228/294) | `_load_preprocessor_stats()` 优先读 `data/<root>/meta/stats.json` 而非 checkpoint 的 normalizer safetensors; 校验 pol.stats['a_mean'] ≈ [-0.57,...] 级 |
| **`The truth value of an array is ambiguous` (rollout 报错但非维度)** | numpy 数组用于 `and` 判断: `policy.stats.get("s_mean") and ...` | 全写 `is not None`: `policy.stats.get("s_mean") is not None` |
| **SmolVLA 训练"秒完成" (27秒 End of training, 只到 000010)** | **sed 派生 config 残留 `steps: 10`** (链路验证调试值, v3 派生 v6 时没改) | 派生后必查 `grep '^steps' config_*.yaml`; 正式训练 `sed -i 's/^steps: 10$/steps: 2000/'`; 训练完验证 checkpoint 到 002000 而非 000010 |
| **5 模型视频方向"全反了" (2026-08-07 老倪最终裁决)** | **ffmpeg 从 PNG 拼的原版视频方向就是对的** — 我 ffmpeg transpose=2,transpose=2 转 180° 反而转错 | **默认发原版, 老倪说"反了"才转**; 转换前先抽帧用绿色重心量化确认 (原版重心 (269,290) 才是老倪要的); 别再"预防性"旋转 |
| **视频没动但模型明明训好了 (2026-08-07)** | **中断训练 (50步) 目录 mtime 新 → 加载垃圾 checkpoint** | 删中断目录 + train_curve ckpt 显式指向有效目录 (见"垃圾 checkpoint 覆盖"节) |
| **ACT rollout `broadcast (39,) (3,)`** | **39D 完整观测需拆 robot(3)+env(36) 给 ACTPolicy 两个 state 输入** | 从 `encoder_env_state_input_proj.weight.shape[1]` 推断拆分 (见"ACT 39D"节); **⚠️ 但 stats 归一化 (旧 3D stats vs 39D state) 也会报同款错误 — 见 zmax-model-compare-report 坑10b: `np.pad(sm, (0, st_dim-sm.size))` + `ss pad 后 +1e-6` (否则除0 NaN)**; 排查先加 `_tb.print_exc(limit=3)` 看行号再定 |
| **VLA-Touch 动作≈0.0001 + `mat1 and mat2 shapes cannot be multiplied (1x645 and 643x640)` (2026-08-07 未解)** | InterpolantPolicy `_cond` 拼出的 token 序列长 645 vs 模型权重期望 643 — **差 2, 疑似 state 39D 投影后 token 数与训练时 (3D) 不一致**, 或图像 patch 数不同; 触觉 3D + state 39D 的 concat 维度与训练 (state 3D) 不匹配 | **未解, 单独调**: 对比训练时 `_cond` 的输入构造 (训练喂 state 3D? 39D?), 让 rollout 的 cond 输入维度与训练一致; 短期可接受 (视频有运动但插拔动作小), 别把精力耗在误诊上 |
| **曲线尾点 step=1 异常** | lerobot 日志 `step:1K` (1000步) 被正则匹配成 step:1 | `re.sub(r"step:(\d+)K\b", r"step:\1"+"000", log)` 展开后再解析 |
| **45D state 改动后 CastError/broadcast 错 (2026-08-08)** | state 39→45 只改了一处 | **4 处同步**: config state_dim + info.json features.shape + eval_insert 评估补 rel_vec (`if st_dim==45 and st_raw.size==39` 现场算) + _load_stats 候选目录 (VLA/AWE 无 preprocessor → 直接用数据 stats.json) |
| **训练 0% 即崩 `OfflineModeIsEnabled` (2026-08-08)** | HF_HUB_OFFLINE=1 阻止数据集解析 (新数据集 HF 无 refs) | 新数据集训练用 `HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=1` (关 hub 离线, 留 transformers 离线) |
| **截断数据 `IndexError: Invalid key: 1800 out of bounds for 1015`** | episodes parquet length 写死 300 (截断后实际 90-107) + info.json splits 未同步 | 截断后 meta 三处同步: episodes length 用实际帧数 + total_frames + splits (`0:1015`), 见 stop_after_grab 4 坑节 |

## 视频对比对话框 (InferenceVideoDialog / FlowScopeDialog) 坑 (2026-08-07 全实测, simulink_scope.py)
- **白屏 = lab.size()==0 → scaled(0,0)**: 对话框未显示时 QTimer 已启动 (`_tick` 100ms), `lab.setPixmap(pm.scaled(lab.size(), ...))` 缩放到 0×0 → 白屏。修: 尺寸有效才 scaled, 否则 `setPixmap(pm)` 原图 (QLabel 自适应)
- **模型名标题必须叠在视频框左下角 (老倪偏好, "标题在框上方 → 视觉飘到上面一行窗口")**: QGridLayout 同 cell 叠加 `stack.addWidget(lab,0,0); stack.addWidget(cap,0,0,Qt.AlignLeft|Qt.AlignBottom)`, cap 半透明深底 (`background:rgba(13,17,23,140)`) 水印式 + `WA_TransparentForMouseEvents`; 画布节点文本同理放节点左下角 `QRectF(6, h-18, w-12, 14)`
- **视频"闪一下再次打开" = _check_newer_ckpt 误判**: 曲线 ts 比视频帧 mtime 新 60s+ 且**曲线完整** → 触发重新生成。训练中断残留的残缺曲线 (0-50 点, ts 却新) 每次打开都误判 → 闪一下重新生成。修: `if len(d.get("curve") or []) < 100: continue` (非正常 1000 步训练不算新 checkpoint)
- **on_infer_video 的 have 检查漏 expert 目录映射 → "视频没了"**: 对话框 `_load_frames` 有 `_dir_map` (`expert_mlp`→`rollout_mlp`, `expert_policy`→`rollout_expert_full`), 但触发前检查 (simulink_module.on_infer_video) 没有 → 误判无帧 → 触发重新生成 (rollout_video 的 --policy choices 不支持 expert) → 失败 → 视频"没了"。**两处目录映射必须同步**
- **Scope loss 指标行带训练时间 (老倪要求)**: `ts` 字段 `%Y%m%d_%H%M%S` → `MM-DD HH:MM`, 切片 **`_ts[4:6]-_ts[6:8] _ts[9:11]:_ts[11:13]`** (索引 8 是 `_` 分隔符, 用 [8:10] 会得到 "_1"); ts 缺失用文件 mtime; 七模型显示名映射 (act/smolvla/smolvla_lew/vla_touch/awe_zflow/expert_mlp/expert_policy)
- 各模型视频生成时间不同是**真实事实** (不同批次生成: 部分模型换 checkpoint 重刷, MLP/专家保留原版成功视频) — 别统一时间, 老倪要的就是真实时间

## ⚠️⚠️ 老倪汇报风格铁律 (2026-08-08 mid-turn 纠正: "你现在说话太啰嗦了。你只需要快速执行, 最后给我一个干净利落的汇报")
**执行期**: 收到"全做/继续/出结果"等指令后**少说话直接干** — 不解释过程、不逐条播报进度、不反复确认; 后台任务挂起后只等关键节点。**中间 OOB 纠正 (如"你到底要折腾到什么时候") = 立即停下手头无穷调试, 收敛到已有成果交付** (已训模型+已生成视频先发, 别等完美)。
**汇报期 (终稿)**: ①**数字表格化** (成功率/距离/训练步数一张表) ②**每条结论给视频/数据证据** (老倪要"视频证明呢") ③**形象化解释** (老倪: "数字太多他不懂" — 要比喻/故事: 长轨迹=教材教反了/夹爪=开关不是旋钮/相对向量=GPS) ④**给出下一步建议+等指令** (不擅自继续大动作)。
**关键**: 老倪"要看到插入/结果" = 要**成功视频** — 先扫 seed 找成功案例出视频 (见上文), 失败也出"后退"对比视频证明结论, 别只报数字。

## ⚠️⚠️ 老倪指令最小化执行 — "删掉X" = 只删X, 别扩大范围 (2026-08-07 三次纠正"别删多了")
**本会话血泪**: 老倪说"YOLO 3D, 删掉检测" → 我理解成删整个 YOLO 3D 检测功能/节点 → 老倪纠正"背景字删掉" → 我又误删背景行大字 → 老倪"就是删掉 检测 两个字" → 才发现**只是把节点名"YOLO 3D 检测"里的"检测"两字删掉** (改成 "YOLO 3D"), 期间还误删了背景行大字/小标 (已还原)。**三次纠正 = 指令最小化铁律**:
1. **"删掉 X" 默认理解成最小语义**: 先想"X 是名字? 功能? 节点? 文字?" — 有歧义就取最小 (删名字里的字 > 删条目 > 删功能 > 删数据), 别自作主张扩大
2. **删之前列引用范围** (grep 数量/位置), 范围大时先做最小改动 (如只改 LIBRARY 条目名) 让老倪确认, 别一次删干净
3. **误删立刻还原** (git show HEAD 提取原始代码 patch 回去), 还原后验证无残留
4. 类似模糊指令: "背景字删掉" (背景行大字?)、"没有的都删掉" (列表未下载条目 vs 磁盘数据 — 先只动列表/显示, 磁盘数据保留, 老倪要删磁盘会明说)
- 已入 memory: "无用/重复/没反应直接删不问; 指令最小化执行(删掉X=先改名字非删功能)"

## 数据闭环控制台模型选择器 (2026-08-07 老倪: 选模型→sim-to-real→stage3)
PipelinePanel (数据闭环 CICD 控制台) 新增「🤖 模型」区: QComboBox 列全部已训模型 (名字+训练时间) + 属性显示 (ckpt/步数/尾loss) + Sim-to-Real (S2)/Stage 3 按钮 → 写 PIPELINE_STATE.json。实现+验证细节: `references/20260807-pipeline-model-picker.md`

## 数据集管理 GUI 坑 (studio.py DatasetManager + dataset_viewer.py, 2026-08-07 老倪"点击查看没看到图片")
- **"50 任务数"是写死的 HF 云端条目声明** (DATASETS 里 `lerobot/metaworld_mt50` tasks:50), 与本地实际无关 — 显示 `50 · 本地1` (ds 加 `local_tasks` 字段); 信息弹窗加"📁 本地实际数据"块 (读本地 parquet 统计真实 episodes/帧数/任务)
- **"本地状态: 未下载"错误**: `_is_cached` 只查 HF 缓存目录 (~/.cache/huggingface/hub), 本地项目数据在 `data/` → metaworld_mt50 特判 `data/metaworld_mt50/data/*.parquet`
- **查看器 exec_ 模态 WSLg 弹不出** (记忆: 弹窗零容忍) → `viewer.show()` 非模态
- **系统 python3 无 pandas/pyarrow** (GUI 必须用系统 python3 有 PyQt5) → parquet 内嵌图像读不了 → **npz 读取路径**: `local_npz=data/metaworld_act/train.npz`, numpy 直读 `observations[frame].transpose(1,2,0)*255` → QImage; np.load 结果缓存 `self._npz_cache` (28MB 拖动滑块不重复读)
- **GUI 环境依赖一次装齐 (2026-08-07 老倪"怎么不提前装")**: 系统 python3 只有 PyQt5/numpy/PIL, 缺 cv2 → 数据集查看器 mp4 解码 / capture_cam 摄像头采集崩。**提前装**: `python3 -m pip install opencv-python --break-system-packages` (PEP 668 需 --break-system-packages; .venv 另有 cv2 5.0.0)。改动涉及新 import 前先 `python3 -c "import X"` 检查两个环境 (系统 python3 + .venv)
- **滑块翻帧不换图**: `_on_frame_changed` 只改 label 不加载 → 触发 `_load_video_frame()` (内部路由 mp4→parquet→npz)
- metaworld npz 的 episode slider 无意义 (npz 无 episode 概念, current_episode 不参与读取)
- **\&quot;当前训练数据集\&quot;卡片 + 本地数据集并入表格 (2026-08-07 老倪\&quot;simulink训练的数据怎么不在数据集管理显示, 控制台应该全管\&quot;)**: ①顶部卡片 `_current_dataset_html()` 扫描最近训练 config (`config_*.yaml` 按 mtime 倒序) 的 `root:` 行 — **坑: yaml 里是 `  root:` (2 空格缩进), 正则必须 `^\\s*root:\\s*(data/\\S+)` 否则全匹配失败兜底到 metaworld_act**; 显示路径+类型(插销绿/套环黄)+帧数 ②表格 `_local_datasets()` 探测 `data/` 下候选 → `local_rows + DATASETS` 合并填充, 本地行 repo_id=`local://xxx`、缓存列恒 `✅ 本地`、查看按钮传 `ds.get(\\\"local_root\\\")/ds.get(\\\"local_npz\\\")` (通用化, 不再 metaworld 特判)、信息按钮 `ds.get(\\\"local\\\")` 分支不查 HF 直接 `_msg_ok` 显示本地路径
- **npz 查看器性能坑 — NpzFile 数组访问是 lazy 解压 (2026-08-07 老倪\&quot;点下一帧为什么这么慢\&quot;, 1.5s/帧 → 1ms/帧)**: `np.load()` 压缩 npz 返回 NpzFile, **每次 `d[\&quot;observations\&quot;]` 都从磁盘重新解压整个数组** — 缓存 NpzFile 不够! 首次 load 时**提取到内存 ndarray**: `self._npz_obs = np.array(d[\&quot;observations\&quot;])` (states/actions 同理), 后续翻帧只索引内存数组。首次 943MB 解压 ~2s 可接受 (一次), 之后 0-1ms/帧
- **AV1 编码 mp4 → cv2 解码失败 (2026-08-07\&quot;0帧超出范围\&quot;)**: metaworld_act 的 `videos/` 有 AV1 mp4, cv2 5.0.0 不支持 AV1 硬件解码 → `_load_video_frame` 走视频分支失败。**修: 有 local_npz 时 npz 优先于视频**: `if self.local_npz and os.path.exists(self.local_npz): self._load_npz_frame(); return` (numpy 路径最可靠, 视频/parquet 兜底)
- **frame_slider maximum=0 → \&quot;下一帧点不了\&quot;**: slider 初始 maximum=0, 只有点\&quot;加载帧\&quot;才更新 → 老倪直接点下一帧没反应。修: viewer `__init__` 末尾 `QTimer.singleShot(0, self._load_video_frame)` 打开即自动加载第一帧 (maximum 就位 + 不用手动点加载帧)
- **图像 180° 旋转按数据集条件 (2026-08-07 老倪\&quot;metaworld_act 图像反了要旋转180\&quot;)**: 插销数据 (peg_v2/peg_lerobot) 与视频同源 (corner2 采集) 需 `np.rot90(rgb, k=2)`; **metaworld_act 是 MT50 官方数据 (方向本来正确) → 无条件旋转会把它转反**。`if \&quot;peg\&quot; in (self.local_npz or \&quot;\&quot;): rgb = np.rot90(rgb, k=2)`
- **本地行任务数列误填帧数 (4800/696\&quot;任务数\&quot;)**: 本地数据集是单一任务演示集 (无\&quot;任务数\&quot;概念), `tasks` 字段应填 `\&quot;—\&quot;` (帧数/eps 在描述列); HF 云端条目 (MT50) 才填真任务数 50
- **机器人列统一 Sawyer**: 本地 metaworld 数据 (插销/套环) robot 字段填 `\&quot;Sawyer (metaworld)\&quot;` 与 HF 行口径一致, 别填 \&quot;metaworld\&quot;
- **同名数据集去重 (peg_v2 vs peg_lerobot 显示两行)**: npz 源 (peg_v2 采集原始) 与 lerobot 格式 (peg_lerobot 训练用) 是同批数据 — 数据集管理**只留训练实际用的** (peg_lerobot), npz 中间产物不显示 (磁盘保留); MT50 同理本地行与 HF 行二选一 (留 HF 行, 可查看本地数据)
- **MT50 desc 要写明本地实际**: "MetaWorld 50种桌面任务 · 本地仅下载 task0 套环 (nut-on-peg) 10 演示" — 否则老倪以为 MT50 = 套圈任务
- **本地数据集名称用官方任务名 (2026-08-07 老倪"名称改成官方名字")**: 插销行显示 `📁 peg-insert-side-v3 · metaworld_peg_lerobot` (cands desc 写 `"peg-insert-side-v3 (插销插拔)"`, name 由 `desc.split(' (')[0]` 生成) — 中文俗称放括号里, 名称列用 metaworld 官方任务名
- **mt50 缓存检测必须递归 glob (2026-08-07 老倪"缓存也没显示有")**: parquet 在 `data/metaworld_mt50/data/chunk-000/` 子目录, `glob("data/*.parquet")` 匹配不到 → 显示"未缓存"。修: `glob.glob(..., "**", "*.parquet", recursive=True)`
- **orin 采集包 json 格式 → 查看器加 json 支持 (2026-08-07 老倪"orin 真机数据加载不上")**: orin_live 是 `auto_*.json` 状态采集包 (meta: source/frames 150/n_joint 6 + frames 列表 [{observation.state 6D, action 4D}]), **无图像**。`_load_video_frame` 开头加分支: `local_root` 有 `*.json` 且无 parquet/video → `_load_json_package()` 显示包 meta + 当前帧 state/action 文本 (ep_slider 切包, frame_slider 切帧)。真机**有图像**的数据在 `orin_real_v1` (parquet + mp4, cv2 能解码 64×64) — 数据集管理 orin 行 local_root 指向 real_v1 而非 orin_live (否则"真机数据没有")
- **orin 行 desc 统计 json 采集包数**: `_local_datasets` 探测 `glob(data/<d>/*.json)` 数量 → desc 显示 "114 采集包" (无 info.json/npz 的格式); desc 拼接帧数字段含"采集包"时不加" 帧"字 (`"" if "采集包" in str(frames) else " 帧"`)
- **本地数据行的下载按钮必须禁用 (2026-08-07 老倪"真机数据是台架采集的, 怎么能上 huggingface下载呢")**: 本地数据集 (local://) 没有 HF 下载语义, 点"下载"会报 `缺少 huggingface_hub 库, 无法下载`。**✅ 已落地 (2026-08-07 晚)**: `_populate_table` 里 `if is_local:` 分支 — orin 数据 (tags 含 "orin") → 按钮变「📥 CICD」+ `QDesktopServices.openUrl("https://datadrive.world/cicd.html")` (真机数据从网页采集下载); 其他本地 (metaworld) → 按钮「本地」+ `setEnabled(False)` (已有数据无需下载)。**⚠️ 改按钮分支时注意别误删后续的 manual_btn 创建行** (本会话 patch 误删 `manual_btn = QPushButton("📥 手动")` 致 GUI 启动 NameError) — 改完必须 offscreen 构造 StudioMainWindow 验证

## 🌐 全局数据空间系统 (2026-08-07 老倪: 数据库对应每个 node, 全息信息, 数据一致性, 开始整改)
**架构**: 控制台所有数据对象统一注册表 + simulink node 映射 + 一致性检查。三件套:
1. **`tools/gui/data_space.py`** — `GlobalDataSpace` 类:
   - 五类注册表 (scan 扫描, 3s 节流): `datasets`(data/ 8 候选, 帧数/eps/维度/ts) · `curves`(reports/train_curve_*.json, 点数/尾点) · `models`(outputs/train/*/checkpoints 最后 ckpt, policy 从目录名 `rsplit(\"_\",2)[0]`) · `rollouts`(reports/rollout_*/frame_*.png) · `reports`(pdf+对比 mp4)
   - `node_objects(node)` 全息映射: 数据源→数据集 / 训练→曲线+模型 / 推理·视频→rollout / Scope→曲线 / PDF→报告
   - `consistency()`: 数据集目录存在性 + 训练目录缺曲线文件 → 问题列表; `summary()` 计数
2. **功能块 (Library) 动态数据集组**: LIBRARY 循环后追加探测 `data/` 已有数据集 → `📦 {d}` 按钮 → `add_node_at_center(\"data\", f\"📦 {dd} 数据\", {source, data_dir, desc})` (插销/套环/Orin 同步显示)
3. **studio.py `DataSpaceModule` 页** (modules dict + stack.addWidget + 首页卡片 `(\"dataspace\",\"🌐\",\"全局数据空间\",...)`): 表格 7 列 (节点|类型|关联对象|属性|时间|状态|路径) — 每个画布 node 一行 (node_objects 每 node 最多 3 对象), 顶部摘要 (数据集/曲线/模型/视频/报告/画布节点数) + 🔄 刷新 + 一致性问题红字列表
- **验证**: offscreen 构造 DataSpaceModule → 摘要渲染; node_objects 映射断言 (数据源→数据集 4 对象等); 画布节点 0 时摘要仍正常 (DataSpaceModule 构造用 `type(\"W\", (), {\"simulink\": None})()` 假主窗口)
- 数据空间刷新时机: 训练/推理/清理后 🔄 手动 (scan force=True)

## metaworld_act 数据 696 帧的真实来源 (2026-08-07 老倪"696帧怎么选出来的")
**不是渲染的** — `tools/ci/prepare_metaworld.py` 从预生成 parquet (`data/metaworld_mt50/data/chunk-000`, 206 episodes / 25650 帧) 转换, **默认 `--max-files 2` 只读前 2 个分片** → 879 帧 → 20% 划验证 → train 696 + val 183 (图像 resize 128×128, state 4D / action 4D, task_name=zmax_metaworld)。**696 帧 ≈ 全量 25650 帧的 2.7%** — 快速迭代用, 插拔是长程任务 (抓起→对准→插入) 这点数据是瓶颈 (MLP 插入 55% vs 专家 85%)。提升插拔: 重生成全量 (`--max-files 全部`) 再训练。判别数据集是否精简: meta/info.json 的 total_frames vs train.npz 帧数
