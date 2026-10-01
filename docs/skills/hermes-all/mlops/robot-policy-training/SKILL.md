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

## 训练通道静默失败清单（“跑了但没真训”——症状是没提升，不是报错）
适配器/子模块微调最容易掉进去的一类坑：**训练正常跑完、loss 正常降、产物看不出异常，但那个模块一个参数都没动。**
四条都要在开跑前装闸拦住。

1. **自研 LoRA 注入的冻结语义会误杀行为模块**：`lora_inject` 是“先 `requires_grad_(False)` 全模型，再只解冻适配器”
   ⇒ **目标模块名没覆盖到的模块直接被冻死**。若那正是**决定行为的那半**（动作头 / 世界模型 / predictor），
   它既冻又没适配器 ⇒ 一个参数都训不到。目标列表按“**在损失图里** + **能改变行为**”两条一起定。
2. **注进去前先确认模块真被调用**：`grep -n "<模块属性名>" <policy>/modeling_*.py` —— forward 里一次都不出现的
   模块（例如 VLM 里挂着、但该策略走自己动作头的那个专家）注入进去只是死重量，适配器永远零梯度。
3. **梯度到齐闸：钩 `backward`，不能钩 `Optimizer.step`**：accelerate 把 optimizer 包成 `AcceleratedOptimizer`
   （自带 `step()`）⇒ patch 基类 `step()` **静默不被调用**，以为有闸其实一次没跑。
   闸要分开报 `grad is None`（根本不在损失图里，如模块没被调用/被 `no_grad` 绕开）与 `grad==0`
   （在图里但无学习信号），二者修法不同；并**打印“哪些参数分组真拿到了非零梯度”**（按模块族聚合）——
   选目标模块靠这份名单，不许猜；打印块放失败分支**之前**，否则 raise 一发生它永远不执行。装完要**故意漏一个模块验它会拦**。
4. **损失侧两个静默坑**（适配器没梯度的上游原因，先查损失再查模块）：
   - `total_loss = out.get("action_loss", 0) + out.get("lew_loss", 0)`：上游键名一变或某分支不返回，动作损失
     **静默归零**只剩另一项在训。定式：损失项**缺失即 raise** 并打出**上游真实键集合**，绝不给损失项兜底；
     同文件里 `if not has_X: return {"loss": tensor(0.0)}` 这类早退分支，训练态必须 raise。
   - 序列回归损失（`F.l1_loss(pred, target)`）形状不等时**广播成功、只给一条 warning** ⇒ 拿两段不相干的序列算 L1
     ⇒ 损失“看起来正常”却毫无意义。定式：回归损失前**显式断言形状相等**，不等就 raise 并印真实形状；
     常见根因是两个输入**窗口长度不一致**（视频窗 T ≠ 动作窗 T）⇒ 去数据/配置侧对齐窗口，不是在上游切片糊。
     对齐配方（实测）：窗口开关是**策略自己的** `num_video_frames`(模型侧) + `n_obs_steps`(观测帧数)；
     `dataset.delta_timestamps` **不是 DatasetConfig 的合法字段**（写进 dataset 段直接 DecodingError）。
     ⚠️ 改窗口会撞世界模型的位置编码：`predictor.pos_embedding` 形状是 `[1, num_frames, dim]`（按帧数学出来的参数）
     ⇒ 直接改会 `size mismatch` 加载失败。定式：**复制一份 ckpt**，把 `pos_embedding` 重建为目标帧数（小方差初始化），
     生成器按窗口自动选这份 warm-start（**不改原始 ckpt**），并接受该参数**必须重训**。
     验收：对齐后那条广播 warning **消失**（pred 步数 == target 步数），且世界模型项量级应明显变大
     —— 只比 1 步时该项极小（≈1e-3 量级）= 等于没训。
     找不到目标键时的通用手段：查该字段的**定义处**（`grep -n <字段名>` 在策略包里）+ 用**逐参数 dump** 定故障，别靠命名猜。

5. **把适配器折回基座可能等于把它抹掉**（同样是“没提升”的假象）：折叠 = `W + s·B@A` 落回基座 dtype，比量级：
   `折叠噪声/信号 ≈ (基座 eps)/(‖ΔW‖/‖W‖)`；bf16 eps≈3.9e-3，fp16≈9.8e-4。实训 ‖ΔW‖/‖W‖ 中位 **2.17e-4**
   ⇒ 噪声约为信号的 18 倍 ⇒ 折进 bf16 把贡献**整片抹掉且不报错**。
   定式：折叠前先量 `‖ΔW‖/‖W‖` 中位与最大；**< 基座 eps 就不要折** —— 保持适配器路径加载，
   或升到 fp32/fp16 折叠（代价是体积/显存）。反之，**不合并直接判闸也不对**：标准加载器不认适配器包装键，
   拿到的是基座结果 ⇒ 两边都能造出“无提升”假象，必须按量化账决定走哪条。

**判据口径（防闸门自己产噪声）**：只对**决定行为的模块**严格（缺一个就停），其余零梯度项**告警不拦** ——
强求它们等于把“没走到≠坏”也判成失败，真问题会被噪声淹没；被放行的死区要**在日志里逐项登记**（点名+原因），
不许静默排除。健康长相：有梯度的分组覆盖 动作头主干/时间步编码/输出投影/编解码器/世界模型。

**别把“首步零梯度”当成故障（重要，容易据此发明不存在的 bug）**：LoRA 的 B 是零初始化的 ⇒ `dL/dA=(∂L/∂W')·B·x=0`,
A 要到**第 2 步**才有信号 ⇒ 第 1 次 backward 上每个模块都**必然**同时有一条非零(B)与一条零(A)。
- 硬失败只有一种: **`grad is None`**（模块根本不在损失图里，如从未被 forward 调用的模块）。
- **`grad==0` 的统计必须放到 ≥2 步之后**；否则闸门会把正常报成坏，并污染由它推出的全部结论。
- 实测教训: 曾据此断定“时间步条件被 detach ⇒ adaLN 调制链拿不到梯度”，逐参数 dump 一查，
  `timestep_embedder.linear_1/2` 与 `norm1.linear` **全都有梯度** —— 真因是首步 `lora_A` 必然为零。
  选目标模块/判故障一律靠**逐参数 dump**（打印每个 lora 键的 NONE/ZERO/OK，按模块族聚合），不靠名字推。
- **免基准的“真训过”证明**: B 零初始化 ⇒ 训练前所有 `lora_B ≡ 0` ⇒ **任取一条 `lora_B` 非零即证该层被梯度更新过**。
  按模块族报“非零 `lora_B` 条数/总条数 + 最大 |B|”即可产出报告，不依赖 init 快照
  （拿 init 当基准易翻车: init 文件可能只存了几个键 ⇒ 基准不成立；也别把“找不到初值”记成“已移动”）。

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
