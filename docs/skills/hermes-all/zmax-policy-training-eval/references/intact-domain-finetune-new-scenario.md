# INTACT 迁到新场景 (只换数据) — 2026-09-13 光模块插拔 v3/v4 实测

老倪口径（红线）: **"除了新生成的数据，其它任何代码、接口都不动，只是用新数据"**。
这条等于: 只新增 `config/train/data/<task>.yaml` + `config/train/intact_goal_<task>.yaml`
（既有 train.py / eval.py / 模型代码一行不改），数据用**既有**工具链生成。

## 0. 资产地图 (开始前先认清)
| 环节 | 路径 | 说明 |
|---|---|---|
| 训练入口 | `INTACT-JEPA/train.py` `@hydra.main(config_path="./config/train")` | 必须**仓库根**执行 |
| 数据契约 | `config/train/data/<x>.yaml` | `keys_to_load/cache = pixels/action/observation`; `frameskip` → action_dim = frameskip × 单帧维 |
| 数据采集 | `lerobot-smolvla-lew/tools/intact_domain_dataset.py` 或自写 v3 采集器 | 用引擎 `RealStateSpaceSim` 的 `_frame_sink(sim, act, o)` 逐帧钩子 |
| npz→h5 | `tools/intact_parts_to_h5.py` (INTACT venv, 有 h5py) | 分 part 落盘防 OOM, 转完自动删 part |
| 判闸 | `tools/intact_replay_check.py` | 数据集真帧→模型→预测动作 vs 教师动作 + **常数基线** + 预测std |
| 闭环直驱 | `tools/intact_direct_rollout.py` | 模型动作直接 `env.step` (`install_direct_act`), 带 `--video-dir` 录"解析链对照 + 模型直驱"两段 mp4 |
| 跨 venv worker | `tools/intact_worker.py` | GUI/判闸都通过它跑模型 (`INTACT_POLICY` / `INTACT_RUNTIME`) |

## 1. 四个必踩的坑 (每条都花过时间)
1. **data 名必须带 `.h5`** — train.py → `swm.data.load_dataset → _resolve_dataset`，按字面文件名在
   `<LOCAL_DATASET_DIR>/datasets/` 找；写成不带扩展名报
   `FileNotFoundError: Cannot resolve 'foo': not a local path or HF repo id`。
   而**直接** `swm.data.HDF5Dataset("foo", ...)` 会自己补 `.h5`（写 "foo.h5" 变 "foo.h5.h5"）——
   两条路径口径不同, 别互相套用。
2. **runtime 必须匹配 checkpoint**: 根 runtime 训的 ckpt 用 `module.IntentActionActor`；论文权重用
   `paper_runtime/module.py` 的 `InverseTransitionActor`（两处同名 `module.py`，`sys.path[0]` 决定用哪个）。
   worker 默认走 paper → 加载根 ckpt 报
   `InstantiationException: Error locating target 'module.IntentActionActor'`。
   修: `INTACT_RUNTIME=root INTACT_POLICY=<ckpt目录>/weights_epoch_N.pt`。
3. **8GB 显存 batch 32 必 OOM**（ViT SDPA 峰值 7.6GiB / 显卡 7.62GiB）→ `batch_size: 16`。
   写到 config 注释里, 别让下一个人重踩。
4. **判闸看"预测std/教师std"比值, 不能只看 MAE** — 常数基线(教师均值)天然很强，MAE 不输就说明
   模型只是输出均值。v3 实测: 模型 xyz MAE 0.0203 **输给** 常数 0.0189, 预测std 0.0026 vs 教师 0.055
   (≈1/21) = 塌缩。方向一致率 99~100% 是"均值方向对"的假象, 不代表学会。

## 2. 本域最贵的发现: env 级动作可能是"退化列"
- v3 动作列 = `env.step` 收到的 4D 动作。插入段实测 **回合内 std**: dx 0.053（有斜坡）/ dy 0.001 /
  dz 0.009 / **gripper 0.000（恒 0.6）** → 逐帧回归任务退化, 模型最优解就是输出均值。
- 闭环直驱后果（Step1 口径, 3 seed）: 模型输出≈常量 → 沿 -x 恒速推进 → **过冲 658.8 / 289.2 / — mm**,
  `done=False`, 同轮解析链对照 65.1mm `done=True`。即"链路通、模型不通"。
- 同一引擎里**真正有信息量**的信号（都挂在 tr 上, 采集时读 `sim._u_vec` 即可, 不改引擎代码）:
  `u_sat_vec`/`u_exec_vec`/`u_fuse_vec` 逐帧std ≈ [0.082, 0.072, 0.057, 0.474]；`u_fb_vec` 只有 ~0.001。
- **建新场景数据集前先算"动作列在窗口内的每维 std"**：某维在整个相位内恒定 ⇒ 该列对该相位无监督价值。
  两条出路: ①换记录列（u/解析伺服指令/waypoint）②换覆盖口径（见下）。

## 3. 窗口切法 (治"模型没见过怎么走到插入前")
- v3: 只取"结束于插入完成附近"的 50 步窗口（4 条/回合, 结束点回退 0/15/30/45）→ 全相位缺失。
- v4: `--coverage all` 按 stride 50 均匀铺满整回合 → 接近/对位/下降/抓取/抬起/转移/插入全相位都有,
  且动作列换 `sim._u_vec`。400 seed → 355 成功 / 45 跳过 → 2954 窗口 / 147,700 帧。
- **成功才留**（`--success-only 1`）: 与官方 `*_single_expert` 语义一致（专家数据）。
- **采集必须 `cap="l4"`**（引擎自主恢复档: 失败回退/重抓不放弃）: 实测不带 cap 时 done_rate 只有 0.36,
  失败回合的窗口停在「接近/对位」= 没价值; 带 cap 后 355/400 = 89%。
- 速率参考（4060 笔记本）: insert 模式 ~3.3-5.5 s/回合（cap=l4, ≤1000 步）; 400 回合采集 ~37 分钟;
  npz→h5 转换 ~4 分钟 (147k 帧 / 6.9GB)。

## 4. 自查清单 (交付前)
- [ ] h5 每回合帧 std > 5（真图）; `ep_len` 是否整齐; action/pixels dtype+shape
- [ ] 判闸: 预测std/教师std 比值 + MAE vs 常数基线（两个都要报, 别只报 MAE）
- [ ] 闭环: `done` 数 + 插入深度（mm）+ 与解析链对照同轮跑（同口径）
- [ ] 视频: `--video-dir` 产出的"解析链对照 / 模型直驱"两段都留, 失败的就如实标失败
- [ ] 磁盘: 红线 300G; 删数据集前先把"怎么再造回来"的命令写进 released_archives.log
