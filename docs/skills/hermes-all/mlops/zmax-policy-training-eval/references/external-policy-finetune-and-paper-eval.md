# 外部论文权重: 原项目评测复现 + 域内微调 + 离线回放闸 + 直驱 (2026-09-12 INTACT 实测)

**触发**: 要"用外部项目的预训练/论文权重开我们的机器人"; 或外部模型搭好了但驱动不了我们的任务;
或要给用户看"原生能力效果"视频。

姊妹文件: `l3-official-inference-and-insert-fixes-20260910.md` (官方推理管道)、
`eval-protocol-and-false-positive-defense.md` (评估协议/假突破防御)。

---

## 1. 原项目自带评测 = 零训练成本拿"原生能力"证据 (含视频)

外部项目脚本自带评测 (`eval.py --config-name=<task>`), 它才是"原生能力"的权威口径 — 不用自己写。

**两条必踩的定位错误 (论文权重 = 冻结运行时)**:
- 在仓库根跑 → `Error locating target 'module.InverseTransitionActor'`
  → 必须 `cd <repo>/paper_runtime` (冻结运行时目录) 再跑, 并 `PYTHONPATH` 指向它。
- `solver=direct` → `Error locating target 'direct_solver.DirectSolver'`
  → 论文运行时的零搜索求解器叫 **prior_only** (根 `direct_solver.py` 与论文 actor 命名不兼容)。

**可复用命令** (实测通):
```bash
cd /home/ubuntu/INTACT-JEPA/paper_runtime
INTACT_SKIP_PREFLIGHT=1 STABLEWM_HOME=$CACHE LOCAL_DATASET_DIR=$CACHE \
HF_ENDPOINT=https://hf-mirror.com MUJOCO_GL=egl PYOPENGL_PLATFORM=egl PYTHONPATH=$PWD \
../.venv/bin/python eval.py --config-name=tworoom solver=prior_only \
  policy=recovery_delta_full_tworoom_s3072 seed=42 eval.num_eval=6 \
  output.filename=tworoom_direct_seed42_n6.txt
```

**落点与清理**: 视频 `env_*.mp4` + `<task>_results.txt` 落在 **checkpoint 目录的父目录**
(即 `$STABLEWM_HOME/`), 每轮**覆盖** → 跑前 `rm -f $CACHE/env_*.mp4`, 跑完**立刻复制**到自己的
目录 (`reports/intact_official/<task>/`), 否则下一轮把上一轮证据覆盖掉。

**数据集 (官方命名, 缺哪个报哪个)**: `$STABLEWM_HOME/datasets/` 下 `pusht_expert_train.h5` /
`dmc/reacher_random.h5` / `cube_single_expert.h5` / `tworoom.h5`; HF 源 =
`quentinll/lewm-pusht` (`pusht_expert_train.h5.zst`) / `quentinll/lewm-reacher` (`reacher.tar.zst`) /
`quentinll/lewm-cube`。缺文件时报的是
`Unable to synchronously open file (name = .../datasets/xxx.h5)`, 别去查环境。

**判"真零搜索"**: `solver_timing.get_cost_calls_mean == 0` (不是顶层 `get_cost_calls`)。

**本机实测 (论文权重 · 零搜索)**: tworoom 100% (6/6) · cube 83.3% (5/6) · reacher 97.0% ·
pusht 79.3%。数据集未就位时 (reacher/pusht 需下载) 只能跑 cube/tworoom。

**⚠️ 任务名撞车**: 原项目 `reacher` = DMControl 两连杆臂 (`swm/ReacherDMControl-v0`, qpos_match),
**不是** metaworld 里那个 Sawyer 臂的 reacher; `pusht` = `swm/PushT-v1` 2D 推块; cube/tworoom = OGBench。
用户问"原项目不是有 XX 机器人么, 为什么还要训练"时, 先澄清这个撞车 — 原项目从未训过我们的任务。

## 2. 外部模型没有本任务权重 → 只能域内微调

**动作空间语义 (必须从训练代码挖, 别猜)**:
- `action_dim = frameskip × 数据集动作维` (INTACT: 2×4=8) → 输出 chunk 的 `d0:4` = 第 t 拍动作,
  `d4:8` = 第 t+1 拍。
- 训练时动作列被 **z-score** (`get_column_stats`, ddof=1) → 推理侧唯一该做的是**训练归一化的
  数学逆运算** `a_raw = z·std + mean` (+clip 到 env 动作范围)。**这不是标定**, 与"新增映射逻辑"
  必须分开表述 (用户会追问"你是不是又加了一层映射")。
- 归一化统计从**训练用的同一个数据集**算 (`h5` action 列, ddof=1), 落成 json 供推理侧读 —
  不许手写数字。

**加载微调 ckpt**: `swm.wm.utils.load_pretrained('<dir>/weights_epoch_N.pt')` 传**文件**;
传目录 → `ValueError: Ambiguous checkpoint: multiple .pt files in <dir>`。
子进程桥侧: `INTACT_RUNTIME=root` + `INTACT_POLICY=<dir>/weights_epoch_N.pt`。

## 3. 闸门 = "原项目自己的评法"(离线回放), 不是闭环成功率

