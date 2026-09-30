# GUI 取证三条硬纪律 + 两个可抄的断言 (2026-09-24 实测)

## 1. 定时刷新不得冲掉"派生画面" (最贵的 BUG 类)
**症状**: 用户「处理后的图/框选拉伸图 刚一显示, **立刻变回原始坏图**」; 严重时表现为「图是坏的/一片白」。
**根因**: 窗口 500ms 的 `_tick()` 每次都把**原始帧**重新 `set_frame_rgb()` → 把派生结果(裁剪/切除/标注/框选)冲掉。
**修法**: 定时器只做「取新数据 + 刷状态文字」; **面板画面只在显式动作里更新**(点按钮/切源/改参数/开关)。
**回归断言(逐位)**:
```python
snap = w._last_rgb.copy()
for _ in range(3):
    w._tick(); app.processEvents(); time.sleep(0.15)
assert np.array_equal(snap, w._last_rgb)     # 跨 3 跳画面逐位不变
```
⚠️ 反作用: 改成"只在显式动作更新"后用户马上会问「图片怎么不动了/也不知道什么时候拍的」→
必须同时补: ①一键"立即取图/拍照" ②自动刷新(可关+间隔+模式) ③**时间戳标签**(拍照 HH:MM:SS + 帧龄 + 耗时 + HTTP码)。

## 2. 控件不可截断: 断言要覆盖全部按钮
- `setMinimumWidth(b.sizeHint().width())` **在构造时算不准**: QSS/字体解析晚于 sizeHint →
  真实需要 148px 却钉成 140px, 运行期被布局压窄就截字(实测连抓两处)。
- 修: 布局落定后 + `showEvent()` 里各钉一次:
  ```python
  def _fix_min_widths(self):
      for b in self.findChildren(QtWidgets.QPushButton):
          w = b.sizeHint().width()
          if w > b.minimumWidth(): b.setMinimumWidth(w)
  ```
- 布局层面: 成组控件别塞进窄面板(左侧画面条 ~540px 塞 6 个必截断) → 搬到整宽独立行。
- **断言**: 真桌面脚本对**所有** `QPushButton` 断言 `b.width() >= b.sizeHint().width()`,
  并把按钮写成**显式清单 dict** —— 每加按钮就补一行, 否则新按钮悄悄截断无人发现。

## 3. 断言分级: UI 级不依赖外部服务
服务/设备端口一关, 一片判据同时变红 → 分不清是代码回归还是环境。
- 把「控件可达 → 点了有结果(失败也算如实记录) → 标签口径 → 开关可控」做成**不依赖对端**的独立断言块;
- 依赖对端的判据单独成组, 结论里注明「因对端不在线」, 并在对端恢复后重跑给出全绿证据。
- 统计"是否产生了新的外部副作用(真拍/真动)"时**必须按 action 过滤**:
  审计流水里同样会记**失败**(http 000) → 只数 `action in ("capture_detect","fetch_grab") and http == "200"`,
  否则失败记录也会让计数变化, 把"没动作"误判成"动作了"。

## 4. 剪贴板/绘图两个环境坑 (可抄代码)
```python
# 图片进剪贴板必须一次性 setMimeData — 先 setImage 再 setText 会把图片冲掉(实测剪贴板 0x0)
md = QtCore.QMimeData(); md.setImageData(img.copy())
if path: md.setText(path)          # 粘到文本处=路径, 粘到图处=图片
QtWidgets.QApplication.clipboard().setMimeData(md)
```
- **offscreen 后端的 `clipboard.image()` 恒 0×0** → 剪贴板类断言只能放真桌面 (`DISPLAY=:0`) 跑;
  offscreen 里改为断言逻辑/mimeData。
- `DISPLAY=:0` 下 **先 `import cv2` 再 `import PyQt5`** 会抢走 xcb 插件
  (`Could not load the Qt platform plugin "xcb"`) → 测试脚本里 PyQt5 必须最先导入。

## 5. "最大化按钮不好使"= 修好, 不是禁用
QDialog 默认 `Qt.Dialog` 类型在 X11 下不响应 maximize → 必须**换类型**:
`setWindowFlags(Qt.Window | WindowMaximizeButtonHint | WindowMinimizeButtonHint | WindowCloseButtonHint)`
(只加 hint 无效)。真桌面判据: `isMaximized() and width() >= 屏可用宽 - 60`;
判类型别用 `flags & Qt.Dialog` (Dialog=Window|Dialog 会命中 Window 位) → 取 `WindowType_Mask` 低 8 位比较。
