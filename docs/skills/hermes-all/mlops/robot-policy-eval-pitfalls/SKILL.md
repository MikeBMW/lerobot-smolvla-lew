---
name: robot-policy-eval-pitfalls
description: 机器人策略训练/评估管道坑, 长轨迹平均化, 逐维stats, 图像尺寸, 反归一化, 坐标叠加架构。
---

# 机器人策略训练/评估管道坑 (Z-MAX peg-insert 实测 2026-08-08)

## 触发
- 行为克隆模型 (ACT/SmolVLA/AWE/VLA-Touch) 训练后评估 0% 抓取
- 训练出"后退/不动"行为, 怀疑数据或评估管道问题
- 模型输入 state 维度升级 (39D→45D)

## ① 长轨迹数据平均化陷阱 (最重要)
**症状**: 300 步完整轨迹 (接近→抓取→插入) 训练后, 模型学成"后退/原地不动"
**根因**: 轨迹内"接近(朝peg)"和"插入(朝hole)"方向相反 → 行为克隆回归学到**平均动作≈0**
**验证**: 打印数据动作均值, 若接近 0 且前半/后半方向相反 = 命中
**解法**:
- 分段数据: `--stop-after-grab` 抓起后 30 帧即停 (锁存: 抓起过就持续累计, 不回落)
- 目标条件化: state 加 6D 相对向量 `rel_vec = concat(peg-hand, hole-peg)` (39D→45D)
- **MLP 蒸馏免疫**: 39D 纯坐标直接映射, 每步独立决策, 不受时序平均化影响
- **规律: 纯坐标(39D)→能学会插拔; 图像+坐标→学不会** (单目照片给不了毫米级 3D)

## ② 评估管道 4 大坑 (全部导致假 0% 抓取)
1. **归一化逐维且按模型加载**: 每模型 checkpoint preprocessor 不同
   - `_load_stats(policy_hint)` 按模型名选候选; VLA-Touch/AWE 无 preprocessor → 从数据 stats.json 读
2. **图像尺寸按模型**: SmolVLA=64x64 (siglip_image_size), ACT=128x128
   - 喂错尺寸 → 视觉编码全错 → 输出乱
3. **diffusion 模型必须反归一化**: AWE/VLA-Touch 输出归一化空间, `act = act*a_std + a_mean`
   - `_cond` 分支和 else 分支**都要**反归一化
4. **45D 模型评估补向量**: st_raw[:39] 后补 `rel_vec`; 数据 info.json features shape 同步改 45

## ③ 坐标叠加架构 (老倪架构修正 2026-08-08)
**原则**: 坐标是逻辑主线, 图像是背景 — **叠加而非混合**
- ACT modeling_act.py: `latent_embed = encoder_latent_input_proj(latent) + encoder_robot_state_input_proj(state)`
- state 不再占独立 token (n_1d_tokens 减 1), 图像仍作背景 token
- 注意: VAE encoder 的 robot_state 保持不变 (训练辅助)
- **VAE 坑 (2026-08-08 实测)**: `use_vae=true` 训练时 latent 来自 VAE encoder, 推理时 latent=0 (zeros) — 叠加 state 后**放大训练/推理不一致 → 模型完全不动** (输出恒定小动作)
  - **解法: `use_vae: false`** → 纯 transformer 回归, latent 一致 → 模型从"原地不动"变"大幅接近" (0.247→0.066m 实测)
  - 若叠加架构 + VAE 训完不动, 先关 VAE 重训再排查数据

