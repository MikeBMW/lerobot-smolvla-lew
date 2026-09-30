# GUI 卡在断点 → GNOME 弹「xxx is not responding」(X11) — 2026-09-15 实录

**症状**: 调试 PyQt5 应用 (studio.py 跑在 VSCode debugpy 下), 一停断点就弹
「studio.py is not responding / 等待 / 强制退出」。用户问的是"怎么不让这个弹窗弹出来"。

**根因**: 停在断点时 Qt 主线程不再处理事件 (X11 `_NET_WM_PING` 无响应) > mutter 的
`org.gnome.mutter check-alive-timeout` (默认 5000ms) → GNOME 判定"未响应"并弹窗。
**不是崩溃、不是卡死**, 是调试会话的正常暂停被桌面误判。

**修 (X11 会话, 立即生效, 无需重启)**:

```bash
gsettings get  org.gnome.mutter check-alive-timeout     # 默认 uint32 5000 (ms)
gsettings set  org.gnome.mutter check-alive-timeout 0   # 0 = 关闭无响应探测 → 不再弹
gsettings reset org.gnome.mutter check-alive-timeout    # 调完想还原则恢复默认
```

**回答口径 (重要)**:
1. **先给"怎么不弹"的开关, 再解释** —— 用户在调试现场要的是立刻能用的一句话 + 命令。
2. 明确说清:**这只让弹窗闭嘴, 不修卡顿本身**。若没停断点也卡, 那是真阻塞, 得按既有铁律把耗时活
   挪到 worker 线程 + `pyqtSignal` 回主线程 (参见 SKILL.md 的崩溃铁律)。
3. 现场核对会话类型: `echo $XDG_SESSION_TYPE` / `loginctl show-session <id> -p Type` —— 该键对
   **X11** 会话有效; 先确认再给命令, 别凭印象。
4. 顺手确认进程真实形态: `pgrep -af '[s]tudio.py'` + 读 `/proc/<pid>/cmdline`
   (本次发现它跑在 `debugpy.launcher` 下 ⇒ 断点暂停的证据也一起给用户)。

**为什么不是"环境问题"而是可复用知识**: 同一台开发机每次用 VSCode 调 Qt GUI 都会遇到;
把开关 + 恢复命令 + "不修卡顿"的边界一起记住, 下次直接给答案。
