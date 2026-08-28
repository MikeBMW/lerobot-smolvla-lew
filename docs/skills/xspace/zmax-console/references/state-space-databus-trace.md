# 状态空间数据总线 (CANoe Trace 风格接口监视) — 设计与坑 (2026-08-22)

老倪需求: 参考 CANoe Trace 窗口, 把状态空间"所有接口数据"显示成数据总线, 点运行看到数据流动。

## 三件套 (实现位置)

- 引擎 `state_space_sim.py`: `_io_snapshot(...)` 提取**单步** io 快照 (dict: 模块→{in/out:[(名,值)]}); `run(io_every=25)` 循环里抽样记录 `tr["io_trace"]` = [(t, io_dict), ...] (替代"只留最后一步"的 last_io; 保留 `tr["io"]`=最后一步兼容旧 ss_tree)。
- GUI `model_tree.py` `DataBusTrace`: QTableWidget 5 列 (时间/通道/接口/方向/数据), 右侧面板 cmb_view 新增「🔌 数据总线」(index 9)。
- 接线 `simulink_module.py`: `_start_state_space_sim` 开头 `bus.begin_stream()`, `_ss_tick` 每帧 `bus.feed(t, io)` (跟画布节点动画同步), `_ss_finish` 不再一次性 refresh。

## 双模 (CANoe 双模, 都要做)

- 🔁时间顺序: `append_snapshot(t, io)` 逐帧追加行 (数据流形态, 629/867 行)。
- 📌固定格式: `update_snapshot(t, io)` 信号固定行不变, 每帧只刷"时间列+数据列" (37/51 行; 首次建 `_fix_map` {(mod,dirn,name)→行号})。老倪原话"信号固定位置不变, 而时间变化"。
- `feed(t, io)` 按 `cmb_mode.currentIndex()` 分发到 append/update。`begin_stream()` 清空+重置 `_fix_map`(不强制切模式, 用户自由选)。

## 坑 (全部实测踩过)

1. **QTableWidget 一次性灌几百行 → 真实 GUI 假死 "not responding"**。offscreen 验证快 ≠ 真机快 (真实 viewport 重绘卡死)。修: `_ss_tick` 每帧追加 37~51 行, 绝不运行完一次性 `setRowCount(629)` 灌入。诊断: `sudo gdb -p <pid> -batch -ex bt` 看主线程若在 `poll` (Qt 事件循环) 说明已恢复, 卡死是瞬时灌入导致。
2. **提取 `_io_snapshot` 别留冗余**: 把原 `last_io = {...}` 大字面量替换成 `_io_snapshot(...)` 时, 旧 dict 字面量必须删干净, 否则每步构建两次 dict (功能对但脏)。
3. **字体调大必须同步 `setDefaultSectionSize`**: 17px 字体 + 固定行高 24 → 裁字 ("字大框小"同款坑)。17px 字配行高 34。数据总线规格: item 17px / 表头 15px / 行高 34。
4. **传感器融合 fuse_sensors 真实输入是 3 个**: `fuse_sensors(rgbd_feats(39D), force_6d, tactile_marker)` → obs = concat(视觉39, 触觉4)。force 只接触检测用**不进 obs**。io 快照里 in 别只写 force+tactile 漏了视觉主输入 (否则 obs 看起来"无中生有")。
5. **恒0维度灰/非零绿高亮 = delegate + QTextDocument HTML 渲染** (QTableWidgetItem 不支持单元格内部分着色; 用 `setItemDelegateForColumn` + `doc.setHtml` + `drawContents`, text 存 HTML span)。**但老倪反感绿色太多看不清 → 最终撤销, 数据列恢复正常显示**。

## 用户偏好 (硬性, 嵌入下次直接照做)

- **数据总线数据列正常显示, 不做花哨高亮** (老倪原话"别高亮了, 正常显示就行了")。向量就是普通 `[0.1, -0.06, ...]` 白色文本。
- **数据要"全"**: 数据流链路从头到尾补全 (感知层 5 模块 + 核心 9 模块 = 14 模块/51 接口), 别只显示核心层。感知层: 📦数据源(图像流RGB-D + 状态流39D)→🎯YOLO(检测框2D)→📐2D→3D(3D坐标)→🖐触觉(4D)→🔍AOI(质量门)。
- 数据总线字体要大 (17px 起), 看不清就说太小。

## 架构事实 (回答用户"这是啥/数据在哪"用)

- 状态空间 obs 43D = 39D 坐标 + 4D 触觉, **不含图像像素** ("坐标=逻辑主线, 图像=背景")。图像在感知前端被 YOLO+2D→3D 抽成坐标才进 obs; 真实图像帧在 Orin 摄像头 (硬件工具箱「📷摄像头实时画面」, datadrive.world/api/snapshot/latest), 不进 obs。
- 引擎仿真 39D = cur18(末端位置3+夹爪1+速度3+peg3+孔位3+孔姿态3+预留2) + prev18 + target3(=孔位)。**跟 node_logic 权威 39D (hand3+gripper1+peg7+pad7+prev18+hole3) 不一致** — 仿真引擎自己定的坐标布局。
- force 6D = [Fx,Fy,Fz,Tx,Ty,Tz], 简化只建 Fz 垂直接触力; 接近阶段 (末端-孔位水平距离 > D_CONTACT=0.02) 全 0 是物理正确, 接触后 Fz 从 0 涨到 ~0.12N (归一化 force_norm 峰值 ~0.8 @ 插入完成)。其余 5 维恒 0 (未建模, 非 bug)。
- 数据总线模块顺序 = 画布数据流拓扑: 感知层 → 传感器融合 → 前馈‖估计器 → 预测器 → 校正器 → 调度器 → 限幅 → 执行器 → 物理世界。补模块时同步补 `SS_MODULE_TO_NAME` (simulink_module.py, 选中行高亮连线用)。
