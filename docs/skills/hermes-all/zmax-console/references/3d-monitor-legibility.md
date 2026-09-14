# 3D / 监视界面「看得懂」规范 (v3.0.2 → v3.0.9, 2026-08-25 老倪连续 6 轮纠正)

同一天里老倪对 3D 状态空间视图提了 6 次意见, 每次都不是"美化"问题而是**可读性/正确性**问题。
这份是通用规范 — 任何监视/可视化界面 (3D 视图、Scope、数据总线、大屏) 都按这里做。

## 铁律 1: 信号名 = 画布节点名 / 源模块名 (老倪纠正 2 次)
> 「信号直接写 前馈加速器 就得了, 为什么要夹带 前馈预测呢?」
> 「残差 接触是什么? 改成实际的模块名字」

- ❌ 自造词/夹带词: 前馈建议 / 前馈预测 / 融合指令 / 残差·接触 / 反馈校正
- ✅ 一律用 `flows/*.json` 里的节点名 = 源码模块名:
  | 数据 | 正确名字 | 源码出处 |
  |---|---|---|
  | u_ff | ⚡ 前馈加速器 | parallel.FeedforwardAccelerator |
  | u_fb | 🧪 状态校正器 · 残差方向 | cognition.state_correction (**不是**估计器!) |
  | u 融合 | 🧭 动作调制器 (下发 action) | cognition.ActionModulator |
  | u_sat | 🛡 安全执行边界 (饱和限幅) | safety.saturate |
  | latent | 🔮 自适应状态估计器 · x̂ | parallel.AdaptiveStateEstimator |
  | contact_p | 🧪 状态校正器 · 接触概率 | cognition.contact_probability |
  | 末端轨迹/几何 | 🌍 物理世界 (· 末端轨迹) | execution.PhysicalWorld |
- 改名时**全库搜一遍**旧措辞 (`grep -rn "前馈建议\|前馈预测"`), simulink 日志/HTML 面板/数值面板一起改。
- 归错模块比名字难听更严重: u_fb 原来挂在"状态估计器"名下, 而它其实是校正器算的残差。

## 铁律 2: 图层勾选框必须覆盖该层**全部** GL item key
老倪:「所有的选项都取消了, 但是屏幕还有一小段绿线和黄线, 这是啥?」
根因: `_apply_layer_visibility(key)` 只查 `_gl_items[key]`, 而箭头存的是
`<key>_line` / `<key>_tip` / `<key>_head` (+ ufuse 专有 `ufuse_sphere`), 图层 key 本身不在字典
⇒ `get()` 返回 None 直接 return ⇒ **四个勾选框点了完全没作用**, 用户还以为是坐标轴。
- 收集顺序: `key` 本体 + 所有后缀族 + 特判联动 (scene → arm + 文字标注)
- 辅助元素也要纳入图层 (网格 `grid` / 坐标轴 `axis`), 别用 `_grid`/`_axis` 这种下划线私有 key —
  用户关不掉的东西一定会被问"这是啥"
- pyqtgraph `GLAxisItem` 固定配色: **绿=Z 黄=Y 蓝=X** (源码 updateLines), 画在世界原点;
  近景取景下原点常在画面外 (实测 fit/top 档 0px, 只有"视频同框"档可见) → 默认关
- 验收: 逐层 开→关 非背景像素必须归零; **全部取消后整幅画面非背景像素 = 0**

## 铁律 3: 比例尺按实际量程定, 不能凭想象
老倪:「为什么是一个绿色圆点和一个绿色线段?」
根因: 箭头长度 `clip(|u|,0,1) × 80mm`, 而真实 |u_ff| 只有 **0.031~0.331 m/s**
→ 箭头 2.5~26mm, 近距缩到 2mm ⇒ 屏幕上只剩箭尖那个点。
- 正确: 先量信号量程, 再按量程归一化 + 最短保底
  `length = clip(|u|/u_ref, 0.22, 1.0) × L_max`  (u_ref=0.35 m/s, L_max=0.10 m → 22~77mm)
- 方向必须有**锥形箭头头** (`MeshData.cylinder(radius=[r, 0.0])` + Rodrigues 旋转), 光线段看不出朝向
- 再加**方向人话**: `−X(朝孔位) / +X(离孔位) / ±Y(朝台面内外) / ↑抬升 / ↓下压`
  (主分量 >0.25 才写, 全小于则"几乎静止")

