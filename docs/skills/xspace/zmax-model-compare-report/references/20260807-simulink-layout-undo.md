# Simulink 画布布局/撤销实录 (2026-08-07)

## 事故 1: 节点被甩到显示区右侧 (layout 兜底跑飞)
症状: 五模型画布里 "🌉 Interpolant 控制器" 在 x=6620、"🔀 未来决策交叉注意力" 在 x=7920, 超出显示区十万八千里。

根因: `load_reference_app` 的布局分配逻辑:
```python
pos.setdefault(nm, []).append((base_x + c * col_w, base_y + r * row_h))  # 网格位置
xy = next((p for p in cands if p not in used), None)
if xy is None:
    xy = (base_x + i * col_w, base_y)   # 兜底单行: i = specs 索引!
```
specs 里有 41 个节点, layout 网格只覆盖 35 个 → 6 个漏网 (YOLO目标检测/2D→3D/Encoder/Decoder/Interpolant/交叉注意力) 走兜底,
x = 120 + specs索引×260 → Interpolant 索引25 → 6620, 交叉注意力 索引30 → 7920。**兜底节点全挤在 y=80 顶行**。

修复:
1. 重写 layout 覆盖全部 41 节点 (后扩到 51)
2. 列距 260 → 200 (load_reference_app 里 3 处: 网格/兜底/单行横排), 10 列网格总宽 ~1920

验证 (ad-hoc 脚本, 重放分配算法):
```python
# 提取 specs + layout 行 → 模拟分配 → 断言零兜底
specs = re.findall(r'\(\s*"([a-z_]+)"\s*,\s*"([^"]+)"\s*,', seg[:seg.index("], [")])
rows = [re.findall(r'"([^"]*)"', rs) for rs in re.findall(r'^\s*\[([^\]]*)\]\s*,?$', layout_seg, re.M)]
pos = {}
for r, row in enumerate(rows):
    for c, nm in enumerate(row):
        if nm:
            pos.setdefault(nm, []).append((120 + c * 200, 80 + r * 230))
used, fallback = set(), []
for i, (t, nm) in enumerate(specs):
    xy = next((p for p in pos.get(nm, []) if p not in used), None)
    if xy is None:
        fallback.append(nm)
    used.add(xy or (0, 0))
assert not fallback
```
注意正则 `\[((?:"[^"]*"\s*,\s*)*"[^"]*")\]` 抓不到行首空串 `["", ...]` 的行 — 用
`re.findall(r'^\s*\[([^\]]*)\]\s*,?$', layout_seg, re.M)` 按行抓再 `re.findall(r'"([^"]*)"', row)` 解出含空串的全部列名。

## 事故 2: 背景行跟节点行错位 ("YOLO 占了 ACT 的背景")
加感知链首行后, 模型行全部下移一行, 但 `_draw_model_rows(["ACT","SmolVLA",...])` 仍从 base_y=80 排 5 行
→ ACT 背景盖在感知行, AWE 行没有背景。

修复三件套:
1. row_names 加 "YOLO 3D 检测" 且从首行开始排 → 8 行与 layout 前 8 行一一对应
2. `_draw_model_rows` 默认参数 col_w=260→200、n_cols=8→10 与 layout 网格一致 (否则背景带宽度错)
3. palette 加 "YOLO 3D 检测": "#3a5a7a"、"MLP 蒸馏": "#2d6a8f"、"官方专家": "#8f8a3d" (金色=🏆真值锚点)

对齐验证: bg_y0 = base_y + r*row_h - 20; 节点行 y = base_y + r*row_h → 严格对齐 (60/290/520/... vs 80/310/540/...)。

