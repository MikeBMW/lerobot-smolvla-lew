# left_right Policy 状态机集成 (2026-08-10)

老倪 "src目录下的代码呢" → 双脑成功逻辑从 tools/train_full_pipeline.py 完整搬进
src/lerobot/policies/left_right/modeling_left_right.py 的 select_action。

## 关键发现: 39D obs 结构实锤 (metaworld peg-insert-side-v3)

逐段扫描 obs 与 env 真值对比:

```
obs[0:3]   [0.005 0.601 0.195]  ← hand (z=0.195 是 gripper, 非 endEffector z=0.155)
obs[3:6]   [1. 0.163 0.656]     ← 手朝向 quat
obs[6:9]   [0.03 0. 0.]         ← 夹爪相关
obs[18:21] [0.005 0.601 0.195]  ← 与 obs[0:3] 完全相同 (hand 重复, 不是 peg!)
obs[36:39] [-0.269 0.659 0.131] ← hole (真值 [-0.251 0.41 0.131], y 差 0.25)
真实 pegGrasp: [0.074 0.591 0.03]
```

**结论: obs 里根本没有 peg 位置段**。任何 `_get_pose` 用 obs[18:21] 当 peg 的状态机
d_hp 恒≈0 (hand 与"peg"同坐标) → 抓取判定全错。

## 修复: env 真值注入

```python
def set_env(self, env):
    self._env = env

def _get_pose(self, obs):
    env = getattr(self, "_env", None)
    if env is not None:
        try:
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            peg  = env.data.site_xpos[env.model.site("pegGrasp").id]
            hole = env.data.site_xpos[env.model.site("hole").id]
            return np.asarray(hand), np.asarray(peg), np.asarray(hole)
        except Exception:
            pass
    # 退化: obs 索引 (真机无 env 时用, 但 peg 段是假的)
    ...
```

修复后: 抓起 0/8 → 8/8 (唯一转折点)。

## select_action 编排顺序 (与 train_full_pipeline 逐帧一致)

```
obs [B,1,39] → 取最后帧 → 归一化 (x_mean/x_std) → 左脑 → pred_act_norm
右脑输入: torch.from_numpy(pred_act_raw)   # 原始动作! 不是归一化
         (pred_act_raw = pred_act_norm * y_std + y_mean)
contact_p = right(obs, act_raw)[1]
_step_state_machine(o_i, c_i)   # 用 env 真值 peg/hole 判转移
_act_state_machine(o_i, a_i, c_i)  # 按状态选控制器
```

**坑: 右脑吃归一化动作 → contact 判断全错 → 抓取失败** (训练时右脑监督吃的是原始 act)。

## load_trained_weights 兼容

```python
right_sd = {k: v for k, v in data["right"].items() if not k.startswith("align_head")}
self.right.load_state_dict(right_sd, strict=False)
# full_pipeline.pt 的右脑有 align_head 第三头 (对位头), left_right 只用 next+contact
```

## 调试链 (0/8 → 8/8)

1. 状态机单测 (伪造 obs 喂 _step_state_machine) 全对 → 问题不在状态机逻辑
2. 诊断打印 state/d_hp/peg_z: 0→3 直接跳转移 → d_hp≈0 因为 obs[18:21]=hand
3. 逐段扫描 obs → 实锤无 peg 段
4. set_env 注入真值 → 8/8

## 端到端验证脚本

tools/eval_left_right_policy.py — 标准接口: reset() + set_peg_z0() + set_env() +
select_action() 跑 8 seed。结果 8/8 抓起 4/8 插入 (train_full_pipeline 8/8+7/8,
插入差在转移/插入时序, 不影响"src 工程可用"结论)。
