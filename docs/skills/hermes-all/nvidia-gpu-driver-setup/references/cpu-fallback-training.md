# 退回 CPU 训练操作要点 (Xorg 崩了 / GPU 加载失败后)

GPU 加载失败(reboot 被 Hermes 硬拦 + PCI remove 被审批禁)时, 退回 CPU 训练继续推进的完整要点。

## EGL 离屏渲染 (Xorg 崩了也能跑 mujoco/metaworld)
- `MUJOCO_GL=egl DISPLAY= <venv>/bin/python tools/train_full_pipeline.py ...`
- 脚本开头 `os.environ.setdefault("MUJOCO_GL","glfw")` 不会覆盖已设的 egl, 所以外部 `MUJOCO_GL=egl` 生效。
- 验证: env.render() 出真图 var>1000 (实测 3173); rgbd_tuple 返回 (rgb 480x480x3, depth 480x480) depth 值域 0.98~1.0 (mujoco 深度 buffer 原始值, 非米制)。
- 退出时 `Exception ignored in ... glCheckError EGLError` 是 OpenGL 上下文析构噪音, 无害。

## ultralytics 深度训练断点续训
- 给训练脚本加 `--resume` 参数: 加载 `outputs/<project>/<name>/weights/last.pt` 走 `model.train(resume=True)`, 从上次 epoch 继续。
- resume 继承 args.yaml 的 device/epochs 等参数, 不重头开始。
- 深度训练纯读图 + 前向反向, **不依赖 GL/Xorg**, Xorg 崩了也能训。

## metaworld env 初始化坑 (漏 set_task 直接 reset 报 AssertionError)
```python
import metaworld
mt = metaworld.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env._freeze_rand_vec = False          # ← 必须先关 freeze
env.set_task(mt.train_tasks[0])       # ← 漏这步 reset 报 AssertionError: _last_rand_vec is not None
env.reset(seed=seed)
env._freeze_rand_vec = True           # ← 复位后冻结随机向量
```
- 直接 `env.reset(seed=N)` (不 set_task) 报 `AssertionError: assert self._last_rand_vec is not None`。
