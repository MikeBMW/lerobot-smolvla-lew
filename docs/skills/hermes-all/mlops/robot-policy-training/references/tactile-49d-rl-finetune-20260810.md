# 触觉 49D 整合 + ACT RL 微调 (2026-08-10 完整踩坑实录)

## 背景
老倪指令: "改变数据，将触觉信号加进结构条件，在39D信号中整合设计，重新训练"
→ 39D + 6D 相对向量 + 4D 触觉 = 49D 结构条件, ACT/VLA-Touch/AWE 三模型重训。

## 结果（诚实）
| 模型 | 数据 | 抓起 | 距孔 |
|---|---|---|---|
| ACT 49D 触觉 | tactile2 (27ep×150帧) | 0/8 | 0.359 |
| VLA-Touch 49D 触觉 | 同上 | 0/8 | 0.365 |
| AWE 49D 触觉 | 同上 | 0/8 | 0.365 |
| 三模型 45D 无触觉 (对照) | grab6 | 0/8 | 0.361-0.365 |

**结论: 触觉信号加入对插拔能力零提升。瓶颈是架构无法泛化毫米级时序决策，不是信号缺失。**
验证充分, 止损, 勿再重复此方向。

## 触觉段设计
```
[0:39]  基础 39D (metaworld: hand/peg/hole 位置姿态 + 夹爪)
[39:45] 相对向量 6D: hand→peg(3) + peg→hole(3)
[45:49] 触觉 4D: 关节差分速度×10 (3D) + 力=速度范数×25 (1D)
```
接触时刻特征: 接近移动时 force↑ (0.24), 接触减速时 force↓ (0.006)。
抽查 parquet 确认触觉段有动态, 别全 0 (全 0 = gen 的 gen_state_ctx.prev_ee 没追踪)。

## 实现要点
1. **数据生成**: `gen_metaworld_data.py --rel-vec --tactile`
   - `gen_state_ctx` 全局容器追踪 prev_ee (main() 开头初始化)
   - 力模拟: `np.clip(np.linalg.norm(d_ee), 0, 0.2) * 25.0`
2. **训练脚本触觉提取** (train_vla_touch.py / train_awe_zflow.py load_data):
   ```python
   if st.shape[1] >= 49:
       tac = st[:, 45:49].astype(np.float32).copy()   # 数据自带触觉段, 与训练同构
   else:
       d = np.diff(st, axis=0, prepend=st[:1])        # 旧 fallback: 关节差分
       force = np.clip(np.linalg.norm(d, axis=1, keepdims=True), 0, 1) * 5.0
       tac = np.concatenate([d[:, :3]*10.0, force], axis=1)
   ```
3. **容器训练**: 独立脚本 (train_vla_touch/awe_zflow) 的 docker run **必须加 `-e PYTHONPATH=/app/src`**
   ——漏加 → 容器内秒退 `ModuleNotFoundError: No module named 'lerobot'` (EXIT=1 但 4 秒"完成"像没跑)。
   只对 lerobot_train 记得加、对独立脚本漏加是常见错。
4. **评估注册** (eval_insert.py, 新 policy 名三处):
   - `load_policy`: `policy in ("vla_touch","vla_touch_tactile")` / `("awe_zflow","awe_zflow_tactile")` / `("act","act_tactile")`
   - `_by_policy`: 加 `vla_touch_tactile`/`awe_zflow_tactile`/`act_tactile` 指向新 ckpt
   - `_load_stats`: `policy_hint.endswith("tactile")` → 用 `data/metaworld_peg_tactile2/meta/stats.json` (49D)
   - 不注册的症状: `operands could not be broadcast together with shapes (39,) (3,)` (stats 3D 标量错位)
   - 49D 评估时 state 组装: 39D raw → 现场补 6D rel (st_dim>=45) → 补 4D 触觉 (st_dim>=49, 零值占位)
5. **训练产物权限**: 容器 root 写 checkpoint 权限 0600 → 本地评估报 FileNotFoundError (权限伪装成不存在)
   → `sudo -n chown -R xspace:xspace outputs/train/<dir>` + `chmod -R u+rw,go+r`; reports/ 下 train_curve json 也一并 chown

## ACT RL 微调 (train_act_rl.py, PPO 仿 MLP)
- 结构: 39D obs → MLP ActorCritic (Tanh×2 + policy_head + value_head), 奖励=接近(-dist×2)+抓起(+10)+插入(+50)+步数惩罚
- **GAE bug**: `adv[t] = last_gae` 报 `TypeError: can't assign a numpy.float32 to a torch.cuda.FloatTensor`
  → 必须 `adv[t] = torch.tensor(last_gae, dtype=torch.float32, device=DEVICE)`
- **结果**: 40 iter 奖励 -80~-90 卡住, 0/6 抓起 → RL 学稀疏插拔奖励是死穴 (与网络结构无关, 强化已有结论)
- 输出: `outputs/rl_act/act_rl_ft.pt` (插入>=3 才保存, 本次未触发)

## 数据集修复链 (49D 数据 Invalid key)
gen --tactile 丢失败轨迹后三处元数据错位 (详见 lerobot-dataset-engineering #26):
1. data parquet episode_index 不连续 → 重编号 0..N-1
2. episodes meta dataset_from_index 累加 + frame_index = 全局段末帧号 (i*150+149)
3. info.json total_frames/total_episodes + **features.observation.state.shape=[49]** (漏改 → DatasetGenerationError: Couldn't cast)
4. stats.json observation.state mean/std 49 维
5. `rm -rf ~/.cache/huggingface/datasets` 清 schema 缓存