先做**离线回放**: 数据集真帧 → 模型 → 预测动作 vs **教师动作** (数据集 action 列)。
判据 (硬):
- 模型 xyz MAE 必须**显著小于常数基线** (常数基线 = 永远输出教师均值);
- 预测 std 与教师 std **同量级** (差 10~25× = 塌缩)。

实测两例:
| 版本 | xyz MAE | 常数基线 | 预测 std vs 教师 | 判 |
|---|---|---|---|---|
| v1 (36 集 / 8 epoch, intent 权重 0.1/0.05) | 0.0919 | 0.0860 | 0.0145 vs 0.1723 | ❌ 塌缩到均值 |
| v2 epoch0 (300 集 / 动作头权重 1.0) | 0.1122 | 0.0993 | 0.0074 vs 0.2121 | ❌ 仍塌缩 |

**塌缩根因线索 (先查这两个, 别改接线)**:
1. loss 权重 — `intent.local/goal = 0.1/0.05` 而 `forward = 1.0` → 动作头只分到 ~15% 梯度;
2. 数据量/轮数 — 36 集 / 8 epoch 对 84MB 预训练策略太小。

**"用回归把外部动作映射到我们的控制量"这个口径已判死** (INTACT 实测):
样本外 R² 全局 **0.043**、分阶段条件 **−0.63** (过拟合) → 结论是"该口径不成立",
**不能**据此宣布"模型无用"。

**逐 epoch 自动判闸 (无人值守)**: watcher 循环检测 `weights_epoch_*.pt` 新增 → 自动跑回放闸 →
落 `reports/intact_replay_<tag>.json` + 日志记 `GATED <tag>`; 任何 epoch 过闸就**提前**上闭环,
不必等训完 (本次 66 分钟/epoch × 3 轮, 等满要 3.3h)。

## 4. 直驱 (模型动作直接开机器人) + 取证

- 引擎侧加**默认关闭**的钩子: `_direct_act` 非 None 时该值**就是 env 级动作** (4D: dx,dy,dz,gripper),
  跳过参考换算 (`u/K_ACT`) 与离散维阈值化/重夹逻辑; 默认 None = 既有行为零改变 (这是能安全合并的前提)。
- 中间**不要再塞**控制器/流形/标定 — 用户要的就是"和原生项目一样: 模型出动作 → env.step"。
- 唯一换算是第 2 节的归一化逆运算。
- **录像取证** (用户要"看实际操作结果"): `cv2.VideoWriter(fps=引擎控制频率)` + 每帧 `cv2.putText`
  叠加「阶段 / 模型原始动作 / 实际下发动作 / 模型真推理次数」→ 一眼分辨是不是真模型在开。对照组
  必须**同轮同 seed** 跑参考链, 并用它的**末帧当 goal 帧**。
- CLI 无附件通道: 视频结论必须给**绝对路径** (用户自己打开)。

实测 (INTACT 域内 v1 ckpt, 2 seed): 直驱 0/2 (600 步未完成), 同轮解析链 1/2 —
直驱不成功时先靠回放闸把"模型没学会"和"接线错"分开定罪。

## 5. 大采集 → 训练数据流水线 (防 OOM / 防假数据)

- **十几万帧一次性 `np.concatenate` ≈ 22GB → 被 OOM 杀掉且一帧不落盘** (实测: 采集循环跑完 300 回合
  151,364 帧, 落盘时进程被 kill, 目录里啥都没有)。
  修: **分块落 part npz** (内存闸按累计帧数 ~2 万帧/块) + **流式合并 h5** (h5py 可扩展 dataset,
  逐 part `resize` + 写; 每 part 自包含 `ep_len/ep_offset`, 合并时全局重编号 `ep_idx/step_idx`)。
- **合并工具 `--validate` 抛异常会提前 return → 中间 part 不删** (实测残留 7GB)。验证失败只
  **告警**, 不阻断清理; 官方加载器验证要传**带扩展名的名字** (`<name>.h5`), 传裸名报
  `Cannot resolve '<name>': not a local path or HF repo id`。
- **数据有效性闸**: 每个 part 抽帧算 std, 任一回回合 std ≤5 (黑帧) → 不落盘; 合并后 attrs 记
  `ep_frame_std_min/max` + `done_rate` (采集器 → part meta → 合并聚合, 别丢)。
- **GUI 读取**: `gui-venv311` 无 h5py → 跨 venv 子进程 (`INTACT venv`) 读 `--info` / 取单帧出 PNG,
  另由一个脚本生成 **json 台账** (含回合/帧/动作维/帧std真图校验/大小/用途), GUI 只读 json。
- 采集器**绝不 `close()` 引擎 env** (进程级单例, close 后复用 → 渲染全黑); 黑帧批次按 std 判据整体丢弃。

## 6. 汇报纪律 (老倪口径)

- 只报**本机实测数字** + 对照组同口径数字; 视频给绝对路径; 单轮/单臂结论必须标"疑似/待复验"。
- 训练在跑时报"实际在跑什么 + 下一步时间点", 不夸大幅度; 不要拿别的任务的官方成绩充当我们的成绩。
