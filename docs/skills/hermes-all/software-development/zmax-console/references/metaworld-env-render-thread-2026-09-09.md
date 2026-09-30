# metaworld env 单例 + mujoco 渲染线程亲和 (2026-09-09 晚, L3 "直线上升" 排查终局)

症状: GUI 真实化第二轮起 YOLO 检出率 **0%**(0/2 → 0/3952 全 0), 阶段卡"接近",
距离孔位恒定 **9.9m**, 2000 步未完成。用户以为 L3 性能回退/要重训 smolvla —— **不是**。
指纹口诀: **检出率 0% + 距离 9.9m = 渲染黑帧 → 查渲染线程 / env 生命周期,
先别碰模型/控制代码, 更别提重训** (full 模式 CLI 全新进程实测 100% 检出正常)。

## 根因 1: env 是进程级单例, 绝不 close (09-09 自引入回归实锤)

`state_space_sim_real.py _make_env()`: 模块级 `_ENV = None`, 首次建 env 后全局复用,
跨轮靠 `_reset(seed)` 重采布局 (metaworld reset 忽略 seed → 引擎先 `np.random.seed(...)`
再 reset, 见 09-04 修复)。**任何轮结束/失败都不得 `env.close()`**:
- close 单例 → `_ENV` 还指向已关 env → 下轮 `_make_env()` 返回 closed env →
  reset 部分工作但渲染全黑 → YOLO 0% → 手飞。
- 现场证据链: 加 finally close 后 GUI 第 1 轮 OK (新建) → 第 2 轮 0%; 删 close 后
  同线程连续两轮都 100% (probe_thread_env.py 对照)。
- 曾在注释里写"多轮 env 累积泄漏要释放"是**误判** — 单例设计下根本不累积,
  真正回归是 close 本身。教训: 动"生命周期/资源释放"代码前先确认对象是否进程级单例。

## 根因 2: mujoco renderer 绑定创建线程 (glfw/egl 都如此)

probe 实证 (`probe_gl_backend.py`, MUJOCO_GL 分别 glfw/egl 结果相同):
```
thread-A 建 env + 跑: 检出率 100%
thread-B 复用同 env 跑: 检出率 0%     ← 跨线程渲染黑
```
mujoco 离屏 renderer 的 GL/EGL 上下文与**创建它的线程**亲和, 同进程内换线程渲染必黑。
旧实现每轮真实化 `threading.Thread(target=_work).start()` 新线程 → 进程内第二轮起
全部黑帧 (GUI 每轮新线程 = 每两轮坏一次, 重启 GUI 只救第一轮)。

## 终态修复 (2026-09-09 v5.4.2 后续): 进程级单线程池

simulink_module.py:
```python
import concurrent.futures as _cfutures
# 模块级 (import 区后):
_REAL_SIM_EXECUTOR = _cfutures.ThreadPoolExecutor(max_workers=1,
                                                  thread_name_prefix="real-sim")
# _start_real_sim 提交 (替换 threading.Thread):
_prev = getattr(self, "_real_future", None)
if _prev is not None and not _prev.done():
    self._log("⏳ 上一轮真实化仍在收尾 (单线程池) — 先 ⏹ 停止, 再点 ▶ 运行")
    return
self._real_future = _REAL_SIM_EXECUTOR.submit(_work)
```
- 原理: 池唯一线程 = 首个真实化建 env 的线程 = **永久渲染线程**, 之后每轮同线程
  复用 env → 渲染永远正常 (CLI 验证: 池连续两轮都 100% 检出)。
- stop_sim/重启轮询从 `_rt.is_alive()` 改 `_fut.done()` (≤10s + processEvents, 同款);
  abort 机制 (sim._abort → run 循环 break) 不变。
- submit 前查 `_prev.done()` 防排队双写 `self._real_tr` (单线程池排队会顺序执行两个
  _work, 各自 _on_real_poll 交错)。
- 验证脚本 `probe_single_pool.py`: ThreadPoolExecutor(1) 提交两轮 → 两轮都 100% 检出。

## 关联 (同指纹家族)

- YOLO 0% 也可能来自 concat 0D 崩溃轮 (np.concatenate dims, `_peg_cur` 变 0D) —
  防御 = detect_3d 输出形状守卫 (size!=3 丢弃保旧估值) + 拼接兜底置零, 见
  perception-shape-guard-2026-09-09.md。排查先看 stderr traceback 行号, 别只看症状。
- 排查工具: 命令行短跑对比 (全新进程 insert/full 各 100% = 代码正常, 问题在 GUI
  进程状态) → 再查同进程第二次/跨线程是否复现 (probe_thread_env.py 思路)。
