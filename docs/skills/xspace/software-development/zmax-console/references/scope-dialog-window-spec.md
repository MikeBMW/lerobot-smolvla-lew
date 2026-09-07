# Scope/弹窗窗口规格 — 状态空间仿真波形 (2026-08-18 老倪: "窗口小又卡看不清, 不能调大小")

适用于状态空间画布的 📊 仿真波形 (StateSpaceScopeDialog) 及同类纯绘图弹窗。

## 标准节点尺寸
- **仿真波形节点 = 标准 node 尺寸 150x50** (w=150, h=DH=50, DH=50 在
  simulink_module.py 顶部定义)。别做 280x80 特制尺寸 — flows/state_space_obs.json
  的 ssvideo 曾 280x80, 老倪明确要求"默认应该是标准 node 大小"。
- 对比参照: dual_brain_peg.json 功能节点 w=150 h=None (渲染=DH); CICDStageItem 150x88。

## 纯 paintEvent QDialog 的初始尺寸坑
- **无布局 (只有 paintEvent) 的 QDialog 没有初始尺寸** → 弹出极小。
  `setMinimumSize` 只设下限不设实际尺寸 — 必须显式 `resize(1280, 820)`。
- 用户要求: "大一点, 可以看的更详细" → 初始 1280x820, 最小 1024x700。

## 可调大小三件套
```python
self.setMinimumSize(1024, 700)
self.resize(1280, 820)
self.setSizeGripEnabled(True)                                   # 右下角拖拽手柄
self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)  # 最大化按钮
```
- QDialog 默认无 size grip; VcXsrv 下 WM 不会补手柄 → 必须显式 setSizeGripEnabled。
- 用户明确抱怨"不能调整窗口大小" — 加完手柄 + 最大化按钮才算可调。

## 曲线批量绘制性能 (resize 卡顿根因)
- 逐点 `drawLine` (500 点 x 4 子图 = 2000 次 QPainter 调用) 在 resize/拖动重绘时
  明显卡顿 → 改成 QPainterPath 一次性批量:
```python
path = QPainterPath()
path.moveTo(X(self._t[0]), Y(y[0]))
for tt, vv in zip(self._t[1:], y[1:]):
    path.lineTo(X(tt), Y(vv))
p.drawPath(path)   # 500 点 path < 5ms
```
- 放大后细节要求: 线宽 2→2.5, 标题字号 12→14 (wqy 字体), 阶段竖线保留。

## 验证
改完必须重启控制台实测: 双击节点 → 弹窗应 1280x820、右下角可拖、最大化可用、
拖动 resize 时不卡。
