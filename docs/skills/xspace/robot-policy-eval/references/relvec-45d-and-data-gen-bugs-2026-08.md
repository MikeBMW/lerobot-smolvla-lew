# 45D 目标条件化 + 数据生成器 bug 排查 (2026-08-08)

## 背景
MLP 蒸馏是唯一能插拔的学习模型（抓起 6/10 插入 3/10），根因=39D 坐标直接映射。
5 个大模型（ACT/SmolVLA/LEW/VLA-Touch/AWE）长轨迹训练后全部方向退化（后退）。

## 三步方案（老倪"全做"）
1. **①分段数据 (--stop-after-grab)**: 抓起后保持 30 帧即停记录，方向一致防平均化
2. **③目标条件化 (--rel-vec)**: state 39→45D，尾部 +6 = `[peg-hand, hole-peg]`
3. **④夹爪头分离**: 位置动作用主模型，夹爪用阈值触发（真实机器人=位置伺服+力控）

## 45D 实现细节
- 生成器 state 计算处: `rel_vec = concat([peg_pos-hand_pos, hole_pos-peg_pos])` → `state = concat([state, rel_vec])`
- **info.json 必须同步**: `features.observation.state.shape = [45]` + total_frames 更新，否则 CastError
- **评估必须补同样 6 维**: `st_raw[:39]` + env site 算 rel_vec 拼上（st_dim==45 判断）
  ```python
  if st_dim == 45 and st_raw.size == 39:
      hand = env.data.site_xpos[env.model.site("endEffector").id]
      peg = env.data.site_xpos[env.model.site("pegGrasp").id]
      hole = env.data.site_xpos[env.model.site("hole").id]
      st_raw = np.concatenate([st_raw, peg-hand, hole-peg])
  ```
- **_load_stats policy_hint**: 每个模型 stats 不同，候选列表按 policy 名映射，act 优先 45D checkpoint

## 数据生成器 bug 排查链（多阶段专家）
1. **lifted 判断错误**: `ee[2] > target_hole[2]-0.01` 手初始 z=0.155 > 0.121 → 永远 True → 跳过 Phase1-3 直接转移 → peg 从没被抓起。修: `peg_z > peg_z0 + 0.04`
2. **peg 位置未每步更新**: `peg = site_xpos[pid]` 在循环外取一次 → grasp_pt 永远初始值。修: 循环内 `peg_cur = env.data.site_xpos[pid_use]`
3. **官方专家远起点失效**: 手被移到 (-0.05,0.3) 后 SawyerPegInsertionSideV3Policy 内部状态机错乱，接近不了 peg。修: --far 用多阶段专家
4. **grab-only 全丢**: 接近速度 0.3 → 抓取失误（peg 升高-0.005）；降到 0.18 仍不稳。多阶段专家抓取本身脆弱
5. **官方专家夹爪序列**: 前 30 步动作 [1,1,1,-1]（先闭合），中段 0.6（张开）——夹爪顺序固有反了，MLP 能学（90% 抓起）但大模型难

## 实测结论
- ACT-seg 45D 后距孔变化（0.214-0.507，在动）→ 45D 解决了"不动/后退"，但夹爪仍不闭合 → 抓起 0/10
- 方向性解决了，夹爪决策仍需 ④ head 分离或 grip_assist

## 视频方向（老倪确认）
- 5 模型 rollout 视频: 原版不旋转
- 所有行为/成功视频: 若反了 ffmpeg `-vf "transpose=2,transpose=2"` 旋转180
- 一次发齐所有视频（MEDIA: 多条），不要逐个发
