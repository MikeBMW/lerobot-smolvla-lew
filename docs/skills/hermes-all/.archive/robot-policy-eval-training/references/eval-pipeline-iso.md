# 评估管道同构 bug 链 (2026-08-08 实测修复)

## 症状: 所有模型评估 0% 但手动 rollout 能动

5 个视觉模型 (ACT/SmolVLA/LEW/VLA-Touch/AWE) 长轨迹训练后评估全 0%，
距孔值=peg 初始到 hole 距离（0.352/0.291/0.319...每 seed 固定）——peg 从没被碰过。

## Bug 1: stats 归一化标量广播

**错误**: `_load_stats()` 读第一个候选 checkpoint（smolvla 的），标量广播到 39D
**正确**: 每模型 checkpoint 的 preprocessor 是**逐维** mean/std（39 个值）
```python
def _load_stats(policy_hint=None):
    _by_policy = {
        "smolvla": ["outputs/train/smolvla_peg_seg/checkpoints/004000/pretrained_model", ...],
        "act": ["outputs/train/act_peg_seg/checkpoints/004000/pretrained_model", ...],
        "vla_touch": [...], "awe_zflow": [...],
    }
    # VLA-Touch/AWE checkpoint 无 preprocessor → 直接用数据 stats.json
    if policy_hint in ("vla_touch", "awe_zflow"):
        return json.load(open("data/metaworld_peg_seg/meta/stats.json"))
```
- 标量检测: `if sm.size == 1: sm = np.full(39, sm[0])`（兼容旧 ACT 标量版）

## Bug 2: SmolVLA 图像尺寸 128 vs 64

config: `siglip_image_size: 64, num_vision_tokens: 64`
eval 里: `img_size = 64 if type(policy).__name__.lower().startswith("smolvla") else 128`

## Bug 3: AWE/VLA-Touch 无反归一化

diffusion 输出归一化空间动作，直接 env.step → 动作全错。
两个分支都要加（`hasattr(policy, "_cond")` 分支 AND else 分支）:
```python
if act.size == 4 and hasattr(policy, "stats") and policy.stats:
    _std = np.array(_st.get("a_std", _st.get("action", {}).get("std", np.ones(4))))[:4]
    _mean = np.array(_st.get("a_mean", _st.get("action", {}).get("mean", np.zeros(4))))[:4]
    act = act * _std + _mean
```
训练脚本存 `a_mean/a_std` 键名（不是 action.mean/std）。

## Bug 4: 45D 相对向量评估补全

```python
st_raw = np.asarray(obs, dtype=np.float32)[:39]
if st_dim == 45 and st_raw.size == 39:
    hand_pos = env.data.site_xpos[env.model.site("endEffector").id]
    peg_pos = env.data.site_xpos[env.model.site("pegGrasp").id]
    hole_pos = env.data.site_xpos[env.model.site("hole").id]
    rel_vec = np.concatenate([peg_pos - hand_pos, hole_pos - peg_pos])
    st_raw = np.concatenate([st_raw, rel_vec])
```

## 验证方法
- 手动 rollout 能动 (dist 下降) 但 run_episode 0% → 检查上述 4 点
- 评估动作与手动测试动作对比（评估动作应变化非恒定）
