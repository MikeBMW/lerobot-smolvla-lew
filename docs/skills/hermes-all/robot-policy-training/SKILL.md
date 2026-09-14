---
name: robot-policy-training
description: 机器人策略训练(BC/RL/蒸馏)与评估管道正确性, 含长轨迹方向反转坑与夹爪头分离。
---

# 机器人策略训练与评估管道 (BC/RL/蒸馏)

## 触发
- peg-insert 等机器人任务策略训练/评估 (ACT/SmolVLA/AWE/MLP)
- 行为克隆训练效果差 / 评估假 0%
- 多阶段长轨迹数据训练

## 核心结论 (2026-08 实测, 诚实记录)

### ① 长轨迹多阶段数据方向反转坑（最重要）
- 300 步轨迹含"接近(朝peg)"+“插入(朝hole)"方向相反的动作段
- 行为克隆回归学**平均动作** → 模型学成"后退/原地不动"（5 个视觉大模型全灭）
- **解法**：
  - 分段数据（`--stop-after-grab`：抓起后保持 30 帧即停，无转移段）
  - 或截断轨迹到"抓起"时刻（保留接近+抓取，方向一致）
- **免疫者**：MLP 蒸馏（39D 坐标→动作直接映射，每步独立决策，不受时序平均化影响）

### ② 数据量差距决定成败（MLP 赢的真正原因）
| | MLP | ACT |
|---|---|---|
| 样本 | 90000（专家蒸馏 300 轨迹）| 3600-4500（12-15 轨迹）|
| 参数 | ~3M | ~65M+ |
| 数据/参数比 | 30:1 充足 | 1:15 严重不足 |
- **大模型缺数据 → 学不会**。先对齐数据量再谈架构对比

### ③ 夹爪头分离 (grip_assist) — 离散决策不回归
- 夹爪只有 -1/0.6 两档（开关），回归学成中间值
- **位置动作用模型学，夹爪用规则触发**（接近 peg <8cm 闭合）——真实机器人就是位置伺服+力控夹爪
- 评估侧 `run_episode(..., grip_assist=True)`；RL 侧同样把夹爪交给规则，只学位置（奖励=距离下降，平滑）

### ④ 45D 目标条件化
- state 加 `[peg-hand, hole-peg]` 相对向量（39+6=45D）——模型每步知道目标在哪
- 这是 MLP 成功的核心，视觉大模型也该喂
- 评估时现场补这 6 维（env obs 39D → 模型 45D）

### ⑤ 无 VAE 决定性（2026-08-08 novae 对照实验）
| 版本 | 数据 | 叠加 | VAE | 结果 |
|---|---|---|---|---|
| overlay2 | 17条纯接近 | ✅ | ✅ | ❌ 不动 |
| big | 68条纯接近 | ✅ | ✅ | ❌ 不动 |
| **novae** | 68条纯接近 | ✅ | ❌ | ✅ 动了(0.066m) |

- **VAE = 训练作弊**：encoder 训练时偷看未来动作生成 latent，模型依赖它；推理时无未来动作 → latent=0 → 模型"不会动"
- `latent += state` 叠加放大了该坑（state 叠到一坨训练有作弊/推理为 0 的不稳定 latent 上）
- **无 VAE 后**：latent 恒 0 → `latent(0)+state` = 干净 state 信号 → 学 state→动作 直映射（像 MLP）
- **有效组合**（按贡献）：无 VAE（决定性）> 结构条件叠加（基础，state 逻辑主线）> 纯接近数据（支撑，方向一致不平均化）
- ACT 训练默认 `use_vae: false`（novae 配置），控制台 ACT 行 VAE 节点标"🚫 无"

