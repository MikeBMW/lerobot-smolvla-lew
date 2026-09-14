# L4 演示档 (L4Demo / gen_l4_demo_video.py) 调试实录 2026-09-10

老倪反复报 L4 档视觉 bug("夹爪乱动/没拿起/机械臂自己抬升/光模块一跳一跳/轨迹螺旋/没插入成功"),
每轮都断言"模型不对,要重新训练" — 但 **L4 档动作回路 = L4Demo 确定性演示控制器(伺服+治具),
无学习模型**, 全部根因是控制器代码 bug。本文件是架构事实 + 5 个已实锤坑 + 取证方法。

## 架构事实
- L4 档 GUI 链路: simulink_module cap=L4 → `RealStateSpaceSim(seed=104, vision=False, demo_l4=True).run()`
  → `_run_demo` importlib 动态加载 tools/gen_l4_demo_video.py 的 `L4Demo(seed=0, record=False).run_all()`
  → tr(转 list)→ ss_dreamview 3D 播放。GUI 每次运行读磁盘最新代码,**改 gen_l4_demo_video.py 不用重启 GUI**。
- L4Demo 8 段: ①来料转台90° → ②姿态适配抓取(绕z转90°抓横放) → ③治具校直回正 → ④标准抓取(试抓×3)
  → ⑤插入(真物理) → ⑥拔出 → ⑦AOI悬停 → ⑧光耦合(压电台)。段失败即中止(run_all ok_all &=)。
- `step()` 记录顺序(关键): 治具钉(_grab) → env.step(物理) → **记录 tr**(peg 物理位置) → 钉 peg(_grip_lock 覆盖 qpos,不重记录)。
  所以 tr 的 peg 是"上帧钉位经物理演化"位置; 治具↔钉夹切换帧 peg 记录会跳。
- make_env: `_freeze_rand_vec=True` 但 **metaworld 同 seed 仍有进程级物理微扰**(4 连跑步数 4810-5247 波动) —
  渲染版可能偶发失败(卡阻), 不是代码必现 bug。

## 🐛 已实锤坑 (全部有 commit)
1. **钉 peg 坐标系 (b6cb54bc)**: grip_lock 建立后 step() 钉 peg 用 `hx@rel_pos`(hx=手旋转矩阵)。
   手基座含 −90°Y 旋转(yaw90° 时局部 z≈世界 x/y) → 世界系"下方 3.7cm"偏移被转成"爪侧 3.4cm"偏移 →
   peg 瞬移悬在爪侧面外跟着飞 = 用户看到的"一跳一跳/像没夹住/轨迹横偏螺旋"。
   **铁律: 任何 yaw≠0 的夹持钉回必须 `_pin_world=True`(qpos = hand_xpos + rel_pos 世界系)**。
   ④段早已修(注释 2026-09-10),②段漏设 → 检查每段 grip_lock 前是否设 _pin_world。
2. **闭合力维持 (e6484274)**: ⑤解刚性锁真插拔后, ⑦ AOI 悬停 60 帧发 `zeros(4)`(act[3]=0 不维持闭合力)
   → 摩擦夹持滑脱 peg 掉台(z 0.081→0.008), 后续 AOI 空爪假 ok + ⑧ 治具瞬移吸附 = 假 success。
   铁律: 夹持转移/悬停段 act[3] 恒 1.0; AOI 报告加 peg 在位校验(z>0.05), 掉了中止不掩盖。
3. **动作编排观感 (625f04e3)**: ①避让 servo 到 0.34、③抬爪 0.36、转移段一律"+0.18/+0.20 再平移"
   → 手冲 0.457m 像"自己抬升"; ② 在 0.36m 高空空转 90° 像"自己转"。
   修: 避让/抬爪 0.20, 转移抬升封顶 0.32(逐处 min), 姿态旋转在任务点正上方(z≈pc+0.15)做,目的可见。
4. **插入卡阻随机失败 (427734a8)**: 渲染版偶发卡 11.7mm 中止(进程级微扰)。修: 卡阻(stall≥2 或深度<18mm)
   退 3mm + y/z 交替微调 1mm 重对孔再推 ×3(真机插拔同款)。验证 4 新进程全 ok, 其一真实触发重试。
5. **hand_yaw 记录通道 (5570f1c3)**: 夹爪角度必须取手局部 **Z 轴**(col2, yaw0≈世界+X, 随绕z线性);
   局部 X 轴≈旋转轴自身 → XY 投影≈0 → atan2 纯噪声 ±180°(143 处跳变) = 3D"夹爪乱动"。

## 🔍 取证方法 (CLI 复现+定位, 全部无渲染 ~2s)
```python
import importlib.util, os
os.environ.setdefault('MUJOCO_GL', 'egl')
spec = importlib.util.spec_from_file_location('_l4', 'tools/gen_l4_demo_video.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
d = g.L4Demo(seed=0, record=False)   # 复现路径与 GUI 一致(除 record/ensure_scene)
ok, meta = d.run_all()               # ~5000 步 2-5s
```
- **夹持恒定性**: 抬升窗内 `peg - hand` 差必须恒 ≈ 闭夹值(如 (-5,-1,-33)mm); 突跳 y±34mm = 钉 peg 坐标系错。
- **单帧跳表**: `‖peg[i]-peg[i-1]‖>5mm` 逐帧打 t/段/坐标 → 区分"伺服快移(连续小跳)" vs"钉夹切换瞬移(单帧大跳)"。
- **旋转事件表**: hand_yaw 差分(跨 360 包装)找 >0.5°/帧 连续段 → 只有 ±90°(②对准/③回正)是设计内。
- **真夹判据**: 闭夹后遍历 `m.contact` 找 pad↔peg(实测 7 处, 穿透 −3~−7mm)。注意 **pad 中点到 peg 中心
  几何距离 ~32mm 是正常的(两半宽之和), 不是夹空判据** — 曾误判。
- 修复后交付: 跑全链验证 + `gen_l4_demo_video.py` main()(record=True 渲染 ~2-4min) 出 reports/l4_demo_<ts>.mp4/.npz
  给用户当视频证据; reports 产物不入库。
- 渲染版 vs 无渲染版结果不同 → 先怀疑 metaworld 进程级微扰(坑 4), 别怀疑 ensure_scene(其 XML 生成确定,md5 恒定)。
