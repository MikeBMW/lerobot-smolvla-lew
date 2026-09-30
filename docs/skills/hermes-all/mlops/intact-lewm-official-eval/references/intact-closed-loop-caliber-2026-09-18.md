# INTACT 在 Z-MAX 引擎里的闭环口径 (L4 直驱 / u_ff 接管 / 标定闸) — 2026-09-18 实测

补充"官方评测"之外的一条线: **把 INTACT 接进六层引擎做闭环**时的口径事实与有证据的负结果。
每条都是实测或读码得到, 不是推测。

## 1. 步数预算 (最容易把结果误判成"模型不行")

- `RealStateSpaceSim.run()`: 默认 `MAX_STEPS`; `cap="l4"` 时 **×2** → **full 4000 / insert 1000**。
- `tools/intact_direct_rollout.py` 默认 `--max-steps 600`, **低于 insert 预算** → 600 步口径下
  解析链常停在余量 5.4 / 11.6 / 17.0 / 18.8 mm (差一点就完成) 被记成失败。
- 纪律: 闭环 A/B 用 insert=1000 / full=4000, 报告里写清预算。

## 2. "模型有没有真的在驱动" 看**收口闸计数**, 不看 success

每轮会打印 `🛡 L2 收口闸: 共 N 步 · 阶段白名单外 · 方向/一致度否决 · 幅度否决 · 采纳融合 · 幅值限幅`。
`采纳融合` = 模型动作真进执行的步数。

11 seed (mode=insert, 600 步, 权重 `intact_l4_current` = v6r11 ep2):
- 成功率: 解析链 3/11 vs 直驱 2/11 (seed 7 解析成功/直驱失败 = 回退案例);
- **两轮成功里模型采纳步数 = 3 和 0** → 名义"直驱"实为解析链收口 = 脚本开环。
  ⇒ success 必须与采纳步数一起报, 否则把"链路跑通"说成"模型驱动"。
- 否决以方向为主: 末 5 步 cos ≈ −0.67 (系统性反相), 提案幅度 ≈ 执行层参考的 1/10;
  阶段白名单 `SS_DIRECT_STAGES=接近,对位,转移` 在 insert 模式下 `stage_out` 常有 250-530/600 步。

## 3. u_ff 接管标定闸: 全局不过闸, **但先看分阶段**再判

`tools/calib_intact_action_map.py` 口径 = 物理量纲对齐 (每轴**选维 + 单尺度含符号**, 非回归拟合状态机),
闸 = 每轴 |Spearman ρ| ≥ 0.30 ∧ 嵌套 5 折 OOF R² ≥ 0.20。
实测 (N=274): 全局 x/y/z |ρ| = 0.12/0.22/0.10, OOF R² ≈ −0.0002 → 不过闸 (脚本诚实拒写);
**分阶段 |ρ| 却很高**: 对位 x 0.72 / 转移 y 0.79 / 插入·接触 z 0.47 / 下降 y 0.47
—— 因为引擎 `u_ff` 是**分阶段状态机语义**, 全局单维单尺度被摊平。
阶段条件 (stage-aware) OOF 在样本少时会**过拟合变负** (−3.07): 先加样本 (多 seed/多步) 再说,
别拿负 R² 直接判"INTACT 动作不可用"。
诊断工具: `tools/diag_intact_stage_align.py` (全局 / 分阶段 / 阶段条件 OOF 一次跑完)。

## 4. 工具前提: skill 通道

`intact_pair_collect.py` 不喂 `skill_ctx` → 对 `skill_dim>0` 的 ckpt (v6 记忆条条件系列) 直接失败:
`... with a skill channel (skill_dim>0) but info['skill_ctx'] was not provided — refusing to silently degrade`。
要用当前 L4 权重重跑标定/配对, 先确认工具链喂 skill_ctx (参考 `intact_replay_check_v4.py` 的采样口径:
连续窗口 stride=frameskip、真值动作历史、goal_mode=train)。

## 5. 分层回答"啥水平" (同一权重的三档证据)

v6r11 ep2 离线同源 replay (200 clips × 3 reps, teacher-forced):
slot0 MAE 0.0347 vs 常数基线 0.0828 (≈42%), pearson_dx 0.71, skill_on ≫ skill_zero (0.0837)
→ 域内**学得动**; 但 std_ratio_xyz ≈ 0.37 (< 0.5 = 幅度塌缩闸未过), 闭环上提案反相、采纳 ≈ 0。
分层: 基座(官方 pusht) → 域内离线(赢常数基线, 幅度不足) → **闭环未成立**。
