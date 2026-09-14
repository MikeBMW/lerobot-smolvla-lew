# 评估有效性前置自检 (2026-09-15, 一次踩全三坑后定稿)

## 触发
任何要拿 A/B / 成功率 / "有没有提升" 的数字下结论之前 —— 尤其是**判定上层模块(模型/预测器/直连线)
是否真的接进执行链**、或**判定某改动是否提升**。本文件是"下结论前的最后一道闸"。

> ⚠️ **与 `paired-ab-and-noise-control.md` §② 的冲突**: 那里主张"同进程内背靠背配对消除冷/热启动偏差"。
> 本仓库引擎**有跨臂持久状态**, 进程内配对会把 A 臂状态泄漏给 B 臂 ⇒ **以本文件 §⑥ 为准**
> (每 (seed×臂) 独立进程 + ≥2 重复)。该文的配对协议/噪声判据仍然有效, 只有"同进程"这一条作废。

## 五问自检 (每条都有"命中签名", 命中就别下结论)

**1. 两臂跑的是同一个场景吗?**  ← 2026-09-15 最隐蔽的坑
- 存两臂逐帧 npz (`act` / `qpos_pre` / `qpos_post` / `peg_head` / `u_ff`) 对齐比较。
- 命中签名: **第 0 帧逐位相同, 第 1 帧起分叉** ⇒ 不是协议差异, 是**运行时被外部改写场景**。
  本例根因: 势场构建在引擎运行中新建第二个 env 实例并 reset → 共享 MuJoCo sim 被改
  (peg 瞬移 Δ=[+1.2mm, −17mm, 0])。定位法见下面配方 A/B。
- **影响**: 同 seed 的某臂与对照臂跑的不是同一个场景 ⇒ 该批所有结论作废。

**2. 评估状态是干净的吗?** (肌肉记忆/记忆层/缓存)
- 命中签名: 同一 seed 在多次运行后从"稳定成功"变成"确定性失败"; 或热态下大量帧走**记忆回放**
  (本例 30~65% 帧), 而红线要求"模型须被真实链路每帧调用"。
- 处置: 每 run 隔离 `SS_MUSCLE_PATH=/tmp/ab_mem_<pid>.json`; **默认冷口径**, 想量化"越练越顺"才用热记忆
  (`AB_HOT_MEM=1`), 且冷/热必须分别报 (本例 3/8 vs 4/8)。

**3. 预算够吗?**
- 命中签名: 阶段帧数**恰好等于** `--steps` (本例 seed1 需要 667 帧, 600 帧跑到 600 就停 = 被截断),
  于是把"预算不够"误判成"策略失败"。
- 规则: `--steps` ≥ 引擎默认 cap (本引擎 insert 模式 1000); 报结论前核对"是否跑到自然结束"。

**4. 指标口径对吗?**
- `tr["dist"]` 夹持后 = **dh (头↔孔口高度差)**, 不是插入深度; 判完成用 `_insert_depth()` (<0.002m,
  连续 2 帧)。把 dh 0.4mm 当"插到 0.4mm"会得出完全反向的结论。
- 取证插入必须 wrap `sim._insert_depth` 逐帧记录真值。

**5. 每臂独立进程 + ≥2 重复?**
- 命中签名: 同一臂在不同批次给出不同结果 (本例 "阶段恒接近600帧" vs "跑到下降162帧")。
- 规则: 独立进程后重复间应**逐位一致**; 不一致就先查泄漏源, 别急着解释成"噪声"。

## 三条取证配方 (可直接照抄)

**配方 A — 场景同一性 / 谁改了我的场景**
```python
# 1) 逐帧记录: 包住 env.step, 记 act / qpos_pre / qpos_post / site_xpos
_ostep = env.step
def wstep(act, _o=_ostep):
    rec['acts'].append(np.asarray(act, float).copy())
    rec['qpos_pre'].append(np.asarray(env.data.qpos, float).copy())
    r = _o(act)
    rec['qpos_post'].append(np.asarray(env.data.qpos, float).copy())
    return r
env.step = wstep
# 2) 比对: 第 0 帧全同 + 第 1 帧不同 ⇒ 外部改写 (不是控制律差异)
# 3) 逐个调用嫌疑函数, 每步查 qpos 是否变化 → 一次定位到函数
sim._reset(seed); q0 = env.data.qpos.copy()
for tag, fn in (("render", sim._render_frame), ("skill_ctx", lambda: sim._l4_skill_ctx("接近")),
                ("l2_proc", sim._l4_l2_proc), ("node.step", lambda: node.step(fr, skill_ctx=sk))):
    fn(); print(tag, "Δqpos =", np.abs(env.data.qpos - q0).max())
```
仓库现成工具: `tools/diag_l4_coupling.py` (两臂逐帧存 npz) · `tools/diag_coupling_isolate.py` (逐个调用隔离)。

**配方 B — 插入/装配失败"谁挡住了" (接触对优先)**
```python
for ci in range(int(env.data.ncon)):
    c = env.data.contact[ci]
    g1, g2 = int(c.geom1), int(c.geom2)
    name = lambda g: env.model.body(int(env.model.geom_bodyid[g])).name or "(box)"
    # 统计每对 (name(g1), name(g2)) 在卡死帧窗口内的出现率
```
顺序: ①接触对 (谁挡住) ②头的侧向/竖直偏差 (头↔孔轴 y,z) ③锁存时的"抓取点↔头"距离 (设计值对比)。
本类问题实测: 卡死帧 78% 是**夹爪↔治具上盖板**, 不是杆; 成功 seed 入孔偏差 0.14~1.7mm, 失败 6.8~21.5mm。
仓库工具: `tools/diag_insert_contact.py` · `diag_insert_geom.py` · `diag_insert_depth.py` · `diag_retreat_reason.py` · `diag_slip_cause.py`。

**配方 C — "真的接上了吗" (功能计数 ≠ 生效)**
- 不能只看 `ran/applied` 计数; 必须看 ①逐帧 stage 直方图 (是否推进) ②末端真位移 ③u 的幅度/方向 vs 下层参考。
- 反例: 声称"解禁插入段白名单"能提升 → 实测 `stage_counts` 显示**从未到过插入** ⇒ 加白名单是空操作。
- 上层提案越界 (方向相反 / 幅度 >1.5×下层参考) 必须由执行端**否决并计数**, 否则"链路在跑但机器人等于没接"。

## 结论纪律
- **口径一变, 旧结论立即作废并改名留证** (本例: peg 瞬移修复后, 之前所有涉 L4 的 A/B 结论全部作废重测)。
- 报"提升"必须同时给: done/几何量对比 + **零回退证明** (成功样本逐位不变) + 重复范围。
- 反直觉/一边倒的结论先怀疑口径与状态泄漏, 不要先解释成"能力问题"。