## 铁律 4: 3D 文字标注 — 自绘覆盖层 (GLTextItem 在本机不显示)
现象: `gl.GLTextItem` 加进去毫无反应。源码 `paint()` 里是 `QPainter(self.view())` 直接画控件表面,
本机 (Mesa 25.2 + QOpenGLWidget) 实测**完全不渲染** — 抓真实窗口比对, 清空/恢复文本像素差 **0**。
✅ 可用方案 `LabelOverlay`: GL 画布上叠一个透明 QWidget
```python
self._overlay = LabelOverlay(self.view)          # 子控件, WA_TransparentForMouseEvents
self._overlay.setGeometry(0, 0, self.view.width(), self.view.height())
# paintEvent: 深底圆角(13,17,23,205) + 彩色文字 + 一条引线连到目标点
```
实测有效: 屏幕文字像素 11257 px (插销 598 / 孔口 737 / goal 868 / 前馈加速器 4316 / 动作调制器 4705)

## 铁律 5: 标注必须跟着视角走 — 存世界坐标 + 相机指纹看门狗
老倪:「3D空间的文字, 没有跟着图像走, 需要同步位置」
根因: 屏幕坐标只在**换帧**时算, 鼠标旋转/缩放后投影变了却不重算。
```python
# ① 标注只存 (世界坐标, 文字, 颜色)
# ② _refresh_label_positions(): 用 project_world 重投影, 出画的直接不画 (别停在原地误导)
# ③ 相机指纹看门狗 20Hz (QTimer 50ms):
sig = (center.x/y/z, distance, elevation, azimuth, rotation四元数, fov, view.width, view.height)
if sig != self._cam_sig: self._cam_sig = sig; self._refresh_label_positions()
```
⚠️ 不要依赖 `installEventFilter(view)` 抓鼠标: 本机实测过滤器收不到 view 的鼠标事件
(`app.sendEvent(view, MouseMove)` 后标注 0/5 更新; 直接调重投影 5/5 更新) → 轮询指纹最稳。
⚠️ 关窗必须 `closeEvent` 停掉播放 + 看门狗两个 QTimer (工程铁律: QTimer 不清理 → 析构期崩溃)。
实测验收: 旋转/再旋转/缩放 4 档/切两种取景/窗口 resize/换帧 → 与真实投影逐点一致 (≤1px)。

## 铁律 6: 数据层 additive 穿透遮挡
末端轨迹恰好走在机械臂/夹爪实体位置 → 默认深度测试下被完全挡住 (实测只剩 5px)。
traj / 四层动作箭头 / 锥头 / YOLO 框 / 估计线 / 接触球 全部 `setGLOptions("additive")`, 线宽 2→3.5。

## 像素验收的三个坑 (老倪零容忍"看起来对了")
1. **framebuffer 抓不到覆盖层**: `grabFramebuffer()` 只有 GL 内容, QPainter 覆盖层/GLTextItem 一律抓不到
   → 验证文字必须抓 **X11 真实窗口** (`xdotool getwindowgeometry --shell <id>` 拿绝对坐标 + ffmpeg x11grab 裁剪)
2. **窗口被别的窗口压住**: 裁出来是微信/studio 的画面 → 先确认裁出的区域"暗像素占比 ≥70%" 再信数据,
   必要时把 studio `xdotool windowminimize` 3 秒再截, 完事 `windowmap` 恢复
3. **判据方向反了**: 标注带半透明深底板 → 它会**盖住**亮像素, "亮像素总数"反而下降 (实测 −1111 px)
   → 用**标注文字自身颜色**逐色统计, 不用"亮像素总数"; 颜色掩码用相对判据
   (`b>r+55 & b>g+30`) 而不是绝对色距 (additive 混色会把颜色抬亮出容差)

## 探针 (全部离屏/可复跑, 别手敲)
```bash
DISPLAY=:0 gui-venv311/bin/python tools/probe_view_pixels.py [帧号]   # 画面成分逐元素像素占比 + 文字色块图
DISPLAY=:0 gui-venv311/bin/python tools/probe_text_labels.py          # 文字标注是否真显示 (抓真实窗口)
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/probe_view_match.py   # 视角/内容/轨迹三项一致性
```
