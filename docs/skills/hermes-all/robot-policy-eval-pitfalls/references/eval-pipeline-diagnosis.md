# 评估管道诊断实录 (2026-08-08)

## 背景
5 个视觉大模型 (ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE) 长轨迹训练后评估全部 0% 抓起。
逐层排查发现 4 个评估管道 bug + 1 个数据本质问题, 全部是"假 0%"。

## 排查顺序 (从现象到根因)

### 现象 1: 所有模型距孔值完全一样 (0.352/0.291/0.319...)
→ peg 从没被碰过 = 模型动作没生效或没动
→ 先查动作输出: `select_action` / `policy(s_t, t_t, act_hist)` 输出

### 现象 2: ACT 输出恒定 [-0.34, -0.35, -0.03] (5 步不变)
→ 模型学到"平均动作" = 数据方向抵消 (长轨迹平均化)
→ 打印数据动作均值验证

### 现象 3: AWE 输出恒定 [-0.01, -0.215, -0.116]
→ 归一化空间动作直接 env.step = 动作错误
→ 反归一化修复: `act = act * a_std + a_mean`

### 现象 4: SmolVLA 动作乱但 ACT 正常
→ SmolVLA 视觉输入是 64x64, 评估喂 128x128 = 视觉编码全错
→ `img_size = 64 if "smolvla" in type name else 128`

### 现象 5: stats 维度 39 vs 45 不匹配
→ _load_stats 读到旧模型 checkpoint 的 39D stats
→ 按 policy_hint 选候选, 45D checkpoint 优先

## 关键代码位置 (lerobot-smolvla-lew)
- `tools/eval_insert.py`: run_episode (归一化/反归一化/图像尺寸/45D补向量)
- `tools/gen_metaworld_data.py`: 多阶段专家 (Phase 1-5), --stop-after-grab 锁存
- `src/lerobot/policies/act/modeling_act.py`: 坐标叠加 (latent += state), n_1d_tokens

## 数据生成器多阶段专家陷阱
1. `lifted` 判断必须用 **peg 高度** (手初始 z 就高, 用手 z 判断永远 True → 跳过抓取直接转移)
2. **peg 位置每步重新获取** (`env.data.site_xpos[pid]`), 循环外取一次会固定为初始位置
3. 官方专家远起点状态机失效 (只会在标准起点工作), 远移后用手写多阶段专家
4. grab-only/stop-after-grab 用多阶段专家 (官方专家夹爪离散学不到闭合)
5. 截断 parquet 后 info.json 会 CastError → 用生成器直接产出 (勿手动截断)

## 生成器截断调试实录 (2026-08-08 后半段)
**目标**: `--stop-after-grab` 让轨迹在"抓起后 30 帧"截断 (方向一致防平均化)
**调试链** (全部踩过):
1. **主 env 必须 `camera_name="corner2"`** — 无 corner2 时官方专家动作时序乱, peg 抓取轨迹异常, 截断永远不触发 (内联测试有 corner2 正常、生成器无 corner2 不正常 → 对比定位)
2. **截断阈值 +0.04 → +0.03**: peg 抓起瞬间只升 +0.035, 0.04 阈值永远不触发
3. **锁存后每帧无条件 +1**: `if grabbed>=1: grabbed+=1` (不是 elif) — peg 持续升高时若走 max(grabbed,1) 分支会永远卡在 1
4. **官方专家路径 (use_official) 有自己的 append+continue 分支**, 跳过主循环的截断检测和 break — 必须在官方分支内**也加截断检测 + continue 前 break**
5. **all_eps length 用实际帧数**: `len([f for f in all_frames if f["episode_index"]==ep])` 而非 args.steps
6. **丢弃轨迹要重编号**: 8 条丢弃后 episode_index=[0,3,5...] 稀疏 → 重编号 0..n-1 否则越界

**断点定位法**: 生成器 vs 内联测试唯一差异逐项对比 (env 构造参数/路径分支/检测位置), 比盲改快得多

## 45D 数据 (目标条件化)
- 生成器: `--rel-vec` → state = concat(39D, peg-hand, hole-peg) = 45D
- info.json features shape 同步 [45]
- 评估: st_raw[:39] + 补 rel_vec
