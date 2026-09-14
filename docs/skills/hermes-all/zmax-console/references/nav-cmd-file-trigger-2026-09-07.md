# 外部命令文件触发 (nav-cmd-file-trigger) — 2026-09-07

老倪远程指挥时: "别瞎点了" → "增加技能, 直接打开simulink模式"。
盲点像素被明确纠正; 正解 = GUI 内确定性命令通道。

## studio.py 内置代码段 (v5.0.0+, 主窗口 __init__ 尾部; 丢了可重贴)

```python
# 📡 外部命令文件触发: 监控 /tmp/zmax_nav_cmd — 写入一行命令即执行
self._nav_cmd_timer = QTimer(self)
self._nav_cmd_timer.timeout.connect(self._poll_nav_cmd)
self._nav_cmd_timer.start(300)
self._nav_cmd_seen = set()

def _poll_nav_cmd(self):
    try:
        p = "/tmp/zmax_nav_cmd"
        if not os.path.isfile(p):
            return
        with open(p) as f:
            lines = [l.strip() for l in f if l.strip()]
        os.remove(p)  # 先删防重复
        for line in lines:
            if line in self._nav_cmd_seen:
                continue
            self._nav_cmd_seen.add(line)
            try:
                if line == "simulink":
                    self._on_nav("simulink")
                elif line == "ss_canvas":
                    _oneshot(self, 600, self._open_ss_canvas_cmd)
                elif line == "ss_3d":
                    _oneshot(self, 1200, self._open_ss_3d_cmd)
                elif line in self.modules:
                    self._on_nav(line)
                else:
                    self.statusBar().showMessage(f"📡 未知命令: {line}", 2500)
            except Exception as _e:
                self.statusBar().showMessage(f"📡 命令失败 {line}: {_e}", 3000)
    except Exception:
        pass

def _open_ss_canvas_cmd(self):
    if getattr(self, "simulink", None) is not None:
        self.simulink.open_state_space()

def _open_ss_3d_cmd(self):
    if getattr(self, "simulink", None) is not None:
        self.simulink.open_ss_3d(on_top=False)
```

注意: studio.py 顶部已有 `from PyQt5.QtCore import ... QTimer ...` (178 行附近),
不需要另起别名。类内方法缩进对齐。

## 用法
```bash
echo simulink > /tmp/zmax_nav_cmd     # 切 Simulink 页 (QStackedWidget idx 10)
echo ss_canvas > /tmp/zmax_nav_cmd    # 开状态空间画布
echo ss_3d > /tmp/zmax_nav_cmd        # 开 3D 视图
echo training > /tmp/zmax_nav_cmd     # 任意 modules key: home/dataset/training/...
```
写后 `ls /tmp/zmax_nav_cmd` 消失 = 已消费 (轮询 300ms; 画布/3D 另有 600/1200ms 延迟补偿)。

## 为什么不用 xdotool 盲点
- 像素找按钮 (PIL 色块聚类/猜卡片坐标) 多轮失败: 深色主题无浅色大块可锚、
  青色点缀遍布全屏非卡片色、窗口双实例 (一个 desktop=-1 幽灵) 位置混淆。
- 盲点成本: 每轮截图→分析→猜坐标→点→再截图验证, 且点错污染界面状态。
- 确定性替代优先级: ① 命令文件 (运行中直达, 不重启) ② env 钩子 ZMAX_AUTO_SS* /
  ZMAX_AUTO_RUN / ZMAX_AUTO_TEST (需重启 GUI) ③ 键盘导航 ④ 像素点击 (最后手段)。

## 窗口归属判定 (xdotool 多实例混淆)
- `xdotool search --name "XSpace Studio"` 返回多个 → 同名窗口可能是幽灵/装饰。
- `xdotool get_desktop_for_window <wid>`: desktop=-1 = 隐藏幽灵; 可见 = desktop=0。
- `xdotool getactivewindow getwindowname` 确认前台; 操作前 `windowactivate <wid>`。
- GUI 中央大片黑 = Mutter map/渲染问题或窗口根本没在截图区域 — 先确认
  getwindowgeometry Position 落在截图范围内, 别把黑屏当界面状态分析。

## 相关
- zmax-console SKILL.md § 外部命令文件触发
- simulink_module.py SimulinkModule.open_state_space / open_ss_3d
- 重启 GUI: 精确 PID / `pkill -f "[s]tudio.py"` 方括号技巧 (见 SKILL.md 陷阱)
