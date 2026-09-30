---
name: robot-sim-mujoco-rendering
description: Use when mujoco/metaworld 仿真进程内多轮/多线程 env 渲染黑帧或做来料干扰鲁棒性测试.
---

# mujoco/metaworld 进程内渲染线程亲和 + env 生命周期 + 摆放干扰注入

Z-MAX 真实化引擎 (state_space_sim_real.py, R0/R1) 多轮调试沉淀。metaworld/gymnasium-mujoco 通用。

## 1. 渲染器绑定创建线程 (黑帧根因, 2026-09-09 实锤)

mujoco renderer 的 GL/EGL 上下文**绑定第一次创建它的线程**。GUI 每轮真实化若新建 worker
线程跑复用 env → 从第二轮起渲染黑帧 → YOLO 0% 检出 → 视觉全瞎 → 手飞 9.9m (特征距离!)。

- 探针验证: 同 env 线程 A 跑 100% 检出 → 线程 B 跑 0% (glfw/egl 都如此); 同线程两次都 100%。
- **修复**: 全部真实化任务提交到进程级单线程池 `ThreadPoolExecutor(max_workers=1)` —
  首个建 env 的线程 = 永远渲染线程。abort/join 语义不变 (future.done() 轮询替代 is_alive)。
- 防重入: submit 前检查旧 future 未 done 则拒绝 (单线程池排队会交错写结果)。
- 不要用"每轮新建 env"心智 —— 见下。

## 2. env 是进程级单例, 永远不要 close

`_make_env()` 返回模块级 `_ENV` 单例, 跨轮 `reset(seed)` 复用 (metaworld 官方语义)。
**close 单例 → 下轮复用已关 env → 渲染黑 → YOLO 0%** (自引入回归实锤, 表现为"重启 GUI 后
第一轮好、第二轮坏")。run 结束/异常都别 close; mujoco 资源随进程退出释放。

## 3. metaworld reset(seed) 忽略 seed

sawyer_xyz_env 的 reset(seed=) 参数被忽略, 布局由**全局 np.random** 决定 →
同 seed 在不同用例序列后布局漂移 (测试顺序耦合)。修复: reset 前 `np.random.seed(seed*7919+13)`
再 reset, reset 后 `_freeze_rand_vec=True` → 同 seed 恒同布局 (可复现, 非造假)。

## 4. 摆放干扰注入 (来料移位/转向鲁棒性测试)

peg 是 **free body** (qpos 7 维: 平移3+四元数4)。找它: 遍历 body 名 `"peg"` →
`body_jntadr[body_id]` → `jnt_qposadr`。**joint 名未必含 "peg"**, 别按 joint 名搜。
注入: qpos 平移 += Δxy(±4cm)/Δz + 四元数绕竖轴 yaw; 然后 `mujoco.mj_forward(model, data)`
→ 之后**现场几何/obs 全部重读** (决策链靠现场几何自恢复, 不写死常量)。
注入时机: env.reset 后、obs/geom 采样前。可控复现: 引擎加 `_jitter_override` dict 供回归矩阵。

## 5. 死局早停判据必须排除夹持转移段

"peg 漂移 >10cm → 布局死局换重试" 只在 **未夹持** 时判定 (抓起 peg 转移去孔位, peg 离初始
>10cm 是**正常**的; 不排除会误杀成功轮)。判据加 `not grasped`。

## 6. 干扰鲁棒性 = 多布局 attempts (来料重摆语义)

单次布局成功率非 100% (peg 被碰移成"冰球"死循环是典型失败模式) → 失败换新随机干扰布局
重试 ≤5 次直到任务完成 (真实工厂来料重摆语义)。每次 attempt 前 `_jitter_round += 1` 得新布局。

## 7. 模型部署 state_dict 必须架构一致

旁路模型 (如 WorldModelPredictor) 训练时 hidden_dim/num_layers 若与默认不同, 引擎实例化
必须显式传同一架构, 否则 `load_state_dict` 报 Unexpected key → 静默回退随机权重。
日志里 "predictor 注入失败: Unexpected key(s)" 即此。

## 关联

- 肌肉记忆标杆必须绑定摆放指纹 (布局变则失效关快通道) — 见 user-owned zmax-muscle-memory 坑 8。
- 诊断/回归纪律: CLI 多轮测试前 `SS_MUSCLE=0` 隔离固化库, 否则假回归。
