# 本域微调 (光模块) 与五层体检 — 2026-09-21 一手

承接 SKILL.md 第 3 节 (数据格式)。这里记: **HDF5 插件的真实修法**、**解释器映射**(跑错 venv 会得到假失败)、
**各层体检判据**、以及**本域微调的数据/配置/权重现状**(下次接着训练直接用)。

## A. HDF5 插件: 只 `import hdf5plugin` 不够 (7.1.0 实测)

```bash
pip install h5py hdf5plugin          # 装进 lerobot-venv
```
`hdf5plugin.PLUGIN_PATH` 在 **7.1.0 返回空字符串** ⇒ 只 import 不设环境变量, h5py 仍去找默认
`/usr/local/lib/plugin` → 报
`OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin)...`
或 `can't find plugin. Check either HDF5_VOL_CONNECT...`

正解 (显式指向包自带插件目录):
```bash
export HDF5_PLUGIN_PATH=$(python -c "import hdf5plugin,os;print(os.path.dirname(hdf5plugin.__file__))")/plugins
# 实测: <venv>/lib/python3.12/site-packages/hdf5plugin/plugins
```
效果: `tools/verify_l4_intact_zeroseach.py`(F02) 由 ❌ 直接转 ✅ —— **缺依赖 ≠ 层有问题, 先补依赖再判层**。

## B. 解释器映射 (跑错 venv = 假失败)

| 脚本 | 用哪个解释器 | 跑错时的报错特征 |
|---|---|---|
| `tools/verify_l3_action.py` (F01) | `~/lerobot-venv/bin/python` | 缺 torch/h5py |
| `tools/verify_l4_intact_zeroseach.py` (F02) | lerobot-venv + `HDF5_PLUGIN_PATH` | `ModuleNotFoundError: h5py` → 之后 `OSError ... plugin` |
| `tools/verify_capability_stack.py` (F19) | lerobot-venv | — |
| `tools/verify_engine_live_frame.py` | **gui-venv311** (PyQt5/mujoco) | `ModuleNotFoundError: No module named 'PyQt5'` |
| `tools/ss_yolo_on_real.py` · `tools/local_cam_feed.py` · `scene_vlm.py`(本地 VLM worker) | **gui-venv311** | ultralytics / cv2 只在 gui-venv311 |
| `tools/vlm_guided_crop.py` | gui-venv311 | 同上 |

- `lerobot-venv` 有 pip; **`gui-venv311` 没有 pip 可执行文件** ⇒ 用 `gui-venv311/bin/python -m pip install ...`
- 引擎/mujoco 类脚本收尾常打 `TypeError: 'NoneType' object is not callable`(GLContext `__del__`) —— **收尾噪音**,
  不代表判据失败; 判据看脚本自己打印的 ✅/❌ 汇总行。
- 长脚本用后台 + notify (F02 约数分钟; 光模块链 ~400s/2 seed 会超过前台 600s 上限)。

## C. 五层体检判据 (跑完看哪一行)

- **F01 (L3 单步控制量)**: `u` 存在、非零、`|u|≤界` (不是假零)
- **F02 (L4 INTACT 零搜索)**: `trained=True` · `policy=direct` · 动作块非零 `shape=(horizon, action_dim)` ·
  `cand_seq=0`(零搜索) · `fwd==horizon` · `intent_norm≠0`
- **F19 (能力栈逐层收缩)**: 越界 100% 被夹紧 · 界内不被改 · 不放大 (单调)
- **L4 光模块链** `tools/verify_l4_optical_chain.py`: 输出**诚实口径**——"解析链对照" = 引擎本任务可达性,
  "模型直驱" = 本域微调真水平(不做任何加工)。2026-09-21 实测: 解析链 1/2=50%, **模型直驱 0/2=0%**
  (插入 417mm / 269mm 过冲)。
- 本域 v6 配置里写明的**判闸口径**: `xyz MAE < 常数基线` **且** `预测 std ≥ 教师 50%`;
  配置注释记载 v3/v4/v5 的病 = **预测 std 只剩教师 7~22%**(塌到均值) ⇒ 这是"模型直驱 0%"的根因方向。

## D. 本域微调现状 (2026-09-22 更新, 下次接着训练直接用)

