# 🧠 记忆条件通道: 让 L4 的 INTACT「看到」L2 原子技能 (2026-09-14 实测配方)

老倪原话: "带着记忆层，适配训练 L4 的INTACT, 要能让L4看到 L2的原子技能，复用能力;
我要看到最后的视频成功插入并抗干扰的证据; 你要作新的抗干扰的数据; 适配训练"

这套配方 = **把记忆层状态当成外部模型的一个条件输入训进去**, 且**不许让已有能力回退**。
INTACT 是无条件动作头 (只吃 `[z, intent, z*intent, prev_act_emb]`), 本工程记忆层 = L2 原子技能,
所以中间要一个显式契约。

## 一、契约 (单一事实来源, 顺序写死=版本号)
`skill_ctx` 24 维 = `[引擎相位 one-hot(13) | L2 势场技能软权重 w(8) | 到最近冠军轨迹管横向距离 d_perp |
沿该管弧长 arc_frac | 夹爪指令 grip]`

- 单源实现: `src/lerobot/policies/intact/skill_ctx.py` (`STAGE_ORDER` + `build_skill_ctx(process, x, stage, grip)`
  + `SKILL_CTX_DIM`) —— **采集器与闭环桥 must import 同一个函数**:
  - 数据采集: `tools/intact_insert_dataset_v5.py` (每帧 sink 里调)
  - 闭环推理: `tools/intact_sw_optical_bridge.py` (每帧 `_infer` 里调 → `node.step(..., skill_ctx=..)`
    → `info["skill_ctx"]` → npz → worker 自动进 info)
  两套代码 = 训练/推理口径不一致 = 白训; 兜底回归 `tools/skill_ctx_consistency_check.py`
  (重算已落盘 part 的该列, 要求逐位一致 + 非零占比够, 否则"给了模型一列常量"也算失败)。
- 坐标口径: `x` 用**夹爪真实位置 obs[0:3]** (引擎 `self.x = o[0:3]`), 不是 `peg_head()`
  —— 实测同 seed 两者差 (0.017,0.054,0.176)m, 用错时 d_perp 恒 ~0.13m、场在自己坐标系外求梯度。
- 相位表 = 引擎 `cognition.ActionModulator.STAGES` (mode=full 13 段, 前 8 段 = SK01..SK08);
  **别只写 8 段** —— "放下/AOI转移" 等会被误映射成一维, one-hot 变噪声。

## 二、模型侧零回退扩展 (三条缺一不可)
`IntentActionActor(... skill_dim: int = 0, skill_emb_dim: int = 32)`:
1. `skill_dim=0` 是默认 ⇒ 参数形状与老配置**逐字节相同**, 老 ckpt 仍可 `strict=True` 加载;
2. `skill_dim>0` 时新增 `skill_enc = Linear→SiLU→LN→Linear`, **末层零初始化** (输出 ≡ 0);
3. ⚠️ **入口层 `net.0.weight` 形状从 `[1024,768]` 变 `[1024,800]` ⇒ 部分加载会跳过它** →
   必须**老列逐位复制 + 新列置零**。只做 2 不做 3: 暖启动实测差 **0.4356** (随机入口层污染全网络);
   做完 3: 带 skill_ctx 跑 vs 老模型跑 = 最大差 **0.000e+00** (逐位等价)。
   实现位置: 训练脚本载入 ckpt 后 (配置开关 `init_zero_skill_branch: true`)。
4. `get_action` 里: `skill_dim>0` 却没有 `skill_ctx` → **raise** ("refusing to silently degrade")。
   副作用很好用: 闭环跑起来不报错 = 条件向量每帧都真送到了 (这是"共同运行"的最硬证据)。

## 三、"写了没接" 五道自检 (`INTACT-JEPA/tools/intact_skill_channel_check.py`)
真权重 + 真数据窗口 (`pixels` 从 h5 读要 **HWC→[T,C,H,W] 转置**, 否则 `Expected 3 but got 224`):
- A `skill_dim=0` + 老 ckpt → **strict 加载成功** (= 老行为零改变)
- B `skill_dim=24` 部分加载 → 断言 skip/missing **只有分支键与入口层** (>316 个参数逐位来自 ckpt)
- C 零化分支 + 老列复制 → 与老模型输出**逐位相同**
- D 扰动**入口新列 + 分支末层** → 输出必须变 (只扰动末层时入口列为 0 → 恒 0, 会假判"没接")
- E 诊断 `skill_dim / skill_used / candidate_sequences==0` 如实报

