# 控制台重启 / 启动崩溃排查 / 无显示离线取证

## 重启口径 (GUI 代码改动必须重启才生效 — 模块已在 sys.modules 缓存)

- 用 `bash tools/studio_ctl.sh {status|stop|start}`: 它按**解释器绝对路径**匹配进程, 不会自杀。
- ⚠️ `tools/gui/launch_studio.sh` **已有实例在跑时 exit 0 什么也不做** (只激活已有窗口) ⇒ 光看命令
  返回成功会误判「已重启」。判「真起来 / 真换版」三件套:
  `studio_ctl.sh status` + `DISPLAY=:0 wmctrl -l | grep -i xspace`(读窗口标题里的版本号) +
  `/tmp/studio_launch.log` 的 `Traceback|Error` 计数 = 0。
- 自杀坑: 自己的命令行里出现裸 `studio.py` 时, `pkill -f "…studio.py"` / `pgrep -f "…studio.py"` 会
  匹配到**当前这条命令自己** → 自己被杀 (SIGTERM -15)。用 studio_ctl.sh, 或模式
  `gui-venv311/bin/python studio`(不带 .py)。

## 启动即崩的签名与怎么读 (排查用)

- 签名: `QThread: Destroyed while thread is still running` + `Fatal Python error: Aborted`(退出码 134/SIGABRT),
  栈里是 DDS **进程内线程** (`dds/zmax_node.py take` ← `tools/gui/dds_hw.py _run_inproc`)。含义: 窗口收到
  **关窗请求**时 DDS QThread 还活着 → 解释器收尾时 abort。**不是 DDS 自己崩**。
- `studio.py` 的 `closeEvent` 里有一段临时诊断钩子, 会把调用栈追加到 `/tmp/closeEvent_stack.log`。
  栈形如 `main() → sys.exit(app.exec_()) → closeEvent` = 关窗请求来自**事件循环外部**(外部/系统发的),
  不是代码里显式 close。会自己长出来的日志看时间戳即可对齐是哪次启动。
- 纪律: 真因没定下来前**不要**把它写成「已修」; 要么给出可复现的判据, 要么如实报「现象+已定位层次」。

## 无显示离线取证 (不占屏、不动真机) — 面板/对话框逻辑首选

`QT_QPA_PLATFORM=offscreen` 起**真类**, 调真方法, 断言输出: 比截图快, 可重复, 不打扰现场。

```python
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "<repo>/tools/gui")
from PyQt5.QtWidgets import QApplication
app = QApplication([])              # 无显示也要先建 QApplication
import studio                       # 真模块
mw = studio.HardwareModule()        # 真类真控件
print(mw._cam_local_frame())        # 调真方法, 断言返回值/标签/源
```

- 需要事件循环的行为: 建对象后把内部状态拨到目标时刻再手调回调 (如 watcher `t0 = time.time()-17` 后调
  `_poll_reply()`), 不必真等 17s。
- 定时器/后台线程的对象要显式停掉 (`_wtmr.stop()`), 否则脚本收尾时会打警告。
- 目的: 面板取源优先序、状态栏文案、闸门判定这类**纯逻辑**都能逐条验; 真窗口截图留给「控件尺寸/裁切/布局」。
