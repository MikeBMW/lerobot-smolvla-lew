# Simulink 模式 (GUI 控制台) — 2026-08-01

## 架构

```
tools/gui/simulink_module.py   # 独立模块 (~800行, 不依赖 studio.py)
tools/gui/studio.py            # 4 处集成点 (见下)
simulink-spec.md               # 双仓库共享规范: lerobot-smolvla-lew + zmax-website
zmax-website/comfyui.html      # web 端画布编辑器 (同 N/L 数据结构)
```

设计目标: 对标 Simulink — 0帧起手(空画布) → 左侧模块库点击添加 → 输出端口→输入端口拖拽连线 → 双击节点打开 Block Parameters → ▶运行/单步/停止 (拓扑序执行)。web comfyui.html 同步同一交互与 JSON 格式。

## studio.py 集成点 (5处, 缺一不可)

1. **import**: `from simulink_module import SimulinkModule` (在 version_sync import 后)
2. **首页卡片**: HomeWidget modules 数组加 `("simulink", "🎛️", "Simulink模式", ...)`
3. **modules 字典**: `"simulink": 11` (最后页)
4. **页面挂载**: `self.simulink = SimulinkModule(); self.simulink.flow_synced = self.on_flow_sync; self.stack.addWidget(self.simulink)` + `on_flow_sync(flow)` 方法 POST 到 `https://datadrive.world/api/comfy/task`
5. **`_on_nav` 状态栏 names 列表**: 12 项, 与 modules 字典顺序一一对应 `["首页","架构","数据集","训练","评估","硬件","配置","监控","插拔场景","版本同步","推理服务","Simulink"]`。**漏掉 → 点导航 IndexError: list index out of range (Simulink idx=11 实测崩溃)**。

> 注意: merge -X theirs 会同时吞掉第 5 处。恢复集成点时 grep 全部 5 处, 别只查前 4 处。

## JSON 规范 (与 web 完全一致)

```json
{"format":"zmax-simulink","version":"1.0","name":"flow","sim":{"dt":0.01,"t_end":10},
 "nodes":[{"id":"n<ts><rand3>","type":"hardware","name":"Orin Nano","x":80,"y":100,"w":150,
           "params":{...},"inputs":[{"id":"in1",...}],"outputs":[{"id":"out1",...}]}],
 "links":[{"id":"l<ts><rand2>","f":"n1","t":"n2","f_port":"out1","t_port":"in1"}]}
```

- type 5 类: condition紫#a371f7 / model蓝#58a6ff / action绿#00d4aa / system黄#d4a800 / hardware红#ff4444
- 节点 id 规则与 web 相同: `'n'+Date.now()+3位随机`
- links 的 f/t 与 comfyui.html 的 `L=[{f,t}]` 兼容
- 模块库 LIBRARY 常量 (条件11/模型9/动作11/系统6/硬件8) 与 web comfyui.html 侧栏分组一致

## 关键类

- `SimulinkModule(QWidget)` — 主模块: 工具栏(运行/单步/停止/仿真时间/步长/导出/导入) + QSplitter(LibraryPanel + SimCanvas) + 底部日志
- `SimCanvas(QGraphicsView)` — 网格点背景, Ctrl+滚轮缩放(20%~300%), 中键平移, 输出端口拖线→输入端口松手连线, 点击连线删除
- `SimNodeItem(QGraphicsObject)` — 可移动节点, 左输入/右输出端口, 双击弹参数框
- `SimLinkItem(QGraphicsObject)` — 贝塞尔连线 + 箭头 (与 web draw() 同款三次贝塞尔)
- `BlockParamsDialog` — Block Parameters 弹窗, 按 params 类型生成控件 (bool→combo, float→QDoubleSpinBox, int→QSpinBox, str→QLineEdit)
- `_topo_sort()` — DAG 拓扑排序确定执行顺序 (剩余有环节点追加尾部)

## UI 结构 (对标 MathWorks 解决方案页, 2026-08-01 升级)

自上而下 5 层:
1. **Hero 标题条** (64px): 渐变背景 `qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0d1117, stop:0.6 #0f1a24, stop:1 #0d1117)`, 大标题 "Z-MAX 具身智能 · Simulink 模式" + 副标题 + 版本号。
2. **工作流导航条** (40px, 对标 MathWorks 6 大功能分区): 6 个 checkable QPushButton `① 访问·标注数据 / ② 仿真场景 / ③ 规划·控制 / ④ 感知算法 / ⑤ 部署 / ⑥ 集成·测试`。点击 → `_filter_library(key)` 高亮自身 + `self.library.set_filter(key)`。`WORKFLOW_TYPES` 常量映射 工作流→节点类型: data→hardware, scene→system, plan→model, percept→condition, deploy→model, test→action。
3. **工具栏**: ▶运行 / ⏭单步 / ⏹停止 + 仿真时间/步长 spinbox + 时钟 + 💾导出/📂导入。
4. **参考应用条** (38px, 对标 MathWorks 参考应用列表): `REFERENCE_APPS` 常量, 每个 `(名称, [(type,name,params),...], [(fi,ti),...])`。点击 → `load_reference_app()` (画布非空先弹确认) → clear + 横排 add_node (间距 260px) + add_link。
5. **主体**: QSplitter(LibraryPanel + SimCanvas) + 底部日志。

`LibraryPanel` 支持过滤: `set_filter(wf_key)` 设 `_current_wf` + `_rebuild()` 重建按钮列表 (保留 `self.v` layout 引用以便清空重建, 注意 takeAt+deleteLater 清空)。

## 陷阱

