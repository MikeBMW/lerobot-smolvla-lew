# VcXsrv 下 GUI 交互坑实战 — 悬停ID / QMenu黑屏 / 闪退 / 多实例 (2026-08-12)

## 1. 悬停显示 (hover) 完整链路 — 缺一不可
VcXsrv 下 QGraphicsView 悬停要三层都满足, 缺一个就"悬停无效/迟钝":

1. `view.setMouseTracking(True)` — 无按键时 mouseMove 事件才到 view (SimCanvas init)
2. item 类自己实现 `setAcceptHoverEvents(True)` + `hoverEnterEvent/hoverLeaveEvent` —
   注意 SimNodeItem 原本**没有** hover 事件 (setAcceptHoverEvents 只在 SimLinkItem 连线类里),
   补在节点类 __init__ 尾部
3. 即使都开了, VcXsrv 网络 X 下无按键 mouseMove 事件仍不可靠 (用户报"点击才显示") →
   最终方案: `QCursor.pos()` 定时轮询 (150ms), mouseMove 与轮询共用 `_update_hover_at(vp_pos)`

轮询安全四要素 (防狂闪/闪退 — 80ms 轮询曾导致"屏幕狂闪+闪退"):
- 鼠标不动不重绘: 缓存 `_last_hover_pos`, 相同直接 return
- `QTimer(self)` parent 绑定 — 防关闭时 timer 回调崩溃
- hover_items 里每个 item 检查 `it.scene() is not None` — 节点删除后残留引用 → update() 崩溃
- `self.isVisible() and self.underMouse()` 前置检查, 全部包 try/except

画布节点 ID 显示的用户需求演进: 常显 → 悬停显示 → 白色 #e6edf3 (不要蓝色) →
右下角 (QRectF(8, h-16, w-16, 14) AlignRight) → 不遮挡节点标题/desc;
row_bg 背景行不显示 ID (paint 里 `type != "row_bg"` 判断 + hover 检测同样跳过)。
节点 ID = VEH.5.顺序号 (加载后按 y→x 布局排序 001~020, `_assign_veh5_ids`),
不是模块库跳跃编号 (用户明确纠正过)。

## 2. QMenu 右键菜单黑屏无字 — 根因链
1. 局部 QMenu QSS (深色 + border-radius) → VcXsrv 合成失败黑屏 → 删局部 QSS
2. "复现" → 根因是 **全局 app.setStyleSheet 里的 QMenu 规则** (studio.py 两处) 仍作用所有菜单 → 全删
3. 白底后出现"黑条" → 菜单项 emoji (📖⚙️📂▶) 缺字形渲染成黑块 → 菜单项去 emoji

结论: VcXsrv 下 QMenu 一律系统默认样式 — 不加 QSS, 菜单项不加 emoji。
QMenuBar (菜单栏) 的 QSS 可以保留, 黑屏的是弹出 QMenu。

## 3. VcXsrv 崩溃诊断 ("屏幕狂闪" + 闪退)
现象: 屏幕狂闪 → GUI 退出, 日志 `qt.qpa.xcb: could not connect to display 172.18.80.1:0`, exit 134
真因: vcxsrv.exe 挂掉 (不是代码问题) — 狂闪是 X 假死前兆
诊断:
- `tasklist.exe | grep -i vcxsrv` — 进程没了
- `timeout 3 bash -c 'echo > /dev/tcp/172.18.80.1/6000'` — 端口不通
重启:
```
powershell.exe -NoProfile -Command "Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'"
```
注意: VcXsrv 重启后 xdotool search / xwininfo 可能查不到窗口 (查询工具异常, 不代表窗口没显示),
以进程存活 + 用户所见为准。

## 4. 多实例残留 (用户: "你怎么打开两个控制台")
- `pgrep -f "python3 studio.py"` 会误匹配 hermes 的 bash -lic 包装 shell → 杀不干净
- 正确清进程: `ps aux | grep "python3 studio.py" | grep -v grep | grep -v bash | awk '{print $2}' | xargs -r kill -9`
- 清窗口残留: `xdotool search --name "XSpace Studio" | xargs -r -I{} xdotool windowkill {}`
- 每次重启 GUI 前先清残留, 只留一个实例

## 5. 外部源码显示 (node_logic _EXTERNAL_LOC)
- 截取外部源码用**符号名定位** (文件内搜 "class Xxx"/函数名), 不要依赖写死的行号 —
  映射行号与实际错 1 行 → 截到空行/错误内容 → 面板只显示"源码结束"标记
- `_EXTERNAL_LOC[key] = (abs_path, line, "class Xxx")` — line 仅作 fallback
- 节点"没有独立逻辑"= match_node 没匹配到注册 → 补 `_reg(key, [关键词], desc, fn)` + `_EXTERNAL_LOC`
- 同一文件可映射给多个节点 (YOLO 3D / 2D→3D / State Adapter 都指 yolo_state_aligner.py 的 class YoloStateAligner)

## 6. 启动加速 (27s → 8s)
- 重量级模块 (SimulinkModule 200+ 按钮) 延迟创建: 构造期 `self.simulink = None` +
  `QTimer.singleShot(400, self._init_simulink)` — 主窗口先显示
- 延迟创建时记录 `self._simulink_index = self.stack.count()`, 创建后 `insertWidget(index, sim)` 插回原 tab 位
- 不要用 show→hide→80ms 再 show (加重闪烁, 已回滚)