## 四、判闸: 同权重同帧消融 (老倪 09-12 口径"有提升非仅不回退")
同一 ckpt、同一批真帧, 只切条件: `--skill on` (真值) / `--skill zero` (全零消融) 各跑一遍:
- ① `MAE(on) < 常数基线` ② **`MAE(on) < MAE(zero)`** ③ 预测std/教师std ≥ 0.30 (不塌缩)
- 只有 ① 通过 = "不回退"; ② 才叫"记忆层真的有用"。三条全过才是交付门槛。
- 哨兵: `~/.hermes/scripts/v6_judge_watch.py` (no_agent cron 每 20 分钟; 无新 ckpt 静默;
  节流 1/2 + 偶数 epoch) + `reports/intact_replay_v6_epoch{N}_skill_{on,zero}.json` 留证据。

## 五、训练侧坑 (Hydra / DataLoader / 在训证据)
- 数据集配置 `keys_to_load` 必须加新键 (`skill_ctx`) —— 否则训练侧根本拿不到 (但**不会报错** ✗);
  验证: 日志出现 `Cached 'skill_ctx' from '<h5>'`。
- 配置里**不存在**的键要 `+trainer.limit_train_batches=6` (前缀 `+`), 否则
  `Could not override 'trainer.limit_train_batches'`。
- `prefetch_factor` 只在 `num_workers>0` 时合法: `num_workers=0 + prefetch_factor=2` → ValueError。
- 在训证据: 让 `log_dict` 里出现 `fit/<x>_used: 1.000` **且** `validate/<x>_used: 1.000`
  (训练/验证两栏都有; Lightning 的 prog_bar 表会打出来)。
- 通道切片必须与 actions **同窗口**: `skill[:, local_start : T-1]` / `skill[:, goal_start : T-1]`
  (别整段糊一起, 也别沿用整段 skill)。

## 六、抗干扰数据 (新数据怎么算"真抗干扰")
`tools/intact_insert_dataset_v5.py`:
- 干扰 = 引擎**真注入** (`_inject_peg_jitter` 改 peg 的 qpos + `mj_forward`, 现场几何/obs 全重读),
  不是贴图; 三档 `light/med/heavy` 用显式 `_jitter_override` (可复现), yaw 上限钉在 ±15°
  (物理可成功域, 再大长条盒夹不住 = 造不出成功样本)。
- 每回合把 `_jitter_meta` (dx_cm/dy_cm/dz_mm/yaw_deg/shell90) 与 `_insert_depth` 记进 part meta
  → 报告里能逐条溯源"这条数据被怎么干扰过"。
- 专家口径 `--cap l4` (自主恢复档) + `--success-only 1`; 落盘后**必须抽查**: keys 里有 `skill_ctx`、
  帧 std>5、d_perp/arc_frac 非零占比够 (曾因一个 4 元组解包 bug 整列缺失而日志全绿 ✗)。

## 七、坑 (本轮踩到的原文)
- `project_polyline()` 返回 **(最近点, 距离, 弧长, 段号) 4 元组**; 按 3 元组解包 → 每帧 ValueError
  → 被引擎 `_frame_sink` **静默吞掉** → part npz 里**整列 skill_ctx 都没有**, 而日志一切正常。
  教训: sink/回调里的构造失败要么外抛, 要么把错误写进 meta (`skill_ctx_err`), 不许零填充混过去。
- 落盘 `np.savez_compressed(p, **kw, ...)` 忘写 `**` → pixels/action/observation 全不落盘,
  文件几 KB 而日志说"900 帧" ✓ 假成功 → 落盘后必验 keys + 帧 std。
- 逻辑量 `ep_sk` 为空时, 采集器 meta 写的是"未记录 (--l2-skill-ctx 0)" —— **读 meta 就能分辨
  "没接" 和 "接了没数据"**, 别只信日志。