## ③b 截断数据元数据同步 (LeRobotDataset 加载三件套)
`--stop-after-grab` 截断生成后, 若 `LeRobotDataset` 报 IndexError/KeyError/CastError, 三处必须同步实际帧数:
1. **info.json**: `total_frames` / `total_episodes` / `splits={"train": "0:{n}"}` / `features.observation.state.shape=[45]`
2. **episodes parquet** (meta/episodes/chunk-000/file-000.parquet) 标准字段 15 列:
   `episode_index, length, videos/observation.image/chunk_index, frame_index, file_index, dataset_from_index, dataset_to_index, from_timestamp, to_timestamp, data/chunk_index, data/file_index, tasks, meta/episodes/chunk_index, meta/episodes/file_index`
   - `dataset_from_index/to_index` 是累计帧区间 (最易漏, 漏了报 Column 'dataset_from_index' doesn't exist)
3. **数据 parquet**: episode_index 重编号 0..n-1 (丢弃轨迹后稀疏索引会越界)
- 修复后 `rm -rf ~/.cache/huggingface/datasets` 清缓存再训练 (旧 splits 缓存会残留 1800 vs 1015)

## ④ 工作流偏好 (老倪)
- 视频**一次发齐** (多个 MEDIA 同行), 不一个一个发; 方向默认旋转 180° (transpose=2,transpose=2)
- 简洁执行, 少说话, 最后干净利落汇报; 不要无限折腾数据生成 (多轮失败即止损换路)
- 数据生成器改完先小规模验证 (2 eps) 再全量

## ⑤ metaworld 评估随机性 (2026-08-10 实测 — 最重要)
**症状**: 同权重 + 同 seed + 同代码, 两次评估结果差异巨大 (抓起 7/8 vs 4/8, 插入 7/8 vs 4/8)
**根因**: `env.reset(seed=...)` 后 `_freeze_rand_vec=True` **仍有物理随机性** — 每次 reset 的初始扰动不同 (夹具/物件位置微扰)
**验证**: 同权重跑 3 次完整 8-seed 评估 → 抓起 5-7/8, 插入 4-6/8 (波动覆盖两端)
**铁律**:
- **单次评估结果不可信** — 7/8 和 4/8 可能是同一分布的两次抽样
- 对比任何改动 (新模型/新状态机/新控制) 必须**同权重 3 次重复评估取波动范围**, 范围重叠 = 无差异
- 逐 seed 对比同样会翻转 (seed6 手写卡抓取、policy 却走到 DONE) — 不是实现差异
- 汇报写**范围** (抓起 6-8/8, 插入 4-6/8) 而非单值

## ⑥ 39D obs 结构 (peg-insert-side-v3)
- **obs[18:21] 不是 peg — 是 hand 的重复** (obs[0:3]==obs[18:21], 39D 结构矛盾)
- obs[36:39] = hole 位置 (对)
- **状态机/控制器要用 env 真值**: `env.data.site_xpos[env.model.site("pegGrasp").id]` / `site("hole").id` / `site("endEffector").id`
- 标准 lerobot policy 的 select_action 只收 obs → 需 `set_env(env)` 注入 env 引用 (推理时读真值)
- 状态机常量必须与训练脚本一致 (8 状态: APPROACH,ALIGN,DESCEND,GRASP=0,1,2,3; LIFT,TRANSFER,INSERT,DONE=4,5,6,7 — 曾用 6 状态 DONE=5 导致插入判定错位)

## ⑦ 两套 39D 不通用 — 引擎构造 obs ≠ env 原生 obs (2026-09-10 实锤, v9 闭环 0/7 真根因)
Z-MAX 里存在**两套 39D 观测**, 语义不同, 混用 = 模型输入错位 (单看 val MAE 好也照样崩):
- **env 原生 obs** = `env._get_obs()[:39]` (metaworld, 见 ⑥):
  [0:3]手xyz, [3]gripper, **[4:7]peg 位置**, [7:10]0, [36:39]hole
- **引擎构造 39D (visual39)** = 训练 v9 实际用的:
  `obs[:39] = concat(cur, prev, target)`, 其中
  `cur = [self.x(3), gripper(1), self.v速度(3), _peg_cur(3), _goal_p(3), zeros(3), zeros(2)]` (18)
  `prev` = 上一帧 cur (首帧=cur), `target` = `_stage_target()` (3)
  → **引擎 obs[4:7] 是速度 v, [7:10] 才是 peg**
实测两者仅 **15/39 维相同**, 全维最大差 **1.24m** (均值 0.17m)。
**铁律**: 训练用哪套, 推理必须用哪套。引擎内已备同源通道 `_l3_forward(visual39)` (SS_L3=1) — 优先用它, 别另写外部脚本; 外部脚本必须喂 visual39 而不是 env obs。
**排查**: 同帧打印两套 obs 逐维最大差, 只有 15/39 相同即命中。

## ⑧ SmolVLA-Lew 推理三口径 (接对≠能用, 但接错必不能用)
1. **task 语言**: 必须 = 数据集 `meta/tasks.parquet` 里 task_index=0 的**真实字面串**
   (本仓库实测 **`"metaworld 光模块插拔"`**)。
   ⚠️ **采集脚本源码里写的串 ≠ 落盘 parquet 的串** (本仓库实测就踩了: 源码写 `peg-insert-side-v3`,
   parquet 实际是 `metaworld 光模块插拔`) → **一律动态读 parquet, 禁止硬编码**。
   不传 → modeling 兜底 `"push red block to target"` → VLM 条件分布被换掉。
   实测换串 → 输出最大变化 0.25~0.41 (对比动作 std 0.115~0.46) → 语言通路是活的, 必接。
2. **图像尺寸**: 训练 128×128 (采集时 LANCZOS) → 推理同样 128; 喂 480 原图 = 分布不一致。
3. **归一化**: 用 `make_pre_post_processors(policy_cfg, pretrained_path)` 官方 pipeline
   (STATE=MEAN_STD / **ACTION=MIN_MAX** / VISUAL=IDENTITY)。手动 `*std+mean` = 错口径 + 双重归一化。
   ⚠️ torch 2.6+ `torch.load` 默认 `weights_only=True` → 自产 ckpt(含 numpy 字典) 加载**静默失败**,
   必须 `weights_only=False` (否则 decoder 看似接上、hits=0)。
**口径全对齐后仍全败 = 模型能力不足**, 先查 epoch: 本仓库 v9 = 30000 步 × batch=1 × 12.99万帧 = **0.23 epoch**。

## ⑨ 意图→target decoder 的形态选择 (2026-09-10 实测教训)
- ❌ **MLP 直接替代规则 target** (`_stage_target()`): 全败 0/8。两因:
  (a) 规则 target 是**分段条件函数**(if/else 跳变) → MLP 拟合不了跳变, val MAE 9~11mm;
  (b) 标签若用"下一帧位置 x_{t+1}" → 输出 ≈ 当前位置 → target 误差≈0 → **机械臂原地不动**
      ("段目标点" ≠ "下一帧位置", 语义混淆)
- ❌ **整段动作基跨场景重放**: seed7 从 346→403 帧(更慢) — 标杆绑定摆放, 布局变即失效 (09-09 实锤)
- ✅ 正确形态: **(1) 残差修正** `target = 规则target + decoder(小量, 裁剪)`, 基线=规则 → 不回退;
  **(2) 分段** — 只在 接近/对位/下降/转移 用学习目标, **插入(毫米级)恒走解析伺服**。
- 接入点: 引擎 `target = self._stage_target()` 之后 (⚡前馈加速器之前), L2 三件套一行不动。
- 特征坑: 引擎 obs 的 [4:7] 是**速度** → 采集特征必须用 `tr["peg"]`(=env o[4:7]) 与推理侧 `_peg_cur` 同源;
  孔位置特征用 `geom["goal"]`(=site('goal')), 别用 `_hole_p()`(=site('hole'), 差一个孔深偏移)。

## ⑩ SmolVLA-Lew 训练侧: 速度/显存/续训 (2026-09-10, 8GB RTX4060 实测)
- **变长指令批处理 (batch>1 的前提)**: 逐样本调 processor 得到的 `input_ids` 长度随指令文本变化,
  直接 `torch.cat` 崩 `Sizes of tensors must match: Expected 1145 but got 1142`
  → **这就是原实现只能 batch=1 的真因**。修法: 右 pad 到批内最大长度 + attention_mask
  (causal 注意力下 pad 在末尾, 不污染有效 token; batch=1 零开销)。
- **显存真凶不是参数量, 是图像 token**: 64×64 源图被 processor 放大到 512×512 → 切 **17 patch
  → 1141 token/样本**;乘上 batch 与 `repeated_diffusion_steps(=4)` → 3.6 万 token/步。
  · `repeated_diffusion_steps=4` 会把 batch 复制 4 份 → **有效 batch = batch_size × 4**
  · 实测: batch16 OOM(已用 6.07GiB 还要 1.59GiB); batch8 = 5.5~6.3GiB, **4.5 s/step**
  · 8GB 卡训 500M VLM 的速度上限 ≈ 4.5 s/step → 8000 步 ≈ 10 小时
- **降 token 的捷径走不通**: `max_image_size={'longest_edge':N}` 确实能把 1141→347(1024)→81(2048) token,
  但 SmolVLM 内部报 `At least one sample has <image> tokens not divisible by patch_size` → 放弃, 维持默认。
- **AMP 无效**: `use_amp=True` 在本实现上 4.93→4.5 s/step(几乎没变)。
- **续训必须重置 lr schedule**: d1 从 30500 续训, 而 scheduler 只有 31000 步
  → cosine 已到尾, 实际 lr ≈ 2.5e-6 (峰值 1e-4 的 1/40) → **白跑 1h40m**。
  续训时按新步数重设 warmup/decay, 并且 output_dir 必须不存在(resume=False 下预建目录会 FileExistsError)。
- **指令增广 (C1)**: 语言只在训练里是**常量**时会被模型忽略(对动作无信息量 → 最优策略是丢弃),
  训练时随机换同义表述(`SS_INSTR_AUG=1`)才能让语言进入条件路径。

## ⑪ 全局记忆系统骨架 (2026-09-10 落地)
- `src/lerobot/memory/motor_hub.py` — **L2 运动基元全局记忆**: 从标杆提取"发力/速度/加速度"特征
  (v_peak/v_mean/a_peak/f_peak/f_mean/grip_sw/dur) → KMeans 聚成共享基元 → 写入
  `data/shared_memory.json` 的 `motor` 层。实测 14 标杆→4 基元(全部跨技能共用), 参数压缩 9.21×。
- `src/lerobot/memory/global_memory.py` — **三层记忆中枢**: 共享编码(39D→统一表示) +
  二态意图语法(attached `z_{t+1}−z_t` / detached `z_g−z_t`, 图同构) + 公共键 (阶段, Δz) +
  一致性校验(判定必须基于 L3 成功率/L4 可行率等**证据**, 不是"有数据就算可靠")。
  `plan()` = 一次就位(无梯度, search-free); `absorb()` = 成功后写回跨层链接。

## ⑫ 抓取滑移 / 阶段死循环诊断 (seed11/12 类难场景, 2026-09-10 实锤)
**症状**: 某 seed 跑满 1500 步不完成, 阶段反复循环 (接近→…→转移→再回接近), `grasped` 反复 True→False。
**完整因果链(按序排查)**:
1. peg 在夹爪内**缓慢下滑** — 诊断量 `off = peg − hand`, 每帧 +0.5~0.7mm (metaworld 摩擦夹持 0.03m 销, 裕度小)
2. 滑移判据触发 → `grasped=False` → `grasp_force=0`
3. 调度器回退到"抓取之前" (`stage_idx < GRASP_IDX`) → **`gripper_cmd()` 返回 0 = 张爪** → peg 真掉件
   ← **回退本身就是掉件的原因**, 不是滑脱导致回退 (这是最容易搞反的地方)
4. 重抓 → 再滑 → 死循环
**三条已证伪的修复(别再试)**:
- `GRIP_CLOSE` 0.6→1.0 **无效** (夹持力由 metaworld env 固定, 不受动作值控制)
- 运动限幅 `SS_LIMIT` 0.6→0.3 **无效** (与速度/惯性无关)
- "滑移时重夹"(强制闭合 15 帧再继续) — 机制正常运行但**物理拉不住** (实测 16→17→18mm 继续滑)
**唯一有效的判据改动**: 滑移判据由"绝对偏差 >8mm"改为
  **"帧间漂移 >4mm 连续 5 帧" + "累计偏差 >15mm 兜底"**
  → 因为"深夹后 peg 稳定停在 9mm 相对位移"是**正常**状态, 旧判据把稳定位移当滑脱 (seed11 滑移 20→10 次)。
**工具**: `tools/diag_grasp.py` (抓取轮次/到位距离/滑脱分类) · `tools/diag_slip.py` (滑移时刻/速度/阶段分布)
**定性**: peg 摆放与成功组差异大 (如 x 偏 6cm) → 布局问题; 几何相同仍失败 → **物理临界, 非控制缺陷**
  (seed7 与 seed12 抓取轨迹逐帧相同, 一个成功一个死循环 → 该结论的实证)。

## ⑬ 插入鲁棒性: 对孔精度上限 3~5mm vs 插入需求 1~2mm (2026-09-10 实测铁证)
**症状**: 抓取/转移都正常了, 但插入段反复 `🛡 插入遇阻#1 → 回撤 → 回退转移重新对孔`, 跑满 1500 步不完成。
**遇阻判据**: `_insert_depth()` 推进 < 0.8mm/帧 **且** 水平指令 > 0.03 (推而不进)。
⚠️ 判据出现 `depth=61~72mm` 时 = peg 头**根本没入孔**就顶住了的签名 (正常接近不应触发)。
**align_th 收紧梯度实验 (证明是能力缺口, 不是参数问题)**:
```
0.025(原) 3/5  成功组 346/355/343
0.010     3/5  成功组 347/356/346
0.006     3/5  成功组 346/355/420   (104 变慢)
0.003     3/5  成功组 348/359/433; seed11 卡"转移1301帧" seed12 卡"对位465帧"
0.0015    3/5  成功组 377/382/577; 难组卡得更死
```
→ 门槛收到 <3mm 时**永远达不成** → 卡在更早的阶段 ⇒ **引擎对孔能力上限 ≈ 3~5mm**。
**根因**: 孔间隙仅 1~2mm (peg 端口无倒角刚体) vs 引擎对孔 3~5mm ⇒ 缺口 2~3mm ⇒ 端面顶孔口上缘。
**正确解法(未实施, 下一步)**: peg-in-hole 工业标准 = 遇阻时在孔口上方做**螺旋搜索 (spiral search)**,
半径 1mm→4mm 递增; 现有"回撤 12 帧重对"只是**重试**, 同样的偏差必然再次顶住。
**参数**: `align_th` 已参数化 `SS_ALIGN_TH` (默认 0.025 = 原行为)。

## ⑭ L3/VLA 接入引擎失败: "取帧"函数无限递归 → 模型永远收到黑帧 (2026-09-10 实锤, 极隐蔽)
**症状**: 模型在 rollout 脚本里能完成任务, 在引擎里接管**必卡死**(实测卡"转移"2318帧, 2500步不完成)。
**通用诊断法(遇到"两条路径成绩不一致"就用它)**: 同一 env、同一帧, 对比
  「引擎取帧函数」与「env.render()」的像素差 → 本例 **平均像素差 130.72/255** ⇒ 引擎帧是全黑图!
**根因**: `_render_frame()` 的 Linux 分支写成 `return self._render_frame()` — **调用自身** →
  无限递归 → RecursionError 被 `except: return np.zeros(...)` 静默吞掉 → **永远返回全黑帧, 零报错**。
  (mac 安全渲染包装时引入: 原实现被自己的 wrapper 覆盖)
**修复**: 改回真渲染 `self.env.render()` (与采集脚本 `_frame_sink` 同源)。
**效果**: 修复前 2500 步卡"转移"; 修复后 **insert 341 步完成** / **full 全链 865 步完成 + AOI PASS** ✓
**三条教训**:
1. **"行为一致"≠"输入一致"** — 影子模式(不接管)会让黑帧 bug 完全隐形, 必须主动做输入对比。
2. **任何静默 except 兜底(return zeros / pass)都是 bug 温床** — 至少加一行 log。
3. **两条路径成绩不一致时, 先做"逐项输入对比"(state/image/动作语义), 不要先调超参** —
   本例白试了 3 处口径修正(图像 128/64、env obs、K_ACT 语义), 全都不是主因。
# 数据动作均值检查 (验证平均化)
.venv/bin/python -c "import pandas as pd,numpy as np; df=pd.read_parquet('data/X/data/chunk-000/file-000.parquet'); a=np.stack(df['action'].values); print(a.mean(0), a[:len(a)//2].mean(0), a[len(a)//2:].mean(0))"

# 生成分段数据 (抓起后停, 锁存)
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/gen_metaworld_data.py --eps 20 --stop-after-grab --rel-vec
```

## ⑮ 训练/运行时口径对齐四查 (2026-09-14 实锤: 一次查出 4 个口径 bug, 全部让评测结论作废)
**症状**: 判闸/评估连续多轮 ❌ — "预测塌缩 (pred_std/teacher_std ≈ 0.08)" + "MAE 打不过常数基线",
**且与训练轮数无关** (4 轮/3 轮/1 轮同一个病) ⇒ 不要加训练量, 直接查口径。
判据: **去掉整体偏置后 MAE ≈ 常数基线** = 模型在该口径下对教师动作零信息量 (= 输入/变换错, 不是能力不足)。

四查 (按发现顺序, 每条都便宜且致命):
1. **零初始化死锁**: 新加分支若"入口层新列"与"分支末层"**同时零初始化** → 贡献 = 0×0,
   ∂L/∂W 两侧恒 0 ⇒ 分支永久死亡。**自检**: 读 ckpt 看该层 `nonzero%` 是否仍为 0;
   判闸 `on/zero` 两臂输出**逐位相同**即命中。修: 只留一端零初始化 (保暖启动逐位等价), 另一端小随机。
   见 `references/runtime-train-parity-audit.md` §1
2. **图像预处理**: 训练 `ToImage(scale=True)+ImageNet` 时若数据集是 **float 0~255**, 而 dataset loader
   给的是 **uint8** ⇒ 训练实际输入 ≈ [-2.1, 2.4]; 运行时若直接喂 0~255 (尺度差 ~100×) ⇒
   编码器退化、动作头输出恒定带偏移。**自检**: 打印训练 batch 的 transform 后 `min/max/mean`,
   与运行时喂进去的同一批帧对比。修在**唯一入口 (桥)** 让所有运行时同时生效。§2
3. **反归一化统计来源**: `stats.json` 的 `source` 必须 == ckpt `train_config.yaml` 里的数据集名。
   实测错用另一代数据集的 stats → dx std 0.153 vs 0.074 (2.1×)、grip mean 0.120 vs 0.828 ⇒ 指令缩放全错。
   **做成快速失败** (不一致直接退出), 否则白跑 25 分钟拿假数。§3
4. **判闸/哨兵去重键**: 用 `epoch` 号当标记名 → 续训/换轮次后 ep1/ep2 被旧标记顶掉 ⇒ **永久静默不判**。
   改用 `{family}_epoch{n}` 去重 + 老名字兼容别名; 顺带取消"只判奇数/偶数轮"的限流 (短跑每轮都判)。§4

**排查脚本 (本次沉淀, 都在仓库里)**: `tools/intact_replay_bias_probe.py` (逐维 mean/std/偏置/MAE 分解/
pearson + goal 口径对照) · `INTACT-JEPA/tools/skill_deadlock_evidence.py` (死锁前后对照)。
**证伪也要做**: 曾怀疑"goal 口径 (所有帧用第 0 回合末帧)"致塌缩 → 用 `--goal-mode own` 对照后
数字几乎不变 ⇒ 该猜想被证伪, 别急着改口径。
**作废纪律**: 口径修好前的所有评测数字 (判闸 ❌、"越训越塌"、直驱 92.2mm) **一律作废并改名留证**,
不得与修后数字混在一张表里。

## ㉑ 插入失败先查"谁挡住"(接触对), 别只盯杆 (2026-09-15 实测)

- 症状: 插入段 depth 卡在某值 (本例 ~27mm), 接触力饱和 0.98, 螺旋+回退都无效。
- **三步取证 (必须按顺序)**:
  1. `env.data.contact` 逐帧打印接触对 (geom/body 名) → 本例卡死帧里 **78% 是夹爪
     (rightclaw/rightpad) ↔ 治具顶板**, **不是杆**! 只盯"杆顶孔壁"会查错方向。
  2. 头的**侧向/竖直偏差** (头↔孔轴在 y,z 上的距离): 卡死 seed 6.8~21.5mm vs 成功 seed 0.14~1.7mm。
  3. **锁存时的"抓取点↔头"距离** (off0 + head_off 的模): 成功 seed 129~132mm (设计 130) vs
     失败 seed 112~124mm → 夹爪比设计深 6~18mm, 于是压在治具上盖板, 推不动。
- 修法 (已验证 4/12→5/12, 零回退): **抓取点闭环补偿** —— 锁存后若"抓取点↔头"< 下限(126mm),
  回退重抓并把抓取目标沿杆轴**远离头**平移缺口量 (≤20mm, 最多 2 次)。成功 seed 不触发 → 逐位不变。
- 反例 (不许进默认档): ①入口 z 容差收紧 (单测能修一个 seed, 组合后净收益 0) ②"降落受阻先退出
  孔道再降" (12 seed 开关无差异) ③"滑脱→抓取点平移搜索" (无效且叠加后把已修好的 seed 打回失败)。
  这三条都保留为**默认关**的旋钮 —— 未证明提升不得进默认档。

## ⑳ 仿真引擎评估有效性三坑 (2026-09-15, 一次踩全)

**A. 共享底层 sim + 二次建实例 = 场景被偷换 (最隐蔽)**
- 症状: 同一 seed 的 A/B 两臂 act 逐位相同、step 前 qpos 逐位相同, **step 后状态不同**;
  某臂的 peg 在第 1 帧就"瞬移" Δ=[+1.2mm,−17mm,0]; 同 seed 多次运行结果漂移、成功↔失败翻转。
- 根因: 势场/几何构建 (`ObstacleField.from_engine`) 在引擎**运行中**又 `RealStateSpaceSim(...)`
  新建实例并 `_reset(104)` 采样 —— metaworld 的底层 MuJoCo sim 进程内共享 → 改写运行中场景。
- 定位手法 (可复用): 同 seed 跑两臂存 npz (x/peg_head/u_ff/u_sat/act/qpos_pre/qpos_post),
  **先看第 0 帧是否逐位相同** → 相同则问题在"运行时被外部改写"; 再逐个调用嫌疑函数
  (`_render_frame` / `skill_ctx` / 势场 / 模型 step) 并检查 qpos 是否变化 = 一次定位到函数。
- 修法: 传现成 geom 进去, 不新建第二个引擎 (只读不写)。修后逐帧复现解析链 = 收口闸行为正确。

**B. 引擎自带"肌肉记忆"默认开且跨 run 持久化**
- `SS_MUSCLE != "0"` 时每局学 champion 并 save() 到 `data/muscle_memory.json`, 后续 run 读回 →
  评估不可复现 (实测同一 seed0 从稳定成功变成 6/6 确定性失败); 热记忆下 **30~65% 的执行帧走
  记忆回放而非实时计算** (老倪红线"模型须被真实链路每帧调用"在热态下不成立)。
- 修法: 加 `SS_MUSCLE_PATH` 隔离, A/B harness **默认冷记忆** (`/tmp/ab_mem_<pid>.json`),
  `AB_HOT_MEM=1` 才用共享记忆量化"越练越顺"。冷/热结果要分别报 (实测 3/8 vs 4/8)。

**C. 局级标签训不出"何时停"**
- 用"这局最终是否失败"当标签训练停权判据, 局级区分可以很好 (成功局 P=0.39 vs 失败局 P=0.84,
  合并 OOF AUC 0.80), 但**同 seed 内只有单一类别** → 折内 AUC 无定义, 且首段帧与成功局同形 →
  模型从第一帧就报警 (假阳), 无法回答"现在该不该停"。
- 要"何时停"必须做**尝试级标签** (从卡死起点到回退的窗口), 否则不如保留硬编码 stall 计数。

## ⑲ 指标口径: tr["dist"] 夹持后是 dh(高度差), 不是插入深度 (2026-09-15 踩到)

`state_space_sim_real.py` 里 `tr["dist"].append(d_xy if not self.grasped else dh)` —
**夹持之后 dist 就变成"光模块头↔孔口的高度差"**, 不是"到插入终点的距离"。判完成用的是另一个量:
`_insert_depth()` < `insert_depth`(引擎传 0.002m) 且需 `_confirm` 连续 2 帧。
把 dh(0.4mm) 当成"插到 0.4mm"会得出完全错误的结论 (实际那是"悬在孔口上方 0.4mm 却根本没插")。
取证插入问题必须 wrap `sim._insert_depth` 逐帧记录真值, 别读 tr["dist"]。

**解析链 1/3 完成的真因分层 (同一天实测, 三 seed 各不相同)**:
- seed0: 插入段 118 帧 depth 91→0.73mm, 接触力峰值 0.96 → 真插进去, done=True ✅
- seed1: 有接触力 0.98 但 depth 卡在 31.5mm 磨不动, 随后回退重试 → **顶壁卡死** (不是判据问题)
- seed2: 插入段仅 6 帧, 接触力峰值 0.03 → **根本没接触**, 在"对位·接触"里反复回退 70 帧
⇒ 结论: 闭环成功率被**插入物理成功率**卡住, 而不是完成判据或上层策略。诊断顺序应是
①接触力 (0.03=没接触/0.98=顶住) ②depth 轨迹 (卡在什么值) ③阶段序列 (是否反复回退), 三者一起看才定位。

**⚠️ 当天修正 (同一批数据的口径陷阱)**: 上面那批 A/B 用了 `--steps 600`, 而 seed1 恰好需要 667 帧
(阶段帧数合计正好 600 = 被截断在插入段中) → 得出"seed1 失败"的假象。**放到 900 步 seed1 done=True**
(depth 0.66mm)。教训: 评估预算必须 ≥ 引擎默认 cap (insert 模式 1000), 否则把"预算不够"误判成"策略失败"。
修正后解析链实为 **2/3 完成** (seed0 384 帧 / seed1 667 帧 / seed2 真失败)。
同时 A/B 了螺旋参数 (半径 1.2→4.5mm/70帧 ×3 vs 9mm/110帧 ×5 vs 150帧/0.22rad ×4): 三臂结果差异 <0.15mm
⇒ **螺旋参数不是瓶颈**; seed2 的唯一真失败是**抓取滑移 16~19mm / 滑脱** (10 次滑事件, 从未进入插入遇阻)。

## ⑱ A/B 评估两条硬纪律 (2026-09-15 实测踩到)

1. **每臂独立进程 + 每组合≥2 重复**: 同一进程里连跑多臂会互相污染 (实测同臂在不同批次给出
   "阶段恒接近600帧" vs "跑到下降162帧, 最小插入11.5mm" 两种结果)。改成 `subprocess/命令行
   每臂一进程` 后重复间几乎逐位一致 (末端 65.1/65.1mm; 最小 2.2/2.0mm) ⇒ 可复现才算数。
2. **goal 口径必须与训练同构**: goal-conditioned 策略训练时 `goal = 该回合末帧图`
   (INTACT-JEPA `jepa.py:_encode_goal` + `train.py: goal = embeddings[:, -1:]`); 运行时若
   从不 `set_goal` → 回落到**固定文件** (所有 seed 共用一张) = 口径不一致。
   实测: 换活目标帧后提案 0% 逐位相同、平均 |Δu|=0.115 (≈u 本身量级!) ⇒ 目标帧确实是提案跑偏的成因。
   但**只在闸关时可见** (闸开后否决 87~98%, 结果由下层解析链主导, 换 goal 无可测影响)。
   教训: 目标帧要按"与该 run 场景一致"生成, 但它不是闭环成败的第一因。

## ⑰ 上层直驱 u 越界 → 执行端必须否决, 否则"链路在跑但机器人等于没接"

2026-09-15 实测 (光模块插入, 引擎 L4 直驱档):
- 症状 A: `stage_counts={'接近':600}` —— 600 帧阶段完全不动, d_xy/dh 逐帧**完全不变**, 看似"冻结";
  真相是 u 在 y 轴恒定撞限幅(−0.1235)、|u|=解析链 2.3×、60 帧末端飞 243mm 朝**错误方向**。
- 症状 B: 另一 seed `{'下降':565}` 卡死在下降段, **从未进入抓取** → 全程无产出。
- 判定"上层模块有没有真接上"**不能只看 ran/applied 计数**, 必须看 ①逐帧 stage 直方图 (是否推进)
  ②末端真位移 Δx ③u 的幅度/方向 vs 下层参考。先前误判"插入段被阶段白名单排除是瓶颈" →
  实测运行根本没到过"插入", 加白名单是**空操作** (direct vs direct_ins 数字逐位一致)。
  **没有 stage_counts 取证就别下阶段相关结论**。
- 修复 (收口闸, 默认生效): 上层提案 `u_up` vs 下层参考 `u_l2`, `cos<0` 或 `|u_up|>1.5·|u_l2|` → **否决**
  (计数 `l2_veto_dir/l2_veto_mag`, 不静默回退); 通过者按方向一致度加权 `w_eff = w·max(cos,0)`。
  效果: 0/3 完成 → 1/3 完成 + 另一 seed 插到 2.5mm。
- 读法纪律: 闸生效后否决率高 (38~98%) 时, 该臂实际主要在跑下层解析链 → **不能**把"能完成任务"
  算成上层模块的功劳; 判提升必须比较同闸下上层提案是否额外带来 done/min-insert 增益。

## ⑯ 离线判闸自身的口径 (2026-09-14 夜: 判闸 v3→v4, 结论整体翻转)
**症状**: 离线判闸连续 7 轮给出 ❌ + "ΔMAE(on−zero) 7/7 全负" + "输常数基线", 看上去像"记忆条件无效/有害"。
**真因**: 判闸脚本与**训练不同源** (不是模型不行), 四处 (每条都能单独毁掉结论):
1. **观测窗口**: 抽样 stride=120 后逐帧喂 ⇒ 模型 3 帧 obs 窗口是三帧相隔 360 帧的散帧;
   训练里 obs 窗口 = 同段轨迹上 **stride=frameskip(2)** 的连续帧。喂散帧 = 输入分布外。
2. **动作历史**: 让节点用**自己预测的 chunk 滚动** action_hist (闭环); 训练用该帧前 `frameskip` 帧**真值动作**。
   诊断必须 teacher-forced (喂真 obs + 真历史) 才是在测"模型在训练分布内的能力"。
3. **goal 口径**: 判闸把所有帧的 goal 设成第 0 回合末帧; 训练 `construct_intents` 的 goal = **本窗口末帧**
   (= 前视 `frameskip*(num_steps-1)` 帧的位移意图) ⇒ 意图幅度量级完全不同。
4. **覆盖/统计**: 只抽 120 帧 (占 149,100 帧的 9.6%, 全在数据前段) / 只看 slot 0 / 无重复;
   且 chunk 是 `[horizon, frameskip*4]`, `chunk[0, slot*4:]` 在 slot≥2 取到**空切片** (= 静默失效)。
**修法**: 判闸 = 训练同源自监督回放 → 连续窗口 (stride=frameskip) + 真值动作历史 + 训练口径 goal +
**全回合覆盖 + 多重复出均值±std** + 逐槽统计。脚本 `tools/intact_replay_check_v4.py`, 批量 `l4_ab/v4_judge_sweep.sh`,
成本 ~60 s/轮 (200 段 × 3 重复, GPU 4060)。哨兵 `~/.hermes/scripts/v6_judge_watch.py` 已切到 v4 (标记 schema 不变, 下游早收哨兵无需改)。
**前后对照 (同一批权重, 只换判闸口径)**: 7/7 输常数 (0.0387~0.0420 vs 0.0325) + pearson_dx≈0 →
7/7 **赢**常数 (0.0466~0.0499 vs 0.0830) + pearson_dx 0.53~0.63; ΔMAE(on−zero) 7/7 负 → **6/7 正且随训练轮数单调递增** (r5 +0.00057 → r10 +0.00497)。
死锁轮 v6r2 ep3 Δ=0 (on/zero 逐位相同) 恰好是已知 0×0 死锁 → 内部自洽, 反向验证口径可信。
**纪律**: ① 判闸/评估脚本的输入口径必须逐项写清 (窗口 stride / 历史来源 / goal 语义 / 抽样数与重复数),
否则容易把输入错当成能力不足; ② 出现"整片结论一边倒"时先怀疑口径, 不要加训练量;
③ 幅度与噪声同量级时靠**趋势 + 锚点**判定 (本例 7 轮单调 + 死锁锚点=0), 单轮不说"显著"。
**附带结论 (2026-09-14)**: goal 换成"部署口径回合末帧"后 MAE +12% 但**预测动作幅度几乎不变** (0.0215 vs 0.0217)
⇒ goal 口径**不解释**直驱过冲 152~331mm; 直驱过冲的嫌疑转到"8 维动作块 = frameskip 帧 × 4 维, 部署侧按每帧消费/按 stride=1 喂观测 ⇒ 速度翻倍"。

## 参考
- `references/eval-pipeline-diagnosis.md` — 评估管道排查实录 (现象→根因→代码位置, 含数据生成器多阶段专家 5 个陷阱)
- `references/runtime-train-parity-audit.md` — **训练/运行时口径对齐四查** (2026-09-14: 死锁/图像/统计来源/去重键 的复现命令与前后对照数字)
- `references/judge-caliber-v4.md` — **离线判闸口径换代 v3→v4** (同批权重的翻转数字表、v4 参数语义、v6/改判闸时要改的 4 处)
