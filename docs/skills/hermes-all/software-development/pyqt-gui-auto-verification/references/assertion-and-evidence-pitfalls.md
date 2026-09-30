# 断言写法与证据采集的三个坑 (2026-09-13 实测, 都踩过)

## 1. `QLabel.pixmap()` 返回对象会随下一次 setPixmap 变动 → 比较必须立刻取标量
```python
# ❌ 错: 两次比较都读到"最后一帧"的宽度 → 误判"倍率不生效"
win.cmb_zoom.setCurrentText("×1"); app.processEvents(); pm1 = win.lbl_img.pixmap()
win.cmb_zoom.setCurrentText("×4"); app.processEvents(); pm4 = win.lbl_img.pixmap()
assert pm4.width() > pm1.width()
# ✅ 对: 立刻取 int
w1 = int(win.lbl_img.pixmap().width())
```
实测现象: `×1:686px ×4:686px` 被判 FAIL, 而独立探针打印 `×1→224 / ×2→448 / ×4→686` 完全正常。
**凡是断言 Qt 返回对象 (QPixmap/QImage/QByteArray) 的尺寸/内容, 先转成标量再比较。**

## 2. 阴性对照法: 证明"修好了"是因为修复真的覆盖了崩溃路径
- 只做正向断言 ("现在渲染不崩") 是不够的 —— 可能那段代码根本没被执行到。
- 做法: 把 monkeypatch 打回**旧实现** → 断言同一路径**确实报错** → 换回新实现 → 断言通过。
  实测教训: 只 monkeypatch 被调函数无效, 因为**调用点**已经改成传正确类型 (int), 旧函数收不到坏类型;
  真要复现必须回到调用点。更省事的等价组合:
  ① 单元级复现坏类型 (`fm.elidedText(text, Qt.ElideRight, 300.0)` 抛 TypeError / 传 300 正常);
  ② 定点调用**该 item 的 paint()** (而不是整窗 render, 后者可能没走到该分支);
  ③ 全场景 `render()` / 整窗 `grab()` 做最终回归。
- 价值: 一次交互里把"根因→修复→覆盖性"三段证据凑齐, 用户质疑时不用重跑。

## 3. offscreen 也能拿真渲染证据 (别把 GL 报错当失败)
- 证据链: `widget.grab()` 或 `scene.render(painter)` → `QImage` → `constBits()` → numpy →
  亮像素计数 `int((a.max(axis=2) > 60).sum())` 断言非全黑; 判"真图非黑帧"用像素 `std > 5`;
  同时把 PNG 存盘当交付证据 (报告/回报里给绝对路径)。
- offscreen 下 `GLViewWidget` 会打印 `pyqtgraph.opengl: Requires >= OpenGL 2.1; Found b'4.6 ...'`
  —— 那是**窗口自身 GL 初始化**失败, QPainter / 子控件 / grab 路径照常工作。
  **不要据此下"窗口是空的/3D 不可用"结论**; 真机 GL 行为要用真实 DISPLAY 另验。
- 取像素的标准写法:
```python
img = pix.toImage().convertToFormat(QtGui.QImage.Format_RGB32)
buf = img.constBits(); buf.setsize(img.byteCount())
a = np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3]
```
