# UI 布局与主题坑 (2026-08-22, v2.5.2)

96DPI 高分屏 (33寸 3200x2000, GNOME X11) 下画布 UI 重构的三条坑, 均为实际踩坑 + 根因 + 修复。

## 1. QSplitter 固定宽度面板仍会画可拖手柄竖线

**现象**: 用户报"模块库右边的拖动栏，还在，你也没改啊"。之前只删掉了独立的 16px 空扩展条按钮 (`_lib_expand_bar`), 但 LibraryPanel 仍塞在 `QSplitter` 里, QSplitter 在库面板和画布之间**照常画一条可拖手柄竖线** — 即使 `setStretchFactor(0,0)` 也不能去掉这条竖线 (fixed-width widget 只是拖不动, 手柄仍在)。

**根因**: QSplitter 一定给相邻两个 widget 之间画 handle, 与 widget 是否 fixed 无关。

**修复**: 把 fixed 面板移出 QSplitter, 外层用 QHBoxLayout 承载 `[面板 | splitter]`:
```python
body = QWidget()
body_lay = QHBoxLayout(body)
body_lay.setContentsMargins(0, 0, 0, 0)
body_lay.setSpacing(0)
split = QSplitter(Qt.Horizontal)      # 只排 [mdi | model_tree], 不再含 library
...
self._main_split = body               # 浮动窗口 lay.addWidget(new_w._main_split,1) 仍兼容
body_lay.addWidget(self.library)      # fixed 360/20
body_lay.addWidget(split, 1)          # 画布+数据字典占满
```
- 折叠/展开 (set_collapsed setFixedWidth 360/20) 在 QHBoxLayout 下同样生效 (fixed width 优先)。
- **验证**: 截图后扫 library 右边界 (x≈360) 附近整段灰度连续无突变 = 手柄消失 (之前 QSplitter handle 会是一条 4-6px 亮度突变竖线)。

## 2. switch_theme 之后才 addWidget 的控件遍历不到 → 白底残留

**现象**: 用户报"模块库的样式，背景怎么变白了？换成暗夜风格"。模块库是唯一白底, 其余全暗。

**根因**: `switch_theme` 遍历 `[self]+findChildren(QWidget)` 逐个把浅色值 replace 成深色值。上一轮把 `body_lay.addWidget(self.library)` 放在了 switch_theme **之后** (等 model_tree 也加进 split 才统一组装 body), 导致 switch_theme 执行时 library 还是"孤儿" (没 parent 加入树), findChildren 遍历不到 → 写死的 `background:#f6f8fa` 没被替换成 `#0d1117` → 白底残留。

**修复**: 把 library 加入 body_lay 的动作**提前到 switch_theme 之前** (在 split.addWidget(mdi) 之后立即组装)。split 可以先只含 mdi 就放进 body_lay, model_tree 后加进 split 会自动出现, 不影响。

**排查线索**: 单一面板白底、其余全暗 = 该面板的 addWidget 行号晚于 switch_theme 调用行号 (grep 两处行号对比)。这是 switch_theme "类常量不更新" 之外的第二个主题坑 (前者是新建对话框黑字, 后者是已有 panel 白底)。

## 3. 96DPI 节点"字大框小" — JSON 固化旧尺寸压制新默认值

**现象**: 用户报"方块太小，里面的字体太大" / "你也没改啊，别瞎说"。字体放大了但节点框没变大。

**根因**: `flows/*.json` 固化 202 处 `"w":150`、244 处 `"w":180` 旧尺寸。`load_flow` 里 `node.setdefault("w", 240)` 对**显式存在的 key 无效** — JSON 旧值 w=150/180 压制了新默认值 → 框没大、字却大了。

**修复**: `load_flow` 与 `load_flow_file` 两条路径对普通节点 (非 row_bg) 强制 `max(旧尺寸, 240×84)`:
```python
node["w"] = max(node.get("w", 0), 240)
node["h"] = max(node.get("h", 0), 84)
```
- 比例最终态: 普通节点 240×84, CICD 240×92, 标题 12pt 递减 (12/11/10), 徽章/ID 11pt, 辅助 10pt, 参数 Consolas 10pt, 列距 300, 行距 260。
- **教训**: 改默认值 ≠ 生效, 必须先 grep JSON/配置文件里是否固化了旧值; 固化值会压过代码默认值, 必须改"加载路径"强制覆盖。

## 版本号 bump 清单 (每次迭代必查)
版本号分布 6 处, 都要同步 (integrity_check.py 校验 5 处 + 自身 EXPECTED_VERSION):
1. `tools/gui/studio.py:641` — `QLabel("Z-MAX vX.Y.Z")` 侧栏
2. `tools/gui/studio.py:9734` — `setWindowTitle("... Z-MAX vX.Y.Z [W-01]")` 窗口标题
3. `tools/gui/update_checker.py:10` — `CURRENT_VERSION = "vX.Y.Z"`
4. `tools/gui/docs_sync.py:193` — `"version": "vX.Y.Z"`
5. `tools/gui/docs_sync.py:197` — `"zmax_version": "vX.Y.Z"`
6. `tools/ci/integrity_check.py:27` — `EXPECTED_VERSION = "vX.Y.Z"` (别漏这处, 曾停留在 v2.3.1)

> 注意 studio.py 窗口标题那行注释里有历史版本说明 `# v2.5.1: ... | v2.5.0: ...`, 那是历史记录**不要**替换; 精确匹配 `Z-MAX vX.Y.Z` (带前缀) 才安全, 注释里是 `vX.Y.Z:` 无前缀不会误伤。
