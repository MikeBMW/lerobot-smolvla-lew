# L4 运行时口径 · 两条 INTACT 路 · "模型不被采纳"定量归因 (2026-09-22 一手)

承接 SKILL.md §6 (与 L2/L3 对齐)。这里回答两个**每次都会被问**的问题:
"点 L4 到底有没有把模型动作喂进 env?" 和 "模型没被采纳是接线问题还是能力问题?"
并记一个真实修掉的口径 bug (反归一化统计用错源)。

## A. 引擎里 INTACT 有**两条**路 — 别混淆

| 路 | 装配 | 需标定? | 判据 |
|---|---|---|---|
| **直驱路 (主)** | `tools/intact_direct_rollout.install_direct_act(sim, node, a_mean, a_std, infer_every=1)` 包 `sim.sched.decide` → 每帧写 `sim._direct_act`; 引擎在 `_direct_act` 非 None 时**直接用模型动作做 env.step** (不走 `u_vec`/`K_ACT`), 唯一变换 = 训练归一化逆变换 `a_raw = z*std + mean`, clip ±1 | 否 | `sim._direct_act is not None` |
| 前馈槽位 (冗余边) | `sim.attach_intact(node, adapter)` → `_intact_u_ff` (`state_space_sim_real.py:1351`) | 是: `IntactActionAdapter.enabled` 需 `models/intact_action_map.json` (生成器 `tools/calib_intact_action_map.py` 从未写 ⇒ 从未标定) | `_intact_stats.u_ff_src` |

**结论**: 前馈槽位 `refused_map=N` **只说明那条冗余边断**; 它旁边的 `u_ff_source="intact(chunk×K_ACT=0.5)"`
说明解码器先验其实可用。诊断 "L4 不驱动" **先看直驱路**。
直驱路每帧还会: 真渲染帧 → `build_skill_ctx(...)` (L2 24 维上下文, 逐帧) → `policy_service.run_once(decode=True)`
→ `chunk` → (可选 `SS_L4_DIT=1` 与 DiT 融合 `act = (1−β)·act_INTACT + β·act_DiT`) → **L2 收口闸**。

## B. 口径 bug: 反归一化统计与权重**不同源** (已修)

```
GUI 装配 (simulink_module.py:12016) / probe / diag 原读写死 reports/zmax_action_stats.json
                                        ↳ 源自 zmax_insert.h5 (n=18635)
在役 intact_l4_current/weights.pt → v6r11/weights_epoch_2.pt → train_config.yaml name: optical_insert_v5_disturb.h5
本轮 intact_goal_optical_insert_v6d5_s3072        → train_config.yaml name: optical_insert_v6_disturb.h5
⇒ dx std 0.153 vs 0.0742/0.0774 ≈ 2 倍 ⇒ 指令缩放全错, 判闸/演示数字全不可用
```
修法 (`tools/intact_direct_rollout.py`):
```python
stf, why = idr.resolve_stats()      # 在役指针 → 跟随软链 → 真实权重目录 → train_config.yaml → 找同源统计
print(why)                          # ✅ 同源: optical_insert_v5_action_stats.json ↔ ckpt 训练集 optical_insert_v5_disturb.h5
```
- ★ **必须跟随软链**: `checkpoints/intact_l4_current/` 是「目录 + `weights.pt` 软链」形态, 目录内**没有**
  `train_config.yaml` ⇒ 不 follow symlink 就解析成"未知" → 静默回落到错统计。
- 已有闸 `audit_stats()` 会 fail-fast (报"用 --stats reports/<同源>_action_stats.json 重跑"), 但默认路径
  与 GUI 装配点没跟上 ⇒ **新工具一律用 `resolve_stats()`, 别手写路径**。
- 效果: 模型动作逐维 std `0.045/0.008/0.040/0.57 → 0.022/0.004/0.017/0.37` (与参考同量级, 不再 2 倍虚大)。

## C. 判 "模型是否被采纳" 的运行时计数 (别只看"模型跑了")