- **节点乱跑 / 鼠标点击失控 (2026-08-01 用户实测反馈 "node乱跑")** — QGraphicsView 节点编辑器 3 个根因, 全部要一起修:
  1. **SimLinkItem boundingRect 固定巨大矩形** (如 `QRectF(-200,-200,800,400)`) → itemAt() 用 boundingRect 做粗命中, 点击画布任意处都可能命中连线 → 误删连线/干扰节点。修: `shape()` 用 `QPainterPathStroker().setWidth(14)` 生成细长命中区 + `boundingRect()` 动态 `self._path().boundingRect().adjusted(-12,-12,12,12)`。
  2. **setDragMode(RubberBandDrag)** → 点击节点画的是橡皮筋框而非拖动节点 (ItemIsMovable 被 view 拦截)。修: `setDragMode(NoDrag)`。
  3. **连线 z 值 ≥ 节点 z 值** → 连线挡住节点。修: 连线 `setZValue(5)`, 节点 `setZValue(10)`。
  - 调试辅助: `path.elementAt(0)` 取曲线起点 (currentPosition() 返回终点); 验证命中区用 `canvas.itemAt(canvas.mapFromScene(pt))` 断言远处 None / 线中点 SimLinkItem / 节点中心 SimNodeItem。
- **节点联动拖动 (2026-08-01 用户二次反馈 "还是跟着动")**: 第一轮修复 (super() 后强制单选) 不彻底 — QGraphicsScene 在 mousePress 时**缓存所有已选中 movable items 为拖拽集合**, press 后改 selected 无效。最终方案: ① SimNodeItem **移除 ItemIsMovable** (scene 完全不参与移动); ② SimCanvas 接管: press 记录 `_drag_node` + `_drag_offset = p - rp` (节点主体, 先判输出端口), move 里 `setPos(p - _drag_offset)`, release 清空; ③ 选中管理: 非 Ctrl 点击节点清其他选中 + 选中自己, 空白 clearSelection, Ctrl 多选。验证见下方 offscreen 条目。
- **offscreen 验证真实拖动 (手动接管后可行, 2026-08-01 实测)**: 拖动由 SimCanvas 接管后, offscreen 下构造 QMouseEvent 直接调 `canvas.mousePressEvent/mouseMoveEvent/mouseReleaseEvent` 可完整模拟 press→move→release 并断言坐标变化 (10/10 PASS: A 动 B 不动)。`QEvent.MouseRelease` 不存在 → 用 `QEvent.MouseButtonRelease`。若未接管 (scene 默认拖动), QTest.mouseMove 在 offscreen 无效, 只能断言 `scene.selectedItems()` + `item.setPos()` 走 itemChange 同步。
- **QPen.setWidth 只收 int (PyQt5 严格类型)**: `pen.setWidth(2.4)` 在 paint() 里直接 TypeError 崩溃 — 用 `setWidthF(2.4)`。同类: QSpinBox.setRange/setValue 只收 int (float 用 QDoubleSpinBox, int 分支必须 `int(v)`)。**这类崩溃只在真实渲染路径触发** (offscreen 下 add_node/连线不崩, 但选中节点触发 paint 就崩), 所以验证脚本必须加 `item.setSelected(True); scene.update(); viewport().repaint(); app.processEvents()` 强制走 paint。
- **merge -X theirs 会覆盖 studio.py 集成点**: 2026-08-01 用 `git merge origin/main -X theirs` 合并 mac 分支后, Simulink 的集成点全被远端版本覆盖 (模块文件还在但页面消失)。**合并后必须 grep 验证集成点**: `grep -n "simulink\|Simulink" tools/gui/studio.py` (5 处全查)。
- **git rebase 冲突多时换 merge**: 历史提交与远端大改同一批文件 (studio.py 22处冲突) → `git rebase --abort` + `git merge origin/main -X theirs --allow-unrelated-histories` 更干净。但注意 -X theirs 丢弃本地对同文件的改动, 集成点要重加。
- **新增模块三处同步更新** (与现有规则一致): modules 字典 + stack.addWidget + HomeWidget 卡片。

## web 端同步 (GUI → datadrive.world)

- `on_flow_sync` POST `https://datadrive.world/api/comfy/task`，body 为 zmax-simulink flow JSON。
- nginx `location /api/comfy/ { client_max_body_size 500m; proxy_pass http://127.0.0.1:50058/; }` → 反代到 comfyui_mock_ecs.py (50058, 绑定 127.0.0.1)。
- **mock 服务常挂**: 50058 无监听 → 同步返回 502。重启: `bash /root/zmax-website/start_comfy.sh` (setsid nohup, 脚本已在 ECS 上)。
- **detect_model dict 兼容**: mock 的 `detect_model(nodes)` 原本 `" ".join(nodes)` 只收字符串列表；simulink 规范节点是 dict → TypeError: sequence item 0。已打补丁: `if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict): node_str = " ".join(str(n.get("name","")) for n in nodes)`。web 端被覆盖回旧版时按此重打。
- 验证: `curl -X POST https://datadrive.world/api/comfy/task -H 'Content-Type: application/json' -d '{"format":"zmax-simulink","nodes":[{"id":"n1","type":"hardware","name":"Orin Nano"}],"links":[]}'` → 200 且返回带 `"steps"` 数组的 task JSON。

## 验证

```bash
cd tools/gui && python3 -c "import ast; ast.parse(open('studio.py').read()); ast.parse(open('simulink_module.py').read()); print('OK')"
QT_QPA_PLATFORM=offscreen python3 - <<'EOF'
import simulink_module as sm
from PyQt5.QtWidgets import QApplication
app = QApplication([])
w = sm.SimulinkModule()
n1 = w.add_node('hardware','Orin Nano',80,100); n2 = w.add_node('model','SmolVLA',360,100)
w.add_link(w._items[n1['id']], w._items[n2['id']])
w.start_sim(); w.step_sim(); w.stop_sim()
print('SIM OK')
EOF
```
