# GUI 调试时的两类「假故障」— 无响应弹窗 + 断点阻塞 (2026-09-15 实测, 原生 Ubuntu 24.04 + GNOME 46 X11)

## 1) `studio.py is not responding` 弹窗 (Mutter 存活探测)
症状: 调试中反复弹「未响应 / 等待 / 强制退出」对话框, GUI 本身没崩 (进程活着)。

根因: 应用 X11 窗口在 `org.gnome.mutter check-alive-timeout` (默认 **5000 ms**) 内没有回应
Mutter 的 `_NET_WM_PING`。触发场景:
- **停在断点** (VSCode debugpy `--configure-qt none` 拉起, 主线程停在 bp) → Qt 事件循环完全停止;
- 主线程被同步长调用阻塞 (网络/训练/大文件 IO 写在主线程)。

一键关掉探测 (X11, 立即生效):
```bash
echo $XDG_SESSION_TYPE                       # 本次 = x11
gsettings range org.gnome.mutter check-alive-timeout   # type u (uint32)
gsettings set org.gnome.mutter check-alive-timeout 0   # 0 = 关闭存活检测
gsettings get org.gnome.mutter check-alive-timeout     # 确认 uint32 0
gsettings reset org.gnome.mutter check-alive-timeout   # 调试完还原 (默认 5000)
```
注意:
- 这只让弹窗闭嘴, **不解决卡顿**。若没停断点也卡 → 真主线程阻塞, 按 SKILL.md §5
  (worker + pyqtSignal 回主线程 / QTimer 队列 flush) 修, 别用关探测掩盖。
- 屏上已存在的弹窗不会自动消失 (点"等待"即可)。
- 该键是 per-user dconf, 不需要 sudo, 不影响其它机器。

## 2) 判「是断点阻塞还是真卡死」
- `pgrep -af studio.py` 能看到 debugpy 两个进程 (launcher + adapter/`--connect`) = **跑在调试器下**,
  此时"卡住"多半是断点/单步, 不是代码 bug;
- 想确认是否真的死在主线程: 在调试器里看主线程栈是否停在 `app.exec_()`, 或在代码里
  `faulthandler.dump_traceback_later(20)` 落盘 (见 references/qt-mutter-native-gnome.md)。

## 3) 附带: Windows 侧死锁类问题的处理顺序 (本次实际顺序)
1. 先确认进程/会话类型 (`$XDG_SESSION_TYPE`, `pgrep -af`) — 别先改代码;
2. 先用 WM 层开关消除噪音 (上面 gsettings), 让调试能继续;
3. 调试完再按根因修主线程阻塞; 最后 `gsettings reset` 还原。