- **数据**: `$HOME/stable-wm-cache/datasets/optical_insert_v6_disturb.h5` (**4.1 GB · 1743 回合 · 87150 帧**,
  新造抗干扰, `--disturb mixed` 三档真注入, success-only 专家口径; 帧 std 55.5~56.1 = 真图)
  · 上一代 `optical_insert_v5_disturb.h5` (7.37 GB / 2982 回合 / 149100 帧) 仍在位, 可做跨集对照
  · **skill_ctx 24 维有效性可核验**(别只看列数): stage one-hot 12/13 维非恒定且行和=1 · L2 w8 7/8 维非恒定 ·
    d_perp 0~0.26 · grip {-1,0,1}。恒定=通道摆设, 判闸就没意义
- **数据配置**: `config/train/data/zmax_v{4,5,6}.yaml` —— 新建一个数据集务必同步加同名 yaml, `name:` **必须带 `.h5`**
- **配置**: `config/train/intact_goal_optical_insert_v{3,4,5,6}.yaml`; v6 = skill 通道
  (`intent_actor.skill_dim: 24`, `init_zero_skill_branch: true` 暖启动逐位等价)
- **采集→合并→统计 (三件套)**:
  1. 采集 `gui-venv311/bin/python tools/intact_insert_dataset_v5.py --seeds 0-127 --mode full --l2-skill-ctx 1 --disturb mixed --success-only 1 --out-name <name>`
     (实测 ~7s/条 平均, 慢档单条可到 425s; 每 20 条打一次点, **日志里的"用时"是累计值不是单条耗时**)
  2. 合并 `/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py --parts 'reports/<name>_part*.npz' --out-name <name> --dest <cache>/datasets --skill-ctx **--keep-parts**`
  3. 统计 `tools/action_stats_from_h5.py --h5 ... --out reports/<name>_action_stats.json` (闭环反归一化必须同一份)
  · 一键串起: `bash tools/l4_v6_post_collect.sh`
- **⚠️ 坑 1 (会连锁崩两次)**: 转换器**默认删中间 npz**。删掉某个 part 后, 采集器收尾会
  `np.load(p) for p in parts` 汇总 → `FileNotFoundError: ..._part00.npz` 崩溃(但**episode 数据已全部落盘, 不用重采**)。
  ⇒ 转换永远加 `--keep-parts`; 已删就在合并前重采那一段种子(它们会重新写成 part00)。
- **⚠️ 坑 2**: 采集器/转换器的 part 索引按**本次运行**从 0 起 —— 用同一个 `--out-name` 二次采集会**覆盖** part00。补数据要用新名字 + `--parts 'reports/<name>*part*.npz'`
- **训练接力链**: `bash tools/v6_newdata_chain.sh <轮数> <起始轮> [init权重]` (支持自动续训)
  · 口径: **1 epoch × 1000 步/轮 ≈ 8.5 分钟** (实测 2.0 it/s), 从上一轮权重续 + `init_zero_skill_branch=false`
  · 实测 5 轮: local_mae 0.0340→0.0310 · goal_mae 0.0350→0.0320 · action_loss -3.794→-3.834 单调改善,
    `skill_ctx_usage` 恒 1.000
- **验收 (判闸)**: `bash tools/l4_v6_accept.sh` 或直接
  `INTACT_POLICY=<ckpt目录名>/weights_epoch_1.pt gui-venv311/bin/python tools/intact_replay_check_v4.py --h5 <新h5> --stats reports/<name>_action_stats.json --skill on|zero --clips 240 --repeats 3`
  · **同口径铁律**: 判"微调有没有提升"必须**同一份数据只换权重** (老=在役权重), 不能拿"老权重×老数据"比"新权重×新数据"
  · 2026-09-22 实测: 新数据上 老 v6r11 0.0343 → 新 v6d5 **0.0282 (+17.8%)**;
    同帧同权重切通道 on 0.0282 vs zero 0.1075 (**Δ-0.0793, 误差 3.8×**) → 记忆通道确实在用
  · 诚实副作用: 老 v5 数据上哨兵 on-MAE 0.0289→0.0312 (轻微域漂移) —— 报数要带上
- **⚠️ 坑 3 (官方 preflight 会挂在这)**: `tests/test_intact_objective.py` 的 `CountingActor` 桩签名落后于
  `module.py::IntentActionActor.forward(z, intent, prev_act_emb, skill=None)` → 7 个测试 TypeError。
  加 `skill=None` 透传即可 (已修, 27/27 通过)。preflight 另两项 FAIL 属预期: paper_runtime 被本域改过(指纹) + pusht 数据不在盘
- **官方 paper eval 的边界**: harness **不产生 skill_ctx**, 而 v6 权重是按带记忆通道训练的 ⇒ 跑出来的数不代表
  部署行为(可能被误读成"回退")。要么补一个"喂零 skill"的对照臂, 要么以训练同源判闸为准
