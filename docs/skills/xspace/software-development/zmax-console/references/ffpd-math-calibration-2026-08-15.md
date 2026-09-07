# 前馈PD 数学化 + 现场标定系统 (2026-08-15)

覆盖: model_tree.py (analyze_system/_show_math/PoleZeroPlot/FreeResponsePlot/
PolePlacementWidget/StageCalibrationWidget) + simulink_module.py (z700_internal
绘制/连线动画) + flows/ff_pd_top.json。核心概念: 复平面设计 + 物理直觉 +
现场操作三位一体; 几何不变性 (逻辑结构固定, 换场景只标定 m/b/k/Kp/Kd)。

## 1. 前馈PD 二阶代数方程 (数学内核, analyze_system ff_pd 分支)

纯规则前馈PD (L2层, 无MLP, 可解析) 完整推导:
- 时域: m·ẍ + b·ẋ + k·x = F(t);  F = K_ff·r + Kp·e + Kd·ė (e = r − x)
- s域: [m·s² + (b+Kd)s + (k+Kp)]·X(s) = [Kd·s + (K_ff+Kp)]·R(s)
- 闭环: G_cl(s) = (Kd·s + (K_ff+Kp)) / (m·s² + (b+Kd)s + (k+Kp))
- **特征方程: m·s² + (b+Kd)s + (k+Kp) = 0 — K_ff 不进特征方程, 只移零点, 不改稳定性**
- 特征解: s₁,₂ = [−(b+Kd) ± √((b+Kd)²−4m(k+Kp))] / (2m)
- ωₙ = √((k+Kp)/m),  ζ = (b+Kd) / (2√(m(k+Kp)))
- 稳态: T0 = (F_gain+Kp)/(k+Kp), 静差 e_ss = 1−T0 (K_ff 补偿静差)

代码: `den = np.array([m2, b2+Kd, k2+Kp])`, `num = np.array([Kd, F_gain+Kp])`。

**参数读取铁律 (_p helper)**: 必须按节点名过滤 — 感知链曾有 Kp=1.0 (观测增益),
状态机 Kp=2.0 (比例增益), 不点名会读错。2026-08-15 起感知链改名 `K_obs`
(观测增益 y=Cx, 非 PID 组件), 四参数各司其职: K_obs=看 / K_ff=前馈 / Kp=比例 / Kd=微分。

## 2. 增益调度根轨迹 (5阶段特征根)

stage_pd 默认表: 接近(Kp=2.0,Kd=0.3) / 抓取(0.1,0.0) / 抬起(0.8,0.0) /
转移(0.6,1.2) / 插入(0.5,2.0)。**优先读画布 gain_schedule** (现场标定④写回状态机
节点 params, 有则标 "(标定)"): `_gs = sm_node.params.get("gain_schedule", {})`。
每阶段算 ωₙ/ζ/极点/类型 + **工程师验证指标**:
- Mp = e^(−πζ/√(1−ζ²))  (超调), Ts = 4/(ζ·ωₙ) (稳定时间±2%), Tp = π/(ωₙ√(1−ζ²))
- 手感比喻 (物理验证): 接近=拉紧的橡皮筋 / 转移=粘稠糖浆 / 插入=液压缓冲器

## 3. 复平面图 — 连续系统模式 (2026-08-15 修正)

**单位圆是离散系统(z域)判据, 连续系统应看左半平面(虚轴 Re<0=稳定)**。旧实现画
单位圆 + 固定 r 映射, s=−2 的极点会画出界。修正:
- 左半平面绿色高亮 (QColor(63,185,80,26) 半透明矩形)
- 虚轴红色虚线强调 (稳定性边界)
- **自动缩放**: `max_mag = max(|real|,|imag|) 全部极点/根轨迹` → `scale = r/(max_mag*1.25)`
- 极点×绿=左半平面稳定 / 红=右半平面不稳定; 零点○蓝

## 4. 自由响应曲线 FreeResponsePlot (特征解物理含义)

y(t) = e^{σt}·cos(ωt) + 包络线 ±e^{σt} (σ=衰减速率, ω=振荡频率)。
前馈补偿曲线: σ_eff = σ·(1+K_ff) (前馈把有效极点往左推, 更快冷静)。
"特征解=自由响应(推一下松手看怎么晃), 前馈=持续外力可补偿固有运动模式"。

## 5. 极点配置设计器 PolePlacementWidget (⚙️参数标定视图)

性能指标→增益 (不是凑增益):
- ζ = −ln(Mp/100)/√(π²+ln²(Mp/100));  ωₙ = 4/(ζ·Ts)  (±2% 误差带)
- Kp = m·ωₙ² − k;  Kd_eff = 2m·ζ·ωₙ − b;  画布动作 Kd = Kd_eff/Kp
- 💾 写入状态机.Kp + 动作.Kd (画布 z700_internal 节点)

## 6. 5步现场标定系统 StageCalibrationWidget (📐现场标定视图, QTabWidget 5 tab)

① 感知(给眼睛): 手眼标定 AX=XB → camera_to_robot 4×4 + Peg/Hole 参考坐标
   (39D 的 peg[18:21]/hole[24:27])
② 几何(给尺子): grasp_d_hp=实测×1.1 / transfer_tolerance=实测×0.8 /
   insert_tolerance=硬限位×0.5 → 💾 写入状态机节点
③ 辨识(给肌肉): 输入自由震荡相邻两峰幅值 → 对数衰减率 δ=ln(a1/a2) →
   ζ=δ/√(4π²+δ²) → b=2ζ√(mk) 自动填入 → 💾 写入动作节点 m/b/k
