# Rollout 推理修复 (rollout_video.py, 2026-08-07 实测三根因)

现象: 视频对比里模型"不动" / 动作均值≈0 / 推理异常日志。三个独立根因全部实测修复:

## ① V3 环境 obs 是 dict → np.asarray(dict) 全零 (最隐蔽, 影响所有模型)

`metaworld` V3 环境的 `obs` 是 **dict** (`{"observation.state": ..., "observation.image": ...}`), 不是裸数组。
旧代码 `st_vec = np.asarray(obs)` → dict 变 0 维 object array → `ndim != 1` → **state 全零** → 所有模型推理异常/动作≈0。
```python
if isinstance(obs, dict):
    _st_raw = np.asarray(obs.get("observation.state", np.zeros(st_dim)), dtype=np.float32)
else:
    _st_raw = np.asarray(obs, dtype=np.float32)
st = _st_raw[:st_dim] if _st_raw.ndim == 1 and _st_raw.size >= st_dim else np.zeros(st_dim, dtype=np.float32)
```
注意 V3 的 `env.reset()` 返回 `(obs, info)` 且 obs 可能 dict 也可能裸数组 (环境/版本差异) — 一律按类型兼容写。

## ② stats 归一化 39D vs 3D 广播 (numpy ValueError, ACT/AWE)

`policy.stats["s_mean"]` 可能是旧训练的 3D, 而 state 是 39D 完整观测 → `(39,) - (3,)` 广播错。
```python
sm = np.array(policy.stats["s_mean"], dtype=np.float32)
ss = np.array(policy.stats["s_std"], dtype=np.float32) + 1e-6
if sm.size >= st_dim:
    sm, ss = sm[:st_dim], ss[:st_dim]
else:
    sm = np.pad(sm, (0, st_dim - sm.size))
    ss = np.pad(ss, (0, st_dim - ss.size)) + 1e-6   # 补零区必须 +1e-6, 否则除 0 → 动作 NaN
st = (st - sm) / ss
```

## ③ ACT 39D 完整观测 = robot(3) + env(36) (torch mat1/mat2 广播)

ACTPolicy 期望 `observation.environment_state` (env 投影 `encoder_env_state_input_proj`)。39D 单输入直传会内部广播错。
从**权重维度**判断拆分 (不依赖 config 的 input_features, 实测 config 常没有该键):
```python
_env_proj = None
if hasattr(policy, "model") and hasattr(policy.model, "encoder_env_state_input_proj"):
    _env_proj = policy.model.encoder_env_state_input_proj.weight.shape[1]
if _env_proj and st.shape[0] >= 3 + _env_proj:
    batch["observation.state"] = st[:3]
    batch["observation.environment_state"] = st[3:3 + _env_proj]
```

## 调试技巧
- rollout 的 except 块加 `traceback.print_exc(limit=3)` 定位 (异常消息本身常是误导, "39 vs 3" 可能是 numpy 广播也可能是 torch 维度)。
- 动作验证: `np.abs(np.load(actions.npy)).mean()` — 正常学习模型 0.15-0.3; 插销模型 (peg 数据) 0.56; 推理异常 ≈0.0001。帧间均差 (`np.abs(frame0-frame59).mean()`) >1.5 才算"动"。
- `rollout_video.py` 的 `load_policy` 返回 **tuple** `(policy, label)` — 取 `[0]`。
- metaworld 相机: 插销场景必须 `--camera corner2` (默认 corner 看不到插槽); 旋转用 `--rotate-ccw` (k=2 = 180°)。MLP/专家旧视频是 corner2+rotate 生成, 重新生成必须同参数否则视角不一致。

## 插入成功检测 (tools/rollout_peg_check.py)
```python
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
# 判定: peg 抬起 (site_xpos pegGrasp z > 起始+0.05) 且 距 hole site < 0.05m
peg = env.data.site_xpos[env.model.site("pegGrasp").id]
hole = env.data.site_xpos[env.model.site("hole").id]
```
多 seed 跑 N 次统计成功率。官方专家基线 85%。

## 插销数据集生成 (tools/gen_peg_data.py)
- 官方专家: `from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy`
- 采样成功轨迹 (含图像 128² + env._get_obs() 39D state + 4D action) → train/val.npz
- 失败轨迹提前终止 (150 步) 加速; 实测 30 成功 eps / 41 尝试 (73%), 5850 帧
- 图像: `obs["observation.image"]` (V3 dict) 或 `env.render()` 兜底, CHW float(0-1)
- 已有 `data/metaworld_peg` (8-06) 只有 state+action **无图像列** — VLA 不能用, 必须重新生成含图的
- npz → lerobot 格式: `tools/npz_to_lerobot.py --npz train.npz --out <dir> --task "..." --fps 10 --episode-frames 200`
