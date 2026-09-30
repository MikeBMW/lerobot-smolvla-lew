# GUI 真机操作演示 + 窗口状态诊断 (2026-09-06 实测)

## 老倪看 GUI 操作演示时的铁律 (用户偏好, 多次纠正: "不能后台运行"/"在真机的屏幕,要打开"/"我要看到你的操作"/"截图发到飞书群"/"别偷懒")
- 自动测试/操作演示 = **窗口必须在真机前台真实可见**, 不许后台盲点。
  每步真实鼠标操作 (xdotool mousemove+click) 后 **截图 `MEDIA:/path.png` 发飞书群**。
- 用户在场时每步都要有可见结果: 点了什么按钮 → 截图 → 页面变化 → 再截图。
  不要连续盲点一堆坐标再一次性汇报 — 用户看不到过程 = 认为你没在操作。
- 录屏用 ffmpeg x11grab (见 SKILL.md §17); 录屏要在操作开始前启动并告知, 结束发文件。

## 窗口 "没显示/黑屏/关了" 的判别顺序 (本机 GNOME/Xorg 3200x2000, 实测)
1. `ps aux | grep '[s]tudio.py'` — 进程活着 ≠ 窗口可见。进程在但窗口没 = X 窗口问题, 不是崩溃。
2. `DISPLAY=:0 wmctrl -l` — 列出真实顶层窗口 + desktop 号 (XSpace 在 0)。
   注意 wmctrl/xdotool 可能列出**已 kill 实例的幽灵窗口** (标题还是 XSpace Studio) — 用
   `xdotool getwindowpid <win>` 核对 PID 是否 == 当前 studio 进程, 幽灵窗口直接 windowclose。
3. `DISPLAY=:0 xprop -id <win> WM_STATE | grep 'window state'` — **Iconic = 最小化**;
   `xwininfo -id <win> | grep 'Map State'` — **IsUnMapped = 从未显示**。
   mutter 下 xdotool windowactivate/windowmap **恢复不了 Iconic** (报
   `XGetWindowProperty[_NET_ACTIVE_WINDOW] failed`); wmctrl -i -R 也常无效。
   **最可靠 = kill -9 当前实例 → gio launch 桌面 .desktop 重新起一个** (干净窗口必 map)。
4. **窗口塌缩 1x1**: Qt 窗口几何被压到 1x1 (屏幕上看 = 消失/黑) — 进程活着。
   恢复: `xdotool windowsize <win> 3068 1936 && windowmove <win> 0 50 && windowraise`。
5. 每次操作窗口后 `xwininfo -root -children | grep -i xspace` 拿**真实当前窗口 id**
   (旧 id 缓存会误导), 再用它截图/操作。

## studio.py 启动窗口不出现 (2026-09-06 实测, -Xfrozen_modules=off 修复)
- studio.py main() **自动 `debugpy.listen(("127.0.0.1", 5678))`** — 非冻结 python 下会打
  "frozen modules" 警告且明显拖慢启动, 窗口 (main 里 `_oneshot(win, 2000, _show_ready)`
  延迟 2s show) 可能迟迟不 map。
- **成功启动方式 (本机实测窗口必出现)**:
  `DISPLAY=:0 python -Xfrozen_modules=off studio.py` (background=true),
  等 ~15-20s 再 `xwininfo -root -children | grep -i xspace` 确认 0x...000d 级窗口 map。
- 若同时跑过多个实例会残留旧 Qt 窗口/幽灵 — 先 `pkill -f "[s]tudio.py"` 清干净再启
  (方括号技巧, 见 SKILL.md 陷阱 — 别用明文 studio.py 会自杀)。
- 双击桌面图标用 `gio launch /home/ubuntu/Desktop/XSpace-Studio.desktop` (等效双击);
  launch_studio.sh 已有实例检测 (pgrep) 会转去 activate 旧窗口 — 旧窗口是坏的时
  会表现为"点了没反应", 此时直接 kill 后 gio launch。

## 桌面自动操作的可用工具链
- 窗口枚举/激活: wmctrl -l / -a / -i -R (GNOME Xorg 下比 xdotool windowactivate 可靠)
- 鼠标真实点击: `xdotool mousemove <x> <y> && xdotool click 1` (X 层真实事件, 前台可见)
- 截图: `DISPLAY=:0 scrot /tmp/x.png` 全屏; 窗口内容分析用 gui-venv311 PIL 裁窗口几何
- 窗口内容非黑校验 (PIL): `Image.open` 平均亮度>30 且唯一色>1000 = 有内容; 全黑=渲染问题
- 高分屏 3200x2000 注意: 窗口几何 (Position/Geometry) 是屏幕坐标, 裁剪截图用它
