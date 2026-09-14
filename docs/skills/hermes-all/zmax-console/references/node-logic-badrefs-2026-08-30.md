# node_logic 坏引用 + 菜单黑屏排查 (2026-08-30, commit 2d743909)

> 本文件是 SKILL.md「陷阱」区对应内容的完整版。
> 配套脚本: `scripts/check_node_logic_refs.py` (坏引用检查) / `scripts/menu_render_probe.py` (菜单渲染二分探针)。

## 1. node_logic.py 框架动作坏引用 = 静默假执行

**症状**: 画布节点执行时看着一切正常 (变绿 + 日志照打), 但动作从未真正发生。

**根因** (两处, 均 v1.5.0 引入即错):
- `node_metaworld_data` 调 `module._toggle_source_node(ctx["name"])` — 方法**从未存在**
  (git log -S 确认 simulink_module.py 从未出现过该字符串, 正确名是 `_toggle_source(node)`)
- `node_yolo_gate` 调 `module._set_yolo_gate_ctx(...)` — 同样不存在

异常在 `_sim_node` 的 `except Exception: pass` 被吞 → 用户看到"成功"但什么都没发生
= 老倪零容忍的"假激活/写了没接"。

**系统性排查** (别只 grep 单个名字):
```python
import re, sys
sys.path.insert(0, "tools/gui")
import simulink_module, node_logic  # 需要 QT_QPA_PLATFORM=offscreen
src = open("tools/gui/node_logic.py", encoding="utf-8").read()
calls = set(re.findall(r"module\.([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*\)", src))
missing = sorted(c for c in calls if not hasattr(simulink_module.SimulinkModule, c))
print("坏引用:", missing)
```
直接跑 `scripts/check_node_logic_refs.py` (含 match_node 匹配抽查)。

**修复模式** (参照 `_toggle_train_gate_ctx(name, ...)`):
```python
def _toggle_source_ctx(self, name):
    for n in self.nodes:
        if n.get("name") == name:
            self._toggle_source(n)          # 调真实切换方法
            return (True, f"数据源激活: {n.get('params', {}).get('source', '?')}")
    return (True, f"数据源节点未找到: {name}")
```
框架动作必须有真实副作用 + 返回 (True, 描述) 元组。

## 2. node_logic 注册词必须覆盖模板实际节点名

**症状**: 节点逻辑注册了但从不执行 (被别的逻辑抢先)。

**根因**: `_reg("yolo_gate", ["YOLO开关"], ...)` 但模板节点名是 `"🎯 YOLO 感知开关"`
(中间隔"感知") → `match_node` 最长匹配被 `ss_yolo` 的 `"YOLO"` (4字符) 抢先 (6字符的
"YOLO 感知开关" 因注册词不含该串而无法匹配) → 开关逻辑从不执行, 执行的是
node_ss_yolo (目标检测清单)。

**修法**: 注册词补齐实际模板名: `_reg("yolo_gate", ["YOLO 感知开关", "YOLO开关"], ...)`。

**验证铁律**: 跑真实模板节点名的 match_node 回归 (check_node_logic_refs.py 内置 5 个抽查:
🎯 YOLO 感知开关→yolo_gate / 📦 metaworld 数据→data / ☑ 训练开关→train_gate /
② 训练→train / 🎯 YOLO 目标检测→ss_yolo)。"注册了但匹配不到" 是静默失效, 别只断言注册存在。

**连带**: `on_node_activated` 也补了 yolo_gate 双击分支 (与 train_gate 对齐 checkbox 语义,
原落默认分支打开参数框)。

## 3. git remote pushurl 独立于 url

`remote.origin.pushurl` 单独指向 ghproxy → `git remote set-url` 只改 url, push 仍走
ghproxy 报证书错误。诊断: `git remote -v` 看 push 行 ≠ fetch 行。修:
`git config --unset remote.origin.pushurl`。

## 4. 右键菜单黑屏二分排查

**场景**: 老倪报"右键的菜单, 刚开始是全黑的, 啥都看不见" (画布节点右键 / 代码编辑区右键)。

**排查顺序** (2026-08-30 实测, 本环境渲染层全正常, 未复现黑屏):
1. `scripts/menu_render_probe.py` (必须真实 DISPLAY, offscreen 测不出显示层问题):
   - ① `menu.grab()` = Qt 离屏渲染 (绕过 X server)
   - ② `grabWindow` 截屏 = X 屏幕实际显示
   - ①正常②黑 → 显示层问题 (合成器/时序/窗口栈); ①②都黑 → Qt 渲染问题 (QSS/字体/palette)
   - 0.15/0.5/1.5s 三次截屏区分"闪黑" vs "永久黑"
2. 实测结论: 三种 QSS (默认/深色/浅色) 菜单 0.5s 内正常上屏, 全局 QSS 无 QMenu 规则,
   QPlainTextEdit 标准菜单也正常 → 问题可能在特定时刻/环境, 需用户确认场景。

**真实主程序复现的窗口栈陷阱**:
- `xwininfo -root -tree` 查栈序 — 打开的对话框可能**全屏盖住画布** (如 3068x1862 的
  NodeLogicDialog), 右键点到的不是画布
- WM frame 与内容窗口是两层: `xdotool getwindowgeometry` 拿到的是 frame 位置,
  `grabWindow(内容窗口id)` 才能截到内容; xdotool 点击坐标 = 内容窗口偏移 + 节点相对坐标
  (本机 3200x2000 Xorg: 内容窗口 0x200000d 在 (132,138), 画布节点 (468,337) →
  屏幕坐标 (600,475))
- 两个同名窗口 (frame + 内容) 会误导 `xdotool search --name`