④ 整定(给节奏): 拖 ωₙ 滑块 + 各阶段 ζ (接近0.7/转移1.0/插入1.5/抬起0.8) →
   Kp=m·ωₙ²−k, Kd=2m·ζ·ωₙ−b 实时刷新 + 预期 Mp/Ts → 💾 写回状态机.Kp/动作.Kd
   + **gain_schedule 全表写状态机节点** (几何不变性)
⑤ 验证(给考官): 3步现象法 — 推拉测试(ζ手感) / 力尖峰(S型曲线) / 切换瞬间(听声音)
   - 回弹>2次 → Kd×1.5; 软绵绵 → Kp×1.3
   - 力尖刺 → Kd×0.7 + limit×0.8; 无力反馈 → Kp×1.3
   - 咯噔响 → ramp_ms=50 (速度斜坡平滑); 切换后静止 → transfer_tol=0.03

**导出 scene_config.yaml**: scene_name/hand_eye_matrix/peg_hole_ref/
三物理阈值/mbk/gain_schedule → ~/lerobot-smolvla-lew/configs/scenes/。
无 pyyaml 时手写 YAML 文本兜底 (GUI venv 可能没有)。

**快检表 (机柜贴纸)**: 感知像素偏差<2px / 几何倒角×1.1临界×0.8 / 辨识衰减震荡 /
整定2mm阶跃震荡↑Kd爬行↑Kp / 验收: 超调<5%·回正≤1.5次·力峰<10N·无咯噔。
换新场景只重做 ②几何+⑤验证, 1h 内完成。

## 7. 几何不变性闭环 (2026-08-15)

标定④写回 gain_schedule → analyze_system 优先读画布表 → 数学分析/复平面图联动。
**状态空间设计 (_show_state_space) 与数学分析同源**: 不再硬编码一阶 A=[-1/T],
改由标定参数构造二阶可控标准型:
- a0=(k+Kp)/m, a1=(b+Kd)/m, b0=(F_gain+Kp)/m, b1=Kd/m
- A=[[0,1],[−a0,−a1]], B=[[0],[1]], C=[[b0,b1]], D=[[0]]
- 李雅普诺夫: AᵀP+PA=−I 用 np.linalg.solve 解 Sylvester (kron), P 正定=渐近稳定
- 可控性 rank([B,AB]), 可观测性 rank([C;CA]) (矩阵幂累加)
- 无前馈PD画布时回退 1 阶 (T=0.1 右脑延迟近似)

## 8. z700_internal 内部模块 UI — 独立绘制 (多次重叠投诉的根治)

症状: 感知链/双脑/状态机/动作四框文字重叠。三层根因:
1. **load_flow_file 只写 dict 不写 item**: `n["w"]=spec.get(...)` 后 SimNodeItem
   的 self.w 是 add_node 创建时固定的默认值 → JSON 的 w/h 永不生效。
   修复: 加载循环里同步 `_it.w/_it.h` + prepareGeometryChange + update。
2. **通用 paint 路径残留绘制**: 默认类型标签"系统"(y=22) + 参数摘要(y=36) 与
   自定义三区布局重叠。
3. **最终方案 = 完全独立绘制**: paint 开头 `if params.get("z700_internal"):
   self._paint_internal(...); return` — 不碰任何通用路径 (标题/类型标签/端口/徽章
   全跳过)。_paint_internal 自己画: 背景渐变 → 标题(9px Bold) → 角色标签
   (▸前馈·观测 蓝) → desc(灰 7px 单行省略) → 参数区 (变量名青左 + 值白右,
   每行 15px) → 端口锚点 (in1 左/out1 右, 连线依赖不能省)。
   **注意独立分支在 paint 的 pal/status 定义之前 → 自取 THEMES[_CUR_THEME]**

## 9. 运行后自动刷新数学分析

start_sim 顶层分支 (z700_subsystem 检测) 仿真完成后:
`mt.cmb_view.currentIndex() >= 2` 时自动 `_show_math()` 或 `_show_state_space()`
(不弹窗不切页, 弹窗零容忍)。验证: start_sim 后 lbl_math 含 "纯规则前馈PD"。

## 10. 连线动画闪烁根治 (2026-08-15 "屏幕还是闪烁")

**根因**: 无 switch 节点的画布 (ff_pd_top) `_switch_active()` 恒返回 True →
运行后节点置 success → _wake_flow_anim 启动连线动画 → **动画永不停** →
每 80ms 全画布重绘 → VcXsrv 网络合成狂闪。之前只做了惰性启动 (不流动不启动),
没做"运行完停止"。

三层修复:
1. `_exec_topological` 设 `_topo_burst=True` 突发模式 → `_sim_node` 里
   `if not getattr(self,"_topo_burst",False): self._wake_flow_anim_all()`
   (12 节点逐个 success 不再逐个唤醒动画)
2. `_exec_topological` finally: `_topo_burst=False` + `_stop_all_flows()`
3. SimLinkItem.stop_all_flow() (停 timer + 清 offset) + 模块层
   `_stop_all_flows()` 遍历 _link_items; start_sim 顶层分支 + stop_sim 也调

验证: 运行前 0 动画 timer → 运行后 0 timer + 偏移全归零 + 节点 success 保留。

## 11. QDoubleSpinBox 精度坑 (2026-08-15 实测)

**默认 decimals=2 会把 0.055 四舍五入成 0.06** (setValue(0.055)→value()=0.06) →
标定几何阈值全错。修复: 自建 `_sp()` 一律 `setDecimals(4)`。
症状: 断言 `grasp_d_hp == 0.055*1.1` 失败但手算正确 → 先查 spinbox 精度。
