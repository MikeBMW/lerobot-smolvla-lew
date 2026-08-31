# node_logic 框架动作坏引用 + 注册匹配歧义 (2026-08-30)

老倪双击/右键「📦 metaworld 数据」「🎯 YOLO 感知开关」等节点, 发现"运行了但没真跑"。
根因两类: 框架动作调了不存在的方法 (异常被吞=假执行), 以及 _reg 注册词与模板节点名不一致 (被别的注册项抢先)。

## 1. 坏引用 = 假激活 (老倪真实性零容忍重灾区)

node_logic.py 的 🔒 框架动作行调用 `module._xxx()` 时, 方法名写错 → AttributeError →
被 `_sim_node` 的 `except Exception: pass` (simulink_module.py:5922) 吞掉 →
节点变绿 + 日志正常, 但动作从未执行。**这是"写了没做"最隐蔽的形态, 无任何报错。**

本次实例 (commit 2d743909):
- `node_metaworld_data` 调 `module._toggle_source_node(ctx["name"])` — 该方法**从未存在**
  (git log -S 确认从 v1.5.0 引入就是错的); 正确 = `_toggle_source(node)` 需要 node dict,
  而 ctx 只有 name → 参照 `_toggle_train_gate_ctx` 模式新增 `_toggle_source_ctx(name)`
  按名找节点再调 `_toggle_source`。
- `node_yolo_gate` 调 `module._set_yolo_gate_ctx(...)` — 同样不存在; 新增
  `_toggle_yolo_gate(node)` + `_toggle_yolo_gate_ctx(name, yolo_enabled)` (与 train_gate 对称)。

**系统性排查法 (一次找全, 别只修报错的那一个)**:
```python
import re
src = open("tools/gui/node_logic.py", encoding="utf-8").read()
calls = set(re.findall(r"module\.([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*\)", src))
missing = sorted(c for c in calls if not hasattr(simulink_module.SimulinkModule, c))
print(missing)  # → ['_set_yolo_gate_ctx', '_toggle_source_node']
```
改完复查 `hasattr` 应为空。

## 2. 注册匹配歧义: 模板节点名 vs _reg 匹配词

`match_node(name)` 是**最长关键字匹配**。节点名 "🎯 YOLO 感知开关" 里没有 "YOLO开关"
(中间隔"感知"), 注册词匹配不上 → 被 node_ss_yolo 的 "YOLO"(4字符) 抢先 →
开关节点执行的是"列检测目标清单"逻辑, 开关状态从不落地。

**铁律: 模板节点名 (REFERENCE_APPS 第2元素) 必须被 _reg 匹配词覆盖, 且要比更短的
歧义词长**。修法: `_reg("yolo_gate", ["YOLO 感知开关", "YOLO开关"], ...)` —
6字符 > 4字符, 正确命中。改完跑匹配回归:
```python
cases = [("🎯 YOLO 感知开关", "yolo_gate"), ("🎯 YOLO 目标检测", "ss_yolo"),
         ("📦 metaworld 数据", "data"), ("② 训练", "train"), ("全新训练", "train"), ...]
for name, expect in cases: assert node_logic.match_node(name) == expect
```

## 3. 日志文案必须与真实执行路径一致 (又一次"写了没做")

`on_run_env` 推理分支日志写 "📷 推理模式 → 加载真实模型 rollout" 但实际调 `on_infer`
(= 只查 Orin 状态 GET relay/orin/status)。老倪: "运行节点…也没有运行"。
修 (commit 011f79c6): 推理模式 → `on_infer_rollout(node or {})` (真 rollout:
gen_insert_video.py + 飞书), 与 `_toggle_mode` 引导文案 ("双击数据源 → 加载真实模型
rollout") 对齐。**教训: 功能改了执行路径, 日志/引导文案要同步; 文案说 rollout 就必须
rollout, 否则必被老倪抓"没运行"。**

## 4. open_node_source 的 source 语义歧义

数据源节点 `params.source` 是**数据源标识** ("metaworld"/"orin"), 不是代码路径。
open_node_source 拿它拼路径 → "/repo/metaworld" 不存在 → 报"文件不存在"误导。
修: 路径不存在时先查 node_logic 映射 (`match_node` + `get_node_location` + `NODE_LOGIC[key]["fn"].__name__`),
有则提示 "source=... 是数据源标识, 运行逻辑在 node_logic.py:行号 · 函数 fn()",
无映射才报文件不存在。⚠️ source 也可能是真路径 (YOLO/双脑节点的源码映射), 判断靠
os.path.exists, 不存在时再降级到映射提示。

## 5. 终端右键菜单加「清除输出」 (commit 59d0f30e)

```python
class _LogBox(QTextEdit):
    """终端: 标准右键菜单 + 追加清除输出"""
    _MENU_QSS = ("QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
                 "QMenu::item { color:#e6edf3; padding:6px 22px; } "
                 "QMenu::item:selected { background:#1f6feb; color:#ffffff; }")
    def contextMenuEvent(self, e):
        try:
            menu = self.createStandardContextMenu()   # 保留 复制/粘贴/全选
            menu.setStyleSheet(self._MENU_QSS)
            menu.addSeparator()
            act = menu.addAction("清除输出")           # ⚠️ 不带 emoji (VcXsrv 字形黑块)
            act.triggered.connect(self.clear)
            menu.exec_(e.globalPos())
            menu.deleteLater()
        except Exception:
            super().contextMenuEvent(e)
```
创建处 `self.log_box = QTextEdit()` → `_LogBox()`。深色 QSS 在当前 Xorg 环境实测正常。

## 6. 菜单渲染验证方法论 (黑屏排查)

"右键菜单全黑"排查三步 (本次实测当前环境全部正常, 问题未复现, 待老倪补细节):
1. **二分渲染层 vs 显示层**: `menu.grab()` (Qt 离屏渲染, 绕过 X) vs
   `QScreen.grabWindow(0, x, y, w, h)` (X 屏幕合成)。qt_grab 正常 + screen 异常 =
   X 显示层问题 (合成/重绘时序); 都正常 = 环境问题。
2. **时序**: show 后 0.15/0.5/1.5s 分别截屏, 判断"弹出瞬间黑一下"还是"持续黑"。
3. **真实右键**: xdotool 右键 + 截屏 diff (找差异区域 + 色块图)。注意窗口 frame 与
   内容区偏移 (mutter: frame (104,40) vs 内容 (132,138)), 以及全屏对话框遮挡。
   独立测试脚本弹出菜单 ≠ 主程序菜单 (全局 QSS 差异), 尽量在真实主程序上验证。

**⚠️ 测试脚本坑**: 同脚本里先 monkeypatch `QMenu.exec_` 再跑真实渲染, restore 后
QTimer 在模态循环里不触发 — 两类验证必须分开跑 (二分定位法: 注释第一部分单跑第二部分)。