## 评估管道正确性清单（假 0% 排查）
1. **逐维归一化**：每个模型 checkpoint 的 preprocessor 是逐维 mean/std（39 值），不是标量广播
2. **SmolVLA 图像 64×64**（siglip_image_size），ACT 128×128
3. **AWE/VLA-Touch 反归一化**：diffusion 输出归一化空间，必须 `act*std+mean` 还原（stats 键 `a_mean/a_std`）
4. **每模型 stats 不同**：`_load_stats(policy_name)` 按模型映射 checkpoint；无 preprocessor 的模型 fallback 数据 stats.json
5. 数据 info.json 与 parquet 不符 → BackwardCompatibilityError/CastError
6. **新模型名必须注册三处**（2026-08-10 触觉版踩坑）：`load_policy` 分支 + `_by_policy` ckpt 映射 + `_load_stats` 数据 stats——漏注册 = `broadcast (39,) (3,)` 假 0%（详见 references/tactile-49d-rl-finetune-20260810.md）

## RL 实战
- 纯 PPO 60 轮 0% 抓起（奖励 -9.9 卡住，稀疏奖励探索不到）
- warm-start 官方专家后仍 0%（-9.9→-5.0）
- **出路 = RL 只学位置 + 夹爪规则**（grip_assist），奖励塑形用距离下降
- **ACT RL 微调（train_act_rl.py，2026-08-10 仿 MLP 改造）同样失败**：39D obs → MLP ActorCritic → PPO 40 iter 奖励 -80~-90 卡住，0/6 抓起。**结论强化：RL 学稀疏插拔奖励是死穴，跟网络结构（ACT 还是 MLP）无关**——继续验证\"BC+RL 都学不会，规则+蒸馏才有效\"

### ⑥ 触觉信号整合进结构条件无提升（2026-08-10 三模型对照，诚实记录）
- **设计**：39D 基础 + 6D 相对向量 + 4D 触觉（3D 关节差分速度×10 + 1D 力=速度范数×25）= **49D 结构条件**；触觉语义=接触时刻力变（接近移动 force↑0.24，接触减速 force↓0.006）
- **训练**：ACT/VLA-Touch/AWE 用 `data/metaworld_peg_tactile2`（49D）容器训练 3000 步全部 EXIT=0 loss 收敛
- **评估**：三模型 49D 触觉版全部 **0/8 抓起，距孔 0.365 与 45D 无触觉版完全相同**
- **结论：加输入信号（触觉）不解决插拔问题**——瓶颈在架构无法泛化毫米级时序决策，不在信号缺失。触觉方向已充分验证，止损勿再重复
- **实现要点**：
  - 数据生成：`gen_metaworld_data.py --rel-vec --tactile`（45+4=49D）
  - 训练脚本（VLA-Touch/AWE）数据加载：`st.shape[1] >= 49` 时直接用 `st[:, 45:49]` 触觉段（**别再用关节差分重新构造**——数据自带与训练同构），否则 fallback 差分
  - 评估管道：新 policy 名（`act_tactile`/`vla_touch_tactile`/`awe_zflow_tactile`）必须注册到 `eval_insert.py` 的 `_by_policy`（load_policy 分支 + _load_stats 分支；触觉版 stats 用 `data/metaworld_peg_tactile2/meta/stats.json` 的 49D）——不注册 = `operands could not be broadcast together with shapes (39,) (3,)` 假 0%
  - 49D 数据集坑见 `lerobot-dataset-engineering` #26（episodes 重编号/info shape/stats 必须全 49D 同步）

### ⑦ 双脑+状态机 = 完整插拔突破（2026-08-10 重大突破, 抓起8/8 插入7/8）🎉
**这是实测出的"离散时序决策"解法**——之前 5 个视觉大模型 BC 全 0/8、PPO/RL 全 0/6、层级策略/条件时序/抓取点专项全 0/8，唯有拆成"动作生成 + 时机判断 + 状态机编排"三件套突破：
- **左脑 MLP**：39D obs → 4D 连续动作（3 层 512）
- **右脑世界模型**：obs+act → next obs 预测 + **contact 概率**（"该抓了吗"判断, acc 1.00）
- **状态机**：接近→抓取→抬起→转移→插入→完成（125 帧）
- **结果**：抓起 **8/8**（超官方专家 7/8）、插入 **7/8**（与专家持平）——首个学习架构完整解决插拔