- **在役权重**: `checkpoints/intact_l4_current/weights.pt → intact_goal_optical_insert_v6r11_s3072/weights_epoch_2.pt`;
  本轮新产物 `intact_goal_optical_insert_v6d1..d5_s3072/weights_epoch_1.pt` (84 MB/个), **尚未替换在役软链**
- **加载权重口径**: 动作维对齐按模型实测(如 4→8)、`horizon=8`、`策略=direct(零搜索)`;
  数据集名**必须带 `.h5`**(按字面名在 `<LOCAL_DATASET_DIR>/datasets` 下找)。
- **判闸哨兵在后台自动跑**: `~/.hermes/scripts/v6_judge_watch.py`(cron) 认最新 ckpt 目录, 用**老 v5 数据** clips=200×3
  出 on/zero 两臂 → 新权重上线后想知"有没有伤到老域", 直接看它的逐轮 json (`reports/intact_v4_<policy>_epoch1_skill_*.json`)

## E. 门闸逐轴归因: dy 是"数据配方"问题, 不是训练/接线问题 (2026-09-22 实测)

`L2 收口闸` 按**逐轴** |corr|≥0.5 判 ⇒ 必须逐轴看, 只看 dx 会把 dy≈0 的模型误判成"达标"。

- 判闸工具已**逐轴化**: `intact_replay_check_v4.py` 现在输出 `p_dx/p_dy/p_dz/p_grip + min|xyz|`, 并把
  `meta.device` 记进 json。
- **无 GPU 必须自动回退**: 官方加载路径 `swm.wm.utils.load_pretrained()` 硬要 CUDA, 没 GPU 时报
  `RuntimeError: No CUDA GPUs are available` 整条判闸失败 (2026-09-22 实况)。现已内置回退:
  先 `⚠️` 打印根因再 `--device cpu` 重试 (不静默降级)。60 clips on CPU ≈ 2 分钟。
- 实测 (在役 v6r11, teacher-forced 同源回放, v5 数据): **p_dx 0.56~0.84 · p_dz 0.61~0.91 · p_grip 0.63~0.96 ·
  p_dy −0.16~+0.31 (多数 |·|<0.16)** ⇒ 离线 dx/dz/grip 都过 0.5, **唯独 dy 不过** ⇒ 门闸必然 veto
  (v6d1~d5 逐轮 json 同形: on 0.74~0.78 / zero 0.10~0.16 —— 那是 **dx** 的值, dy 一直没人看)。
- 归因工具 `tools/ana_l4_dy.py` (只读 h5, v5/v6 两份数据结论一致):

  | 轴 | 活跃帧 \|a\|>0.05 | 最优单维观测 corr / R² | 判读 |
  |---|---|---|---|
  | dx | 48~49% | 0.32~0.33 / 0.10~0.11 | 有信息可学 |
  | **dy** | **12%** | **0.15~0.18 / 0.02~0.03** | **观测里几乎没有该轴的信息** |
  | dz | 14~16% | 0.45~0.46 / 0.20~0.21 | 有信息可学 |
  | grip | 83~84% | — | 阶段驱动, 好学 |

  ⇒ 数据里**横向纠偏行为接近缺失**, 老师 dy 本身≈噪声 ⇒ 任何模型都学不出 ⇒ **不是接线/口径/训不够**。
- 修法 = **改数据配方**(不是加轮次): episode 生成器加**仓内可达的横向错位** (模块/槽 y ±5~10mm) 或加大 yaw 扰动,
  让对位段必须靠 dy 侧向纠偏; 改完**先用上面两个工具验收 `p_dy ≥ 0.5`**, 再谈续训。
  真机产线两槽 y 间距 50mm (`taught_points`: slot1 y=0.5026 / slot2 y=0.4524) —— 槽间转移天然带 dy, 是更干净的数据源。
- ⚠️ 三轴**一阶自相关 0.95~0.98** ⇒ 判闸的高 corr 有相当部分来自**慢变趋势**; 离线 0.9 的 dz 到闭环 live 只剩 −0.35,
  就是慢趋势在自回归里被抖掉。**别把单帧 corr 当"能闭环"的充分证据。**
- 本轮训练进度 (2026-09-22 上午): v6d6/d7/d8/d9 各 84 MB 依次完成 (1ep×1000 步, 2.0 it/s),
  **在役软链 `intact_l4_current` 仍未替换**; 下一步仍是"先改数据配方拉 p_dy, 再续训"。
