# 3D 视图"打不开" = 默认静态第 0 帧 (2026-09-02)

## 症状
老倪: "运行的时候, 为什么 3D视图 打不开呢? 我需要看到实际的动作渲染视频"

## 排查路径(重要: 先分清真"打不开" vs "静止")
1. **窗口是否存在**: `DISPLAY=:0 xwininfo -root -children | grep -E '"[^"]*"'` 找
   "3D 分层视图" 窗口。存在 = 窗口创建成功。
2. **是否黑屏/有内容**: `scrot -u` 截窗口 + cv2 分析: 非背景像素 >5% = 有渲染;
   橙色像素 (HSV 5-25, 80-255, 80-255) >0 = metaworld 机械臂已渲染。
3. **是否在动(本次根因)**: 隔 1s 截两图 `cv2.absdiff` — 变动像素 ≈0 = **画面静止**。

## 根因
DreamView3D 默认 `_playing=False`: `set_trajectory` 只 `_update_frame(0)` 显示第 0 帧,
`_timer` 未 start — 必须手动点「▶ 播放」才有动画 (60ms/帧≈16fps)。窗口/机械臂/轨迹
全都正常渲染, 但用户看到静态画面 = "打不开/看不到动作"。

## 修复
`ss_dreamview.py set_trajectory` 末尾, n>0 时自动播放:
```python
if n > 0:
    self._update_frame(0)
    self.lbl_frame.setText(f"0 / {n - 1}")
    if not self._timer.isActive():          # 加载即自动播放
        self._playing = True
        self.btn_play.setText("⏸ 暂停")
        self._timer.start(60)
```
验证: 构造 DreamView3D(tr) → `dv._playing and dv._timer.isActive()`; 跑 1.2s
`app.processEvents()` 后 `_idx` 从 0 推进到 ~18 = 动画在动。

## 配套排查经验
- **GUI 进程 stderr 重定向**: studio.py 常跑成 `>/tmp/studio_launch.log 2>&1`,
  先 `tail /tmp/studio_launch.log`(注意 "Unknown property cursor" 刷屏无害, 要 grep
  Traceback/Error 过滤)。
- **py-spy 不可用时判主线程卡死**: `/proc/<pid>/task/<tid>/stat` 的 utime/stime +
  wchan (`poll_schedule_timeout` = 事件循环正常等待; 无线程烧 CPU = 没卡死)。
- **xdotool 点按钮定位难**: Qt 按钮不是 X 窗口, 截图+cv2 找按钮文字可行但费时;
  优先直接查 open_ss_3d 代码路径 + 独立进程构造组件复现, 比猜坐标高效。
- **3D 视图已有坑串联**: pyqtgraph shader 跨上下文(只复用不新建)、GNOME 黑屏
  (AA_UseSoftwareOpenGL 勿开) — 详见 SKILL.md 相关章节。
