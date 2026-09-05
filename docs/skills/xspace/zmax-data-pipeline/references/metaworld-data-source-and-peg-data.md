# metaworld 数据源真相 + 光模块数据生成 + rollout 推理修复 (2026-08-07)

## 数据源真相 (老倪追问"696帧怎么来的/成功率1.1%/任务数50"的完整答案)
- `data/metaworld_mt50` = Meta-World MT50 基准 (49/50 任务), info.json **声明**
  2500 episodes/204806 帧/50 任务 (这是 HF 云端索引, 不是本地实际)。
- **本地只下载了 chunk-000 的 2 个 parquet 分片**: 879 帧 / 10 episodes /
  **只有 task_id=0** = "Pick up a nut and place it onto a peg" (螺母套销钉,
  老倪直观叫"套环")。成功帧标记: metaworld 的 `next.success` **只在 episode
  最后一帧 = 1** (位置 0.99), 10/10 轨迹全部成功 — 1.1% 是标记方式, 不是失败轨迹。
- `data/metaworld_act/train.npz` (696帧) + val.npz (183) = prepare_metaworld.py
  转换上面 879 帧 (20% 按 episode 划验证, 图像缩 128×128, state 4D 来自
  observation.state)。**训练数据是 nut-on-peg, 而 rollout 评估用 peg-insert-side-v3
  (光模块) — 任务不匹配 + 样本极少 (10 演示) = 插拔成功率瓶颈** (MLP 55%)。
- `data/metaworld_peg` (08-06 生成) 只有 state+action, **无 observation.image 列**
  → VLA 不能用, 别指向它。

## 光模块数据集生成 (gen_peg_data.py, 2026-08-07)
```bash
./.venv/bin/python tools/gen_peg_data.py --eps 30 --out data/metaworld_peg_v2
```
- 专家策略: `metaworld.policies.sawyer_peg_insertion_side_v3_policy.SawyerPegInsertionSideV3Policy`
  (`get_action(obs39D)`, 插入率 ~85%) — 与 distill_expert.py 同源。
- 环境: `mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")`
  (corner2 与对比视频视角一致); 图像 128×128 float32 [0,1] CHW。
- 只留成功轨迹 (`pegGrasp 抬起>0.05 + 距 hole<0.05`); 失败轨迹 150 步提前终止
  (渲染慢, 60 eps 会超时); train/val 按 episode 20% 划 (seed 42)。
- 输出: observations/states(39D `env._get_obs()`)/actions(4D) + meta.json。
- 生成后记得把目录加进 GUI 数据源候选 (simulink_module.py `_show_source_info` cands)。

## rollout_video.py 推理修复三连 (2026-08-07, 视频动作≈0 的根因)
1. **V3 env obs 是 dict 不是 numpy**: `np.asarray(obs)` → 0 维对象数组 → state 全零。
   修复: `obs.get("observation.state")` 解包。之前 2026-08-05 记录"V3 obs 是 numpy"
   是错的 (当时 render_mode 黑屏修复语境); V3 `env.reset()`/`step()` 返回 dict。
2. **stats 维度不匹配**: 模型 39D (完整观测) 但 `policy.stats["s_mean"]` 是旧 3D →
   `(39,) - (3,)` 广播 ValueError。修复: stats 维度不足 `np.pad` 补零, **ss pad 后
   +1e-6 防除 0 NaN** (动作出 NaN 的坑)。
3. **ACT robot/env state 拆分**: ACTPolicy 有 `encoder_env_state_input_proj`
   时 39D = robot(3) + env(36) → 拆 observation.state[:3] + environment_state[3:];
   判断用权重维度 (`encoder_env_state_input_proj.weight.shape[1]`) 不依赖 cfg
   (cfg 常无 input_features 键)。

## 视频方向/视角统一 (老倪"前5个反了/看不到插槽")
- 正确命令: `--camera corner2 --rotate-ccw` (rot90 k=2 = 180°; corner2 能看到插槽,
  corner 默认看不到)。
- MLP/专家视频 (rollout_mlp/rollout_expert_full) 是基准视角, 重新生成其他模型必须
  与它们同参数。老倪 08-07 先说"勿再转180"是旧语境 (当时原版已转), 重生成不带
  --rotate-ccw 反而会反 — **以 MLP/专家现成视频为准对齐参数**。
- `load_policy()` 返回 **tuple (policy, label)**, 用 `pol[0]`; 别直接 hasattr(pol, ...)。
- 帧间均差检测视频是否"动": 首末帧灰度均差 >1.5 有运动, >0.8 微弱, <0.8 没动;
  动作均值 (actions.npy) >0.05 为有效。

## 曲线恢复与续训 (2026-08-07)
- 曲线 json 被训练链启动清空后: 从 /tmp 训练日志 (vla4.log/retrain_awe.log/mlp3.log)
  用正则重新解析落盘 (秒级恢复), 或重训 (act 1000步≈1min, smolvla/lew ~9min/1000步)。
- lerobot 日志 "step:1K" → 先展开再解析; 正则 step 后加 `\b`。
- 续训用微调 `--policy.path=<ckpt>/pretrained_model` + 新 output_dir (resume 机制
  在 draccus fork 有 config_path 目录坑); 曲线合并新步偏移 +1000, setdefault 保旧步。
- 评分 (report _TAB) 与视频的一致性: 视频必须加载"最新**有效** checkpoint" —
  50 步中断的训练目录比 1000 步完整训练的"新" → rollout glob 最新会加载垃圾 →
  视频不动但评分最高 (AWE 案例)。清理垃圾目录 (rm -rf 50步目录) 后重 rollout 即可。