工具: `tools/probe_l4_direct_count.py <steps>` (gui-venv311, `CUDA_VISIBLE_DEVICES=` 走 CPU)。
```
IntactNode.step / IntactIntentService.run_once / build_skill_ctx  = 200/200  ← 真推理 + L2 上下文 ✚
rec['act'] = 200                                                           ← 模型动作被记录   ✚
state["gate"] = {n:200, veto_dir:200, veto_mag:0, blend:0, cos_used:0}     ← 全部被闸否决     ✖
sim._direct_act = False                                                    ← 没进 env        ✖
```
**真推理 ≠ 采纳**。gate 的 `veto_dir`(方向反相) / `veto_mag`(幅值超 1.5×) / `blend`(按 `w_eff=cos` 融合,
方向一致才混) 才是采纳口径; `_direct_act is None` ⇒ 该帧执行的是**参考(解析)链**。

## D. 判定技术: off-policy 配对拟合 (接线 vs 能力)

思路: **闸开着** → 参考链驱动、模型仍在**参考帧**上逐帧真推理 ⇒ (模型 chunk, 参考 u) 配对合法,
不会被自我漂移污染。工具: `tools/fit_intact_action_frame.py <steps> <seed>`。

做法: 逐轴在**完整 D_official 维**里搜最佳维 j + 过原点最小二乘 `K=<u,a_j>/<a_j,a_j>`(允许负号) → 报 |corr|、R²。
- |corr| ≥ 0.5 ⇒ 只是两套动作空间差一个线性映射 (**约定问题**) → 写标定有意义;
- 弱相关 ⇒ **能力不足** → 写标定映射无意义, 只能训练侧解决。
- 数据卫生: 参考 xyz 非零帧才拟合 (夹爪停爪阶段的 0 会把 K 往 0 拉); `dy/dz` 最佳维落在 1/3/4 不等于
  "布局变了" —— 弱相关时"最佳维"本身不可信, **别据此改 slice**。

实测 (2026-09-22, 在役 v6r11, 400 步 seed0):

| 引擎轴 | 最佳模型维 | corr | 判定 |
|---|---|---|---|
| dx | 1 | 0.370 | 🟡 弱相关 |
| dy | 3 | −0.261 | 🟡 弱相关(反相) |
| dz | 4 | −0.353 | 🟡 弱相关(反相) |
| gripper | 7 | 0.666 | ✅ 可线性对齐 |

⇒ 与 v5.5.37 变更记录一致: "预测 std 仅教师 7~16%, **模型能力问题非接线问题**"。

### KPI (取代"感觉好点没有"; 每次换权重同 seed 重测这张表)
```
KPI-1 逐轴 |corr| (dx/dy/dz): 目标 ≥0.5  ← 闸才会按 cos 融合
KPI-2 闸采纳率 blend/N:        目标 >0
KPI-3 sim._direct_act = True (模型动作真进 env)
KPI-4 下游: 仿真插入成功率 + 3D 视图可见"插拔成功"
```

## E. 三个坑

1. `frameskip: 2` (train_config) ⇒ `action_dim = 8 = 2 帧 × 4 维` ⇒ 当前帧 = `chunk[step, 0:4]`:
   直驱路的 slice **本来就是对的**, 别急着改 (先做 D 的拟合再决定)。
2. **`import tools/probe_l4_callchain.py` 会覆写 `INTACT_POLICY`** (改成 `intact_l4_current`)
   ⇒ 依赖它的工具(fit/probe/自建 harness) 必须在**导入前**捕获权重路径或显式传 `ckpt=`,
   否则 `resolve_stats()` 拿到错指针 (表现为 reason 里训练集 = "?")。
3. 要看**完整 chunk** 判布局: 包 `lerobot.policies.intact.service.IntactIntentService.run_once`
   记 `self.last_out.chunk`; 直驱路只落 `rec['raw']`(slot 0:4), 只看它会把最佳维系统性搜错。

## F. 复现命令
```bash
cd /home/ubuntu/lerobot-smolvla-lew
# 直驱路 + 收口闸取证
CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_direct_count.py 200
# 逐轴对齐判定 (KPI 表)
INTACT_POLICY=<ckpt目录名>/weights_epoch_1.pt CUDA_VISIBLE_DEVICES= \
  gui-venv311/bin/python tools/fit_intact_action_frame.py 400 0
# 调用链/行级断点 (L4 / L4dec / L4audit / L3)
CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_callchain.py L4 30
```
配对样本落盘: `reports/intact_action_frame_fit_seed<seed>_<steps>.json`
文档: `docs/design/l4_stats_caliber_fix_20260922.md` · `docs/design/l4_runtime_evidence_matrix_20260922.md`
