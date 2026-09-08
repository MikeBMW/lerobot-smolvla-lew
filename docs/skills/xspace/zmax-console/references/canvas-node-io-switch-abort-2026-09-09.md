# 画布节点 I/O 完整性 · 开关节点 · 引擎线程停止 (2026-09-09)

老倪系列反馈: ①状态空间画布节点字体大/挤(二次) ②🧠流形专家预测器"没有输入输出" ③🧭能力档位位置错/无开关 ④选 L4 后⏭单步自动跳回 L2 ⑤点🔄重启跳到运行又崩 (mujoco Segfault)。

## 1. "节点没有输入输出" 四查 (ssmani_exp 案例)
背景: 09-08 predictor 真实接入流形(引擎每帧真调 predict_manifold), 但画布节点 ssmani_exp 入0出0、node_logic/simulink_module grep **零匹配**、引擎 io_trace 无其 channel → 播放/单步永远"没输出"。

- **flow JSON 节点存在 ≠ GUI 有任何逻辑**: `grep -n "ssmani_exp" node_logic.py simulink_module.py` → 0 匹配 = 纯摆设节点。
- **执行却"通"的假象**: 节点名 "🧠 流形专家预测器..." 含注册关键词 "流形专家"(挂在 ss_pred, _EXTERNAL_LOC → predictor_layer.py class WorldModelPredictor)→ match_node 最长匹配兜底 → 双击/右键能执行 node_ss_pred。逻辑在, 但画布没接线、数据总线没数据。
- **修复四件套**: ①flow links 接线(入: ssvlm 潜空间 z / ss2d3d 几何 z R7; 出: →ssmani_c / →ssmani_p "预测流形 (JEPA)"); ②引擎 `_io_snapshot` 加同名 channel (key=画布节点名前缀, 与 data_world.module() 前缀匹配对齐; 数据从现成 dict 取——_mani_out['pred'] 的 manifold 6D, 需在 predict 调用处把 z7/a4/pred 存进 _mani_out); ③布局按用户语义重排 (L4 行 x: exp=40 / c=410 / p=690, 预测器在接触/性能流形**前面**); ④引擎每帧真算的旁路结果只存 tr['mani_pred'] 不够——不进 io_trace 则 DataWorld 无帧数据, 播放节点仍空。
- **校验器 FAIL 先对照备份**: 重复线 (sworld→ssvideo 两条) 在改动前备份同样 FAIL = 历史遗留, 顺手删旧留新 (label 详的一条) → ALL PASS。
- 证据口径: predict 每帧真调 = tr['mani_pred'] 帧数 == 步数 (80/80 帧非零)。

