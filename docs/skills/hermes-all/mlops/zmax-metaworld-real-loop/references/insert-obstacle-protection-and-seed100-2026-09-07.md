# GUI ▶运行 seed100 失败排查 + 插入遇阻保护 (2026-09-07)

老倪报"点击运行后 3D 视图显示的操作不成功"。排查链 + 修复实录。
(注: 本技能为早期版, 与 zmax-real-closed-loop 重叠; 最新真实化坑位以 zmax-real-closed-loop 为准)

## 排查链 (3D/视频"显示失败"先分清数据源)
1. 3D 数据源: simulink_log.txt "🧭 3D 视图数据源: 程序执行轨迹 (sim.run() N 步)" =
   本次运行真实轨迹 (失败是真实的, 3D 忠实显示); "EPISODE 回放(预录)" = 播放 npz 存档。
2. 运行日志尾 "⚠️ 未完成 · 残差峰值 0.5002 · 接触概率峰值 0.98" → 真实失败。
3. **入口参数**: simulink_module.py `_start_real_sim` **写死 RealStateSpaceSim(seed=100,
   vision=True, vision_every=1)** → GUI 真实化每次同一失败布局。命令行同 seed 复现确认
   (`gui-venv311/bin/python tools/gui/state_space_sim_real.py 8 --seed 100`)。
4. 网页视频陈旧 ≠ 代码失败: curl -sI 看 content-length/Last-Modified; 曾停旧失败版而本地
   成功轮未上传 — GUI 上传读环境变量 ZMAX_ECS_PW, 重启丢变量静默失败。

## 数据 success 判定 vs 视觉分叉的参照系坑
- episode npz/meta: `target` = **手的目标位姿不是孔口**! 孔口 = hole_mouth, 孔底 = goal
  (插入沿 x)。拿 peg_head 比 target 会误判"偏 12cm 没插上"。
- 夹持后 peg_head() = 编码器推算 (x+_grasp_off0+head_off) ≠ mujoco 真值 site pegHead。
  **site−推算差 >10mm 且递增 = peg 已在夹爪内滑动** (seed100 实测 11.8→14.7mm), 此时
  "推算 peg 头对准孔口"是假对准 → 必顶孔沿。诊断: 同帧打印推算与 site_xpos[pegHead]。

## 插入遇阻保护 (sim_real 已实现, 防硬推脱手)
- 检测: 阶段=插入 且 grasped, depth(|peg头−goal|) 推而不进 (<0.5mm/帧 连续 5 帧) 且
  水平指令 |u[:2]|>0.03 → 顶住确认。
- 响应: 9 帧窗口 = 3 帧沿孔轴反向回撤 (0.08 松顶住应力) + y/z 轴交替 ±微调 (0.05≈1mm/帧
  扫掠) + 观察; 4 次事件 → sched._goto(5 转移) 重新对孔。
- 意义: 改前硬推把 peg 挤出夹爪 (gf→0 回退重抓 500 步耗尽); 改后遇阻即停不再脱手
  (日志 "🛡 插入遇阻#N" 实锤触发)。
- **z 对齐判据 4mm→1.2mm**: 孔间隙仅 1-2mm (peg 15mm 半径无倒角刚体), z_err 残留 2.6mm
  水平推必顶孔口上沿 (实测 z 校到 0.6mm 即推进 1.5mm)。

## 未解决: 夹持滑脱是 seed100 类深层根因 (边际收益递减)
- 成功轮与失败轮锁存瞬间 gripper 轨迹几乎一致 (0.70→0.52), 差异在夹持之后: seed100
  抬起/转移中 peg 滑出夹爪 (gripper 终值 1.0 = 掉件) → 回退重抓 → 500 步不够。
- 修复后 R0 10 轮 (seed100-109) = 5/10, 失败全为此类。抓取/夹持质量是抓取层面问题,
  插入保护覆盖不了。GUI 演示立即可解 = 不写死 seed100 (轮换/随机)。
