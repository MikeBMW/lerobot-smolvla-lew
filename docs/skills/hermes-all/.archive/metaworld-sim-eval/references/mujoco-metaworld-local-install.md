# 本机 (U盘 Live USB) 装 mujoco + metaworld 与 mujoco 3.3 API 变化 (2026-08-23 实测)

## 用 uv 安装 (GUI 环境 gui-venv311 没 pip, 系统 python3 也没 pip)

```bash
UV=/home/ubuntu/.hermes/bin/uv
$UV pip install --python gui-venv311/bin/python mujoco      # → mujoco 3.12 (含 glfw/pyopengl)
$UV pip install --python gui-venv311/bin/python metaworld   # → metaworld 3.1.1, 强制降级 mujoco→3.3.0
$UV pip install --python gui-venv311/bin/python packaging   # gymnasium 依赖漏带, 必须手动补
```

坑:
- **metaworld 3.1.1 会强制降级 mujoco 3.12→3.3.0** (依赖 pin), 别惊讶版本回退, 3.3.0 同样支持 EGL/glfw 渲染
- **import metaworld 报 `ModuleNotFoundError: No module named 'packaging'`** = gymnasium 1.3 依赖没被 uv 自动带上, 手动补 packaging
- metaworld 3.1.1 **没有 `__version__` 属性**, 别访问

## mujoco 3.3 API 变化 (旧代码 `site_name2id` 已删)

- `model.site_name2id('pegGrasp')` 不存在了 (`AttributeError: 'MjModel' object has no attribute 'site_name2id'`) → 用 `model.site('pegGrasp').id`
- 取 site 位置: `pid = env.model.site('pegGrasp').id; env.data.site_xpos[pid]`
- 列全部 site 名: `[env.model.site(i).name for i in range(env.model.nsite)]`
- peg-insert-side-v3 的 site 名: goal/basesite/headsite/armsite/endEffector/rightEndEffector/leftEndEffector/mocap/pegHead/pegEnd/pegGrasp/hole/bottom_right_corner_collision_box_*/top_left_corner_collision_box_*

## metaworld 3.1.1 obs 结构 (与远程旧版不同!)

- **pip 最新版 metaworld 3.1.1 的 `env.reset()` 返回 array shape (39,), 不是 dict**
- 与主 SKILL.md "渲染黑屏"节记录的"本项目远程旧版 obs 是 dict (observation.state 39D + observation.image)"矛盾 = **版本差异**: pip 3.1.1 = array, 远程旧版 = dict
- 代码要 `np.asarray(obs, dtype=np.float64)` 双兼容, 别写死

## EGL headless 渲染 (GUI 进程内真渲染, 不依赖 DISPLAY/WSLg)

```python
os.environ['MUJOCO_GL'] = 'egl'   # headless 真渲染
os.environ['DISPLAY'] = ':0'      # 保险
env = mt1.train_classes['peg-insert-side-v3'](render_mode='rgb_array', camera_name='corner2')
```

- EGL 退出时 `Exception ignored in __del__ / EGLError` 是**无害析构噪音** (进程退出清理 OpenGL context), 不影响渲染结果, 过滤即可
- 判定真图: `np.asarray(img).var() > 1000 且 unique > 50` (EGL var≈1599, glfw var≈4778, metaworld peg 场景 var≈3190)

## 官方专家策略跑真实插拔轨迹 (数据总线真实渲染用)

```python
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
pol = SawyerPegInsertionSideV3Policy()
env._freeze_rand_vec = False
obs, _ = env.reset(seed=1)   # seed1: 距孔 0.35→0.14m, seed3: 0.23→0.09m, 均插入成功
for _step in range(150):
    act = np.asarray(pol.get_action(obs), dtype=np.float64)
    obs, _r, _term, _trunc, _i = env.step(act)
    obs = np.asarray(obs, dtype=np.float64)
```

- 轨迹 peg 距 hole 距离单调下降 (接近→抓取→对准→插入), 可缓存 dist 序列做"插拔进度"映射到数据总线时间点 (见 zmax-console 技能 §18 真实渲染)
- get_action 会打 `UserWarning: Constant(s) may be too high` 属正常 (环境内部 clip 到 [-1,1])