## 2. 能力档位重新设计 (三档 radio 开关)
用户: 位置应在**数据源层** (ssbg_data 行, 与 ssdata/ssmode 同排 y=-1450); "没有开关可以选择啊"。
- flow: x 560→600、y -409→-1450、name 精简 "🧭 能力档位"、params {cap_switch:True, cap_level:"L2"}。**type 保持 model**——加新 type 要 NODE_TYPES 三处同步 (simulink_module/validate_flow/simulink_ci), 用 params 标记 + paint 分支最省。
- paint (SimNodeItem.paint, drawRoundedRect 之后): `params.get("cap_switch")` → 自绘顶部标题 + 三档 radio 圆钮 (L2/L3/L4, 当前档 #ffd700 实心圆+实心点) + 每档小字 + 底部当前档 desc → return (跳过通用标题/徽章)。
- 交互三路统一走 `module._toggle_cap(node, level=None)`: ①**单击圆钮直选** = SimCanvas.mousePressEvent 左键节点分支内 hit-test (圆心 = scenePos + (12+i*cw+8, 37), ±14px) → `_toggle_cap(n.node, k)`; ②**双击循环** = on_node_activated 分支 `params.cap_switch → _toggle_cap(node)` (放 yolo_gate 分支后); ③右键"运行节点" → node_ss_cap 也先找同名 node 调 `mod._toggle_cap`, 防只切内存不重绘。
- **档位持久**: _toggle_cap 写 node.params.cap_level (画布重绘+保存不丢) + self._cap_level (▶运行消费); _start_real_sim 读档位**先扫画布 nodes** (params.cap_switch → cap_level), 兜底内存值 (重启 GUI 后 flow 里的档位仍生效)。

## 3. ⏭单步/▶播放"执行"开关节点 = 切档副作用 bug (L4 自动跳 L2 实锤)
- `_ss_order` / `_ss_step_order` 三处构建全是 `[n for n in self.nodes if n.get("type") != "row_bg"]` → 开关节点也在列; 单步 execute_node_logic → match_node("能力档位")→ ss_cap → node_ss_cap → 循环切档。
- **修: 三处构建点加 `and not n.get("params", {}).get("cap_switch")`** (_ss_step_order 单步 / _ss_order _real_finish / _ss_order _start_state_space_sim)。gate 类 (train_gate/yolo_gate/mode_switch) 无 _reg 不中招, 只有注册了 node 逻辑的开关会中。
- 通则: **开关/配置类节点只响应用户手动操作, 绝不进自动执行链** (它们的"执行"= 用户点击意图)。

## 4. 档位/模式字符串跨 GUI↔引擎大小写契约 bug
- GUI 档位大写 "L2"/"L3"/"L4" (_toggle_cap/node_ss_cap), 引擎 `RealStateSpaceSim.run(cap=)` 判 `cap == "l4"` 小写 → **L4 预算×2 (full 4000/insert 1000) 从未生效** (只有 _l3_mode 判断用大写集合, 掩盖了问题)。
- 修: 引擎 run() 开头 `cap = str(cap).lower() if cap else None` (GUI 不用改)。
- 通则: 跨层 (GUI↔引擎↔CLI) 传档位/模式字符串先 grep 两端字面量对照大小写/别名。
- 验证探针: cap="L4"(大写) 短轮 → 日志 "🏆 L4 自主恢复档: …预算 ×2" 即生效。

## 5. 🔄重启/⏹停止 mujoco Segfault = daemon 引擎线程未停 (09-09 崩溃实锤)
- 崩溃现场: `Fatal Python error: Segmentation fault`, 栈 `gymnasium mujoco_env._step_mujoco_simulation ← metaworld sawyer_xyz_env._reset_hand ← reset_model`。用户路径: ▶运行真实化中/后点 🔄重启。
- 根因链: _start_real_sim 引擎跑 `threading.Thread(target=_work, daemon=True)`(**无句柄**); stop_sim 只停 _real_poll_timer + 播放 timer (旧注释 "daemon 线程跑完即弃" = 坑); restart_sim = stop_sim() → 清缓存 → start_sim() 立即 new RealStateSpaceSim → **旧 env 线程还在 mujoco C 循环里, 新 env 又 reset → 同进程双 metaworld env 并发 → C segfault**。
- 修复三件套: ①引擎 `__init__` 设 self._abort=False, run() for 循环**首行** `if getattr(self,"_abort",False): log+break`; ②GUI 存句柄 `_th=threading.Thread(target=_work,daemon=True); self._real_thread=_th; _th.start()` (**别保留原裸 .start() 行——会双线程启动**, patch 时注意替换整块); ③stop_sim 开头: 从 `_real_sim_ref`/`_ss_last_sim` 取 sim → `_rs._abort=True`, 再 `_rt.is_alive()` + `QApplication.processEvents()` 轮询 ≤10s (同 worker 停止模式, UI 不冻结), 结束置 self._real_thread=None。
- 验证坑: R0 每步 ~1.5ms 太快, abort 竞争不过自然完成——**验证必须预置** `sim._abort=True` 再 run → 0 步即退 PASS; 或跑 R1 (vision 每步 ~0.5-1s)。
- 通则: GUI "停止/重启"按钮必须**真停**后台占用独占资源 (mujoco env/模型/端口) 的线程再允许重建, 禁止"起新的时候旧的还在跑"。

## 6. ZMAX_DEBUG=1: 断点进不去的隐藏开关
- 09-06 起 studio.py main(): `if os.environ.get("ZMAX_DEBUG")=="1": debugpy.listen(("127.0.0.1", 5678))` (桌面默认不开, 防 IsUnMapped 黑窗口)。**agent 用 python studio.py 普通重启 → 5678 未监听 → VSCode attach 失败 → 所有断点不命中** ("断点进不去" 根因)。
- 自证: 窗口标题 2s 后 "⚠️非调试模式"; `ss -tln | grep 5678` 无输出。
- 重启命令: `env DISPLAY=:0 ZMAX_DEBUG=1 <repo>/gui-venv311/bin/python studio.py`。**用户调试会话期间重启 GUI 一律带 ZMAX_DEBUG=1**, 并提醒重新 attach (重启杀旧调试会话)。
- 断点位置坑照旧: def 行/docstring 行不命中, 设函数体实际执行行。

## 7. 字体第二轮缩小 (192DPI, 09-09)
- Qt logicalDotsPerInch=192 (xdpyinfo 报 96 是坑; 用 gui-venv311 python + DISPLAY=:0 查 QScreen)。9pt=24px / 8pt=21px / 7pt=19px。
- simulink_module.py SimNodeItem.paint: row_bg 大字 fs=9 起下限 7 (原 10/8); ▤小标 9→8; 普通节点标题 `for _fs in (9, 8, 7)` (原 10/9/8); 徽章 & 悬停 ID 10→9。offscreen 96DPI 只验逻辑/拓扑, 像素验证必须真实 DISPLAY。
