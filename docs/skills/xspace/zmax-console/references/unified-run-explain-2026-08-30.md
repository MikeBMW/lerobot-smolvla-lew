# 统一执行 + 代码讲解 + node_logic 维护 (2026-08-30)

## 1. node_logic.py 坏引用系统检查 (假激活排查)

node_logic.py 是热加载的节点逻辑库, 框架动作行调 `module.xxx(...)`。
方法名写错 → AttributeError 被 `_sim_node` 的 `except Exception: pass` 吞掉
→ **节点"运行成功"但动作从未执行 (假激活)** — 老倪最恨的"写了没接"。

检查命令 (gui-venv311, offscreen):
```python
import sys, re; sys.path.insert(0, 'tools/gui')
import node_logic, simulink_module
src = open('tools/gui/node_logic.py', encoding='utf-8').read()
calls = set(re.findall(r'module\.([a-zA-Z_][a-zA-Z0-9_]*)\(', src))
cls = simulink_module.SimulinkModule
print(sorted(c for c in calls if not hasattr(cls, c)))  # ❌ 坏引用
```
实测发现 2 处: `_toggle_source_node` (数据源) / `_set_yolo_gate_ctx` (YOLO开关)。
修法参照 `_toggle_train_gate_ctx(name, ...)` 模式: 新增 `_toggle_source_ctx(name)`
按节点名 `for n in self.nodes: if n.get("name") == name: self._toggle_source(n)`。
**注意 `_toggle_source` 要 node dict, 不能传名字符串。**

## 2. match_node 最长匹配坑 (注册词必须与模板节点名完整对齐)

`match_node` 是最长关键字子串匹配。node_yolo_gate 注册词 `["YOLO开关"]`
匹配不到模板节点名 `"🎯 YOLO 感知开关"` (中间隔"感知") → 被 node_ss_yolo
的 `"YOLO"` 抢先 → **开关逻辑从不执行**。修: 注册词加 `"YOLO 感知开关"`。
新节点注册时必须核对 simulink_module.py REFERENCE_APPS 模板里的实际节点名,
注册词必须是节点名的连续子串。验证: 遍历模板节点名逐一 match_node 断言期望 key。

## 3. 统一执行入口 _run_node_single (单步 ⏭ 与右键「运行节点」共用)

老倪 2026-08-30 要求统一。设计:
```
_run_node_single(node, label=None, keep_active=True)
  防重入 (worker running → _busy_hint)
  ① 环节节点 (NODE_RUN_ACTIONS 名字匹配) → _highlight_node(4s) + _run_node_stage (worker 异步, running青→success绿/error红)
  ② params.run_env 数据层 → _highlight_node + _run_node_stage(lambda: _run_env_wrap(node))
  ③ 其他节点 → _highlight_node(2.5s) + _log_explain + _sim_node (节点逻辑+数据流, keep_active=True=单步金色保持)
```
- step_sim 拓扑序推进, 当前节点调 _run_node_single(keep_active=True)
- 右键"运行节点" → _run_node_single(keep_active=False, 运行完即绿)
- **修了单步假绿**: 原来 _sim_node 里 execute_node_logic 启动 worker 后立即标
  success (训练在后台跑节点却显示完成) — 环节节点改走 _run_node_stage 异步状态。
- _run_node_stage 日志文案统一 "⏳ 运行 [...]" (原"双击运行")。

## 4. 代码讲解 explain_node (老倪: 运行节点要从代码角度解释)

node_logic.explain_node(name, module=None, out=None) → 多行文本, 全节点通用:
```
🧩 代码讲解 · <节点名>
  功能: <注册 doc>
  语法: <可修改区代码行 + 行尾注释>  (上限 6 行, 超出提示看编辑器)
  框架: return module.xxx ← 调度/激活动作 (框架区勿改)
  全局: 画布 i/N 节点 · 上游 ← x / 下游 → y   (从 links 实时算)
  数据: 空间 <dims/desc>
  仓库: <数据源真实路径 · 帧数/集数 · 特征>   (数据源节点, _probe_data_root)
  比喻: 📦 数据源=原料仓库 → dataset(分拣台) → dataloader(传送带)   (数据源节点)
  数据链: 仓库 → LeRobotDataset(归一化) → DataLoader(batch) → checkpoint  (训练节点)
  趋势: 本步输出「...」→ 沿链路向下游传递
```
调用点: _run_node_single 三分支执行前 _log_explain(node)。
`_probe_data_root()` 路径 = node_logic.py 上溯 **两级** (tools/gui → 仓库根, 别多退)。
优先级与 _ensure_training_data 一致: closed_loop(Orin) → metaworld_peg_long →
metaworld_peg → ss_insert_lerobot。

## 5. 右键菜单黑屏 → 显式深色 QSS 是通用解

- 2026-08-12 教训: VcXsrv 下 QMenu 深色 QSS 黑屏 → 去掉 QSS 用系统默认。
- 2026-08-30 新教训: **当前 Xorg (3200x2000) 下系统默认菜单也黑** (弹出全黑,
  鼠标滑过才显示文字) → 显式深色 QSS 反而正常。
- 结论: 菜单/编辑器右键一律显式深色 QSS, 不赌系统默认:
```python
_MENU_QSS = ("QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
             "QMenu::item { color:#e6edf3; padding:6px 22px; } "
             "QMenu::item:selected { background:#1f6feb; color:#ffffff; }")
def contextMenuEvent(self, e):
    menu = self.createStandardContextMenu(); menu.setStyleSheet(self._MENU_QSS)
    menu.exec_(e.globalPos()); menu.deleteLater()
```
已落地三处: _LogBox(终端, 含「清除输出」追加) / _CodeEditor(node_logic_dialog,
NodeLogicDialog 编辑区 + SourceViewDialog) / _CodeEdit(simulink 场景 JSON 框)。
验证: DISPLAY=:0 真实渲染菜单截图, 断言 avgRGB 深色(<80) + 亮像素>2%(文字)。
⚠️ 渲染测试脚本里先 monkeypatch QMenu.exec_ 再测渲染会导致 QTimer 不触发 —
两段测试分开跑。

## 6. QSS f-string 拼接 `}}` 遗留坑

多段拼接 QSS 时, 只有第一段是 f-string, 后续普通字符串里的 `}}` 是**字面双大括号**
→ QSS 结尾多一个 `}` → "Could not parse stylesheet" 警告。检查: `widget.styleSheet()`
结尾是否 `}}`。修: 普通字符串段用单 `}`。

## 7. pip/uv 装大依赖包卡死 → 手动 wheel 解包

症状: `uv pip install metaworld` / `pip install metaworld==3.0.0` 卡死 (0% CPU 无网络,
pip-unpack 里有 wheel 但进程不动; 甚至 --no-deps 也卡)。
正解:
1. 确认网络没问题 (curl 测速 23MB/s)
2. 拿 wheel URL (pypi.org JSON API 或 aliyun simple 页面)
3. `curl -C -` 续传下载, `unzip -t` 校验完整 (files.pythonhosted.org 下载不稳定)
4. 纯 Python wheel (py3-none-any) 直接 `unzip -oq x.whl -d site-packages`
5. 逐个补 import 缺的包 (glfw / imageio / scipy / PyOpenGL, aliyun 源快)
6. 验证 `import metaworld` + make_env
