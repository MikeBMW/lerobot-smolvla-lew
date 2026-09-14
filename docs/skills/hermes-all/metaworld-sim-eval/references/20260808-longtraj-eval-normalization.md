# 长轨迹平均化 + 远起点不可行 + AWE/VLA 评估归一化 (2026-08-08 会话)

## 长轨迹(300步)数据 → 行为克隆"平均化" — 所有 BC 模型都会中招
**症状**: ACT/AWE 用 300 步完整轨迹 (专家 接近→抓取→转移→插入) 训练 4000 步收敛后, rollout 方向**学反/远离目标**:
- ACT(长轨迹): hand→peg 距离 0.255→0.379 (增大), 之前短数据 0.133→0.024 (接近 82%)
- AWE(长轨迹): 0.133→0.591 (远离), 动作恒定 x 负方向

**根因**: 300 步轨迹里各阶段速度指令方向相反 (Phase1 接近向左 → Phase5 插入向右), BC 回归学的是**全轨迹平均** → 平均后方向≈0 或漂移。ACT 7 步 chunk 回归 + AWE diffusion 都吃这个亏。
**唯一免疫**: 蒸馏 MLP (39D 坐标直接映射, 单步条件反射, 无时序平均) — 抓起 6/10 插入 3/10。
**教训**: 提升插拔不要盲目加长轨迹; 要么用短轨迹 (只含接近+抓取段), 要么 MLP 蒸馏路线。

## metaworld 远起点 (--far) 不可行 — 三条路全失败
1. `env.step(delta)` 手动移手到远处: 40 步后手只移到 (-0.006,0.569), 目标 (-0.05,0.3) 没到 — **关节限制, 手起点基本固定**
2. 官方专家远起点: 手被移远后 `SawyerPegInsertionSideV3Policy` 状态机失效, d_peg 0.282→0.266 拉不回 (专家假设标准起点)
3. 手写多阶段专家远起点: 10/10 轨迹全丢弃 (升高 0.000 — 远移后 Phase 判断/抓取失效)
**结论**: peg-insert-side-v3 的起点距离上限 ≈ 0.24m (task 索引变化范围), 想学"更长接近"不可行 — 老倪"方向再长点怎么训练"的答案是**数据多样性 (不同 task 索引) + 短轨迹**, 不是远起点。

## AWE/VLA-Touch 评估反归一化 — eval_insert.py 两个分支都漏过
**症状**: AWE 评估 10/10 全 0 抓起, 距孔恒定 0.362 (与随机一致), 4 次评估结果完全相同 (动作没生效)。
**根因链**:
1. eval_insert.py 的 `hasattr(policy, "_cond")` 分支 (158-162 行) 输出后**无反归一化** (ACT 分支有 `act*asd+am`, diffusion 分支没有) → 归一化空间动作≈0 直接 env.step
2. **AWE 根本没有 `_cond` 属性** (实测 `hasattr(pol,'_cond')=False`) → 走 else 分支 (直接 forward), else 分支也漏反归一化
3. state 归一化用全局 `_load_stats()` (旧数据 stats.json) → 与 AWE checkpoint 自己的 s_mean/s_std 错位
**修复 (2026-08-08 已落地 eval_insert.py)**:
```python
# state 归一化: AWE/VLA-Touch 用 checkpoint 自己的 s_mean/s_std
_sm, _ss = sm, ss
if hasattr(policy, "stats") and policy.stats and "s_mean" in policy.stats:
    _sm = np.array(policy.stats["s_mean"], dtype=np.float32)[:st_dim]
    _ss = np.array(policy.stats["s_std"], dtype=np.float32)[:st_dim] + 1e-6
st_n = (st_raw - _sm) / _ss
# 动作反归一化: _cond 分支 AND else 分支都要加
if act.size == 4 and hasattr(policy, "stats") and policy.stats:
    _st = policy.stats
    _std = np.array(_st.get("a_std", _st.get("action", {}).get("std", np.ones(4))), dtype=np.float32)[:4]
    _mean = np.array(_st.get("a_mean", _st.get("action", {}).get("mean", np.zeros(4))), dtype=np.float32)[:4]
    act = act * _std + _mean
```
**stats 键名**: AWE model.pt 的 stats = `a_mean/a_std/s_mean/s_std` (不是 action.mean/std); train_awe_zflow.py 302 行保存. 修复后动作变化 (real [-0.5,-0.06]→[-0.985,-0.1]) 但方向仍反 (长轨迹平均化, 见上)。

## 夹爪辅助 (grip_assist) 反而破坏纯模型评估
MLP 纯模型评估 抓起 6/10; 加 `d_hp<0.06 → act[3]=-1` 强制闭合后 → **0/10** (辅助覆盖模型输出, 整体动作错乱)。**教训: MLP 自己学会了夹爪时机, 别用启发式覆盖; 评估用纯模型输出 + clamp [-1,1]**。

## MLP 蒸馏插拔成功视频 — seed 选择法
- 15 seeds 扫: seed1/5/10/14 插入成功 (最近距孔 0.027/0.010/0.012/0.004m), seed14 最佳 4mm
- 出"插拔成功"演示视频先扫 seed 找成功帧, 不要硬跑 seed0
- 视频模板: 左面板真实画面 (手-peg 距离 + 夹爪状态标注) + 右面板 TREND 距离曲线 (黄线 + 绿色阈值线) — **老倪"这视频也没动啊"→ 要能看到趋势; 双面板趋势图是正解** (metaworld 速度控制衰减, 画面位移小但曲线下降清晰)

## 训练/评估进程卡死排查 (本会话三次)
1. **grep 管道缓冲吞日志**: `python ... | grep -E '...'` 后台跑时 grep 全缓冲 → process log 看不到进度 → **重定向到文件**: `python -u ... > /tmp/x.log 2>&1` (nohup 后台 + 轮询 tail)
2. **importlib.reload 破坏模块状态**: eval_latest 里 `importlib.reload(eval_insert)` 后 load_policy 返回 None → **别 reload, 直接重新 import 或传函数参数**
3. **HF 权重下载卡死**: SmolVLM2-500M-Video-Instruct 35/38 文件 incomplete, 官方源 + hf-mirror 都失败; `rm -rf *.incomplete` **误删已下载 blobs (2.4G→245M)** → 离线模式 (HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1) 加载失败因为缓存不完整 → **下载大权重用 `hf_hub_download` 单文件断点续传, 别 rm .incomplete**; AWE 的 SigLIP 权重缓存完整 (768M) 所以离线模式直接成功

## AWE 训练 max_frames 默认 200 太少
train_awe_zflow.py `load_data(root, max_frames=200)` 默认只取 200 帧 → 3600 帧数据只用 5.6%。加 `--max-frames` 参数 (默认 2000), 全量训练传 3600。
