# GUI 按钮/回调回归 — 2026-09-13 实测 (老倪: "点击 SW实况窗口, 没反应")

## 症状与根因
用户点按钮完全没反应。真显示 (DISPLAY=:0) 复现出的原始报错:

```
[SW 实况窗口] 打开失败: AttributeError: 'SWLiveWindow' object has no attribute '_open_viewer'
```

- 给子窗口 `SWLiveWindow` 加的新按钮, 回调写成 `self._open_viewer` —— 该方法只定义在
  **另一个类** `DreamView3D` 上。
- `AttributeError` 在**构造期**就抛 → 单例工厂 `sw_live_window()` 返回 `None` →
  **整个窗口都开不出来**, 不只是那个按钮; 用户侧表现为"点什么都没反应"。
- 工厂里只有一句 `print(...)`, 界面上零提示 → 排查全靠猜。

## 为什么 offscreen 测试没抓到
之前的 offscreen 用例只做了: 构造 `SWLiveWindow()` + 拖帧 + 断言信号表/曲线。
**没有点那个新按钮**, 而错误发生在构造期 → offscreen 用例当时其实是失败的 (返回 None),
但断言写的是"窗口存在吗"以外的项, 静默通过。

## 回归脚本模式 (加/改任何 GUI 按钮后必跑, 真显示)
```python
import os
os.environ.setdefault("DISPLAY", ":0")
os.environ.pop("QT_QPA_PLATFORM", None)          # 真 X11; offscreen 测不出构造期回调错
from PyQt5.QtWidgets import QPushButton, QCheckBox, QComboBox
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

w = DV.sw_live_window()                          # 单例工厂必须返回真窗口 (None = 构造失败)
assert w is not None and w.isVisible(), "窗口没开出来"
for b in w.findChildren(QPushButton):            # 逐个真点
    b.click(); app.processEvents()
for cb in w.findChildren(QCheckBox):             # 勾选框来回切
    cb.setChecked(True); app.processEvents(); cb.setChecked(False); app.processEvents()
for cb in w.findChildren(QComboBox):             # 下拉遍历所有项
    for i in range(cb.count()):
        cb.setCurrentIndex(i); app.processEvents()
# 再遍历主窗口 (DreamView3D 等) 的所有按钮
for b in d3.findChildren(QPushButton):
    b.click(); app.processEvents()
# 断言"点击后窗口真存在且可见" — 只断言"没抛异常"不够 (构造失败也是静默)
assert DV._SW_WIN is not None and DV._SW_WIN.isVisible()
print("geom =", DV._SW_WIN.geometry().getRect())  # 顺带确认在屏内 (非负坐标/不超出屏幕)
```

## 三条铁律
1. **加按钮 → 真显示下逐个点一遍**; offscreen 只能验"构造/逻辑", 验不了"点击链路 + 屏内可见"。
2. **子窗口的按钮回调只能指向自己类上定义的方法** — 跨类同名方法 (两个类都有 `_open_viewer`)
   是坑源: 同一个名字在 A 类存在、B 类不存在, 写的时候看不出来。
3. **单例工厂要把失败原因吐出来** (`print(type(e).__name__, e)` + GUI 侧写画布日志), 只 `return None`
   等于把 bug 藏进静默。

## 关联现象: "视频怎么不动"
只播实时流的窗口在链条停下后**定格在末帧**, 用户会以为坏了。交付时配一个可交互的
"拖帧/单步/播放 + 逐帧信号" 视图 (L2/L3 的 dreamview 同款) 并在窗口里显示数据源路径,
让用户能自己区分"没在跑"和"真不动"。