**关键调优点（每个都是踩坑换来的）**：
1. **MLP 偏置接近**（`act*0.3 + (peg-hand)*2.0`）> 纯解析接近（5/8 vs 0/8）——左脑"精细调整"是灵魂，纯解析太粗暴
2. **抓取触发**：右脑 `contact>0.5` 且 `d_hp<0.06`（钳口贴住）→ 夹持 0.6 + **位置锁定**（`act[:3]*0.1` 防 MLP 推走 peg）
3. **metaworld grab_effort 语义**：**正值=夹持(0.6), 负值=张开(-1.0)**——最初用 -1.0 想闭合，方向反了夹不住
4. **抬起 +8cm**（力 0.8）——+5cm 不够，peg 蹭台面导致转移卡死（d_xy 卡 0.15 不动）
5. **转移容差 5cm**（peg 有导向），别用 2cm 死等
6. **固定 seed42 + 800 epoch** 保证复现——左脑 MLP 训练随机性大，不固定每次重训质量漂移（5/8→0/8 反复横跳的根因）
7. **先专家验证状态机，再换学习模型**：用专家动作跑状态机确认阶段识别正确（8/8），再替换成学习模型出动作——隔离"状态机 bug"和"模型质量问题"

**与 ①-⑥ 结论的关系（修正认知）**："BC+RL 学不会"要改成 **"端到端 BC/RL 学不会，但动作/判断拆分 + 状态机编排可解"**。详细版本演进见 `references/dual-brain-state-machine-20260810.md`

### ⑧ 视频生成: imageio av 编码器坑（2026-08-10）
- `imageio.mimsave` 报 `TypeError: expected bytes, NoneType found`（av 版本不兼容）
- **解法**：帧存 PNG 临时目录（`cv2.imwrite` RGB→BGR）→ `ffmpeg -framerate 30 -i f%05d.png -c:v libx264` 合成 → 再 `transpose=2,transpose=2` 旋转 180°（老倪要求）
- 视频生成 seed 有随机性：评估日志里成功的 seed 也可能录失败——换 seed 重试

## 命令
```bash
# 分段数据生成
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/gen_metaworld_data.py --eps 15 --steps 300 --task peg-insert-side-v3 --out data/metaworld_peg_seg --stop-after-grab --rel-vec

# 评估 (带夹爪辅助 + 模型专属 stats)
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/eval_insert.py

# RL + 夹爪规则
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/train_peg_rl.py
```

## 参考
- `references/yolo-perception-eval.md` — YOLO 感知链 + 评估管道修复细节
- `references/tactile-49d-rl-finetune-20260810.md` — 触觉 49D 整合（无提升结论）+ ACT RL 微调 GAE 坑 + 数据集修复链
- `references/dual-brain-state-machine-20260810.md` — 双脑+状态机完整插拔突破（版本演进/调优点/metaworld 物理细节/训练配方）

## 🧩 几何条件节点连线（simulink 画布, 2026-08-08）
- 老倪架构: 坐标是逻辑主线, 图像是背景 — **state 叠加进 latent, 不混进 token 序列**
- ACT 代码实现: `latent_embed = encoder_latent_input_proj(latent) + encoder_robot_state_input_proj(state)`（加号叠加, 非 concat）; state 不再占独立 token → `n_1d_tokens = 1`（原 2: latent+state）
- 画布连线: `StateAdapter --(state39D)--> 🧩结构条件 --(latent+几何)--> 各模型 state 输入`（5 模型行全部接入）
- 节点注册三处: `node_logic.py` 的 `_reg("coord_overlay", ...)` + `simulink_module.py` 的 NODE_TYPES 颜色 + 默认布局行。**双击可改 gate/state_dim**（默认 gate=0.5, 39D）
- **新节点须注册 node_logic（老倪铁律）**; `_set_coord_overlay_ctx` 框架动作用 `getattr(module, fn, None)` 容错（module 未实现不崩）
- **注意**: 几何条件节点在画布上存在 ≠ 训练代码用了它——**画布是拓扑展示, 训练走 config**。改架构要在 `src/lerobot/policies/<model>/modeling_*.py` 里改 forward, 画布连线只做可视化同步
