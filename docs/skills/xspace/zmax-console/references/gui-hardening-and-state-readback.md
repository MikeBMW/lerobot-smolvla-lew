# GUI 现场硬化六条 + 让 agent 能"看见"用户的选择 (2026-09-24 汇总终端实测)

> 场景: 把一个"画布节点右键打开"的汇总终端窗口 (外观质量检测) 做到能用 —— 用户连续反馈
> 「最大化按钮不好用」「字数太多太挤，有的显示不全」「太乱了，重新设计 UI」
> 「我圈了你看到了么」「改完还是老样子」。每条都有现场症状 → 根因 → 修法 → 回归断言。

## 1. 最大化按钮不响应 → 窗口类型必须换 `Qt.Window`

- 症状: 最大化按钮画得出来、点了没反应 (QDialog 默认窗口类型是 `Qt.Dialog`, X11 下 WM 不处理 maximize)
- **只加 `WindowMaximizeButtonHint` 无效**, 必须**换类型**:
  ```python
  self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMaximizeButtonHint
                      | QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowCloseButtonHint)
  ```
- ⚠️ **判据坑**: 别写 `flags & Qt.Dialog` —— `Qt.Dialog = Window|Dialog`, 会命中 Window 位而误判;
  要取类型字段: `(int(flags) & int(QtCore.Qt.WindowType_Mask)) == int(QtCore.Qt.Window)`
- 真桌面判据: `showMaximized()` → `isMaximized() == True` 且窗宽 ≈ 屏宽 (实测 3068 = 屏宽)

## 2. 按钮文字被挤断 ("有的显示不全")

- 根因一: 构造时 `setMinimumWidth(sizeHint().width())` **不够** —— QSS/字体解析晚于构造, 最小宽偏小 (实测 120 < 148)
- 修法: 布局落定后**再钉一遍**最小宽 (`_build()` 末尾 + `showEvent` 里遍历 `findChildren(QPushButton)` 取 `sizeHint()` 重设)
- 根因二: **控件挤在窄侧栏** (左画面条仅 ~540px 却塞了 8 个控件) → 挪到**整宽独立行**
- 回归断言: 真桌面遍历所有按钮, 比"实际宽 vs sizeHint 宽"; 这类问题靠它当场抓到过两次

## 3. `import cv2` 必须在 PyQt5 之后

cv2 自带 Qt 插件, 先导入会**抢走 xcb** → 真桌面起窗报插件冲突 (`could not load the Qt platform plugin "xcb"`)。
窗口代码里 cv2 **延迟导入**(函数内 `import cv2`); 取证脚本也**别在顶层 import cv2**。

## 4. 复制图片到剪贴板: 一次性 `setMimeData`

- 症状: 复制"原始图"到剪贴板后是 **0×0**, 而"判据图"能复制成功
- 根因: 先 `setImage` 再 `setText(path)` —— 剪贴板只保留**一份** mime 载荷, 第二次调用把图片**冲掉**了
- 修法: 一次构造
  ```python
  md = QtCore.QMimeData(); md.setImage(img)
  if self._path: md.setText(self._path)      # 图 + 路径 都给, 粘到聊天/文档/画图都行
  QtWidgets.QApplication.clipboard().setMimeData(md)
  ```
- ⚠️ **offscreen 后端的剪贴板图片恒 0×0** → 剪贴板类断言**只能在真实 DISPLAY 下跑**

## 5. 刷新定时器会冲掉"处理结果"

- 症状: 用户看到"处理后的图闪一下就变回坏图"、"还是一片白"
- 根因: 500ms 定时器每跳都 `_set_frame(原始帧)` → 把"过曝切除/框选拉伸"的结果打回默认源
- 修法: **处理过的画面只在显式取图时更新**; 定时器只刷状态行 (链路/耗时)
- 回归断言: 连调 3 次 tick 后画面**逐位不变** (`np.array_equal`)

## 6. "显示了" ≠ "用上了" (最容易骗过自己的坑, 用户连报两次)

- 症状 A: 手动框选**只换了显示控件** (`wid.set_frame_rgb`), 抽象层 `_last_rgb`(推理输入) 没换
  → 用户看着圈了, 判据/检测仍按旧帧算 ⇒ 现场反馈「没有拉伸到那部分」
- 症状 B: 手动框选的生效条件里带了某开关 (`and chk_expfix.isChecked()`) → **开关一关手选被静默忽略**,
  掉回默认源 ⇒ 现场反馈「选了没用 / 又变回坏图」
- 修法 (两条):
  1. **显示与推理输入同一入口更新** (`_set_frame()` 统一), 并断言 `_last_rgb.shape == 目标形状`
  2. 优先级写死 **手动 > 自动 > 默认**, 手动与任何开关**解耦**; 状态行显示**当前来源**
     (`判据图来源: 手动框选 · 框 (x,y,w,h)` / `自动裁切` / `默认源`) —— 让人一眼知道结果是谁给的
- 附带: 人圈的地方可能是错的 —— 给一个「🎯 自动识别并框」兜底按钮 (算法定位 + 标在画面上 + 打印坐标/指标),
  并在框内指标上给**客观数字**告警 (如"框内饱和 61% → 拉伸后仍会一片白, 建议缩小/上移框")

## 配套: 让 agent 能"看见"用户在界面上选了什么 (agent 无截图通道、不读图)

用户问「我圈的你能看到么」时, 正确姿势**不是**截图, 而是**读落盘状态**:

```python
# 每次交互(拖框/取图/改倍数)落盘, 窗口侧一行 json.dump 的事
reports/<console>_state.json = {
  "ts": "...", "roi": [x0,y0,x1,y1], "k": 2.0, "judge_src": "手动框选",
  "judge_shape": [h,w,3], "orig_shape": [...], "roi_meta": {框内饱和/死白行/Tenengrad/几何描述},
  "camera"/"frame_tag": "..." }
```
- 用户说"我圈好了/你能看到么" → agent **读这个文件**即可核对坐标与结果, 不必让用户转述
- 数字可断言 (饱和度/死白行/边缘能量), 比截图更可靠; 还能据此判断"人圈的地方对不对"
  (实测: 用户圈 `y 552~744`, 而金手指实测在 `y 949~1134` → 差 541px, 直接可用数字反馈)
- 同时把**同样的数字**显示在界面上 (框内饱和/死白行/Tenengrad) → 用户自己也能判断圈对没圈对

## 迭代纪律 (本次现场节奏)

- GUI 改码**必须重启**才生效 (本工程无 autosave) → 每轮改完 `studio_ctl.sh restart` 并查启动日志错误数
- 用户报"改了还是老样子"时, 先分清: ① 窗口是改前打开的旧实例 (需重开) ② 真 bug ③ 环境态
  —— 本session里三条都遇到过, 逐条排除比争论有效
- 每次改完**跑两层回归**: offscreen (逻辑/接口) + **真桌面** (窗口尺寸/控件截断/剪贴板/最大化) ——
  "offscreen 全绿 ≠ 人能用"是本工程反复验证过的