## Ctrl+Z 撤销栈 (本次新增功能)
### 实现骨架
```python
# SimCanvas.__init__
self._sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
self._sc_undo.setContext(Qt.WidgetWithChildrenShortcut)  # 画布内焦点才触发, 不抢输入框
self._sc_undo.activated.connect(self.module.undo)
# mousePressEvent 拖动分支: self._drag_start = (item.node["id"], rp.x(), rp.y())
# mouseReleaseEvent 拖动结束: 位置变了 (差>0.5) 才 self.module._push_undo(("move", [(nid, ox, oy)]))

# module 侧
def _push_undo(self, entry):
    if getattr(self, "_suspend_undo", False): return   # 模板加载/背景行批量布局挂起
    self._undo_stack.append(entry)
    if len(self._undo_stack) > 50: self._undo_stack.pop(0)
# clear() 里 self._undo_stack = []  (新画布=旧操作作废)
```
条目形状:
- `("move", [(nid, old_x, old_y)])` — undo: `it.setPos(ox, oy)` (itemChange 自动同步 node dict)
- `("del_node", nid)` — add_node 自动 push; undo: `_remove_node(nid)`
- `("restore_nodes", [(node_deepcopy, [link_deepcopy...])...])` — delete_selected 自动 push; undo 重建
- `("del_link", link_id)` — add_link 自动 push; undo: 从 links 过滤掉
- `("restore_link", link_deepcopy)` — delete_link 自动 push; undo: add_link 重建

挂起时机: load_reference_app (与 old_sync 模式并列) + _draw_model_rows 开头 `old_undo = getattr(self, "_suspend_undo", False); self._suspend_undo = True` finally 恢复。

### 坑1: restore_nodes 混合 id 连线恢复
add_node 重建生成**新 id**, 删除时保存的连线引用旧 id。被删节点端 → 新 id; **存活节点端 → 原 id** (idmap 里没有):
```python
idmap[n["id"]] = new["id"]          # 只映射被删节点
s = self._items.get(idmap.get(lk["f"], lk["f"]))   # ⚠️ 必须带回退
d = self._items.get(idmap.get(lk["t"], lk["t"]))
```
不带回退 → `_items.get(None)` → None → `if s and d` 跳过 → 连线静默丢。

### 坑2: _suspend_undo AttributeError 被吞
画布未加载过模板 (没走 load_reference_app/_draw_model_rows) 时属性不存在 → `old = self._suspend_undo` 抛
AttributeError → undo() 的 try/except 吞掉 → 撤销静默失败 (无任何日志)。**所有读取一律
`getattr(self, "_suspend_undo", False)`**。

### 验证方法: offscreen Qt 真跑 (抓出两个坑的关键)
```bash
QT_QPA_PLATFORM=offscreen python3 /tmp/verify.py
```
```python
app = QApplication.instance() or QApplication(sys.argv)
mod = M.SimulinkModule()
mod._log = lambda m: None          # 防 Qt 控件调用
# move: setPos(500,500) 后 undo → 断言 scenePos()==(100,100) 且 node dict 同步
# 删除撤销: 建 X→Y 连线, 选中 X delete_selected, undo → 断言 2 节点 1 连线, links[0]["f"] != x 旧 id
# 挂起: _suspend_undo=True 时 add_node 不入栈
# 限深: 60 次 push → 栈长 50
```
- GUI 实际用**系统 python3** (PyQt5 在 ~/.local/site-packages), .venv 无 PyQt5; 用 `/proc/<pid>/exe` 确认
- 断言失败先怀疑 except 吞异常: 临时把 `except Exception: pass` 换成打印 traceback, 或手动重放恢复逻辑分段打点

## ZMAX_AUTO_RUN 行为
- `ZMAX_AUTO_RUN=1 bash run_studio.sh` → studio.py `QTimer.singleShot(2500, self._auto_run_compare5)` →
  自动切 Simulink 页 → open_compare5() (加载七模型) → start_sim() (开始 7 模型串行训练)
- **重启 GUI = 杀训练**: StudioMainWindow.closeEvent 会 pkill -9 训练子进程 → 训练进行中改代码要等训练完再重启
- 训练完 auto_finalize (仅 ZMAX_AUTO_RUN=1): rollout 视频 + PDF + 飞书交付
