# 取证模式: "入口行为/状态同步" 与 "替代数据源真出帧" 怎么验 (2026-09-17 实测)

两类改动**不能用同一种证据**, 混用会得到假 PASS:

## ① 行为级 (入口按状态取参 / 单例窗口复用对齐) — 真函数体 + 假窗口对象

被测对象是"读应用状态 → 决定参数 → 同步窗口"的逻辑, 不必真开 GUI:
- 用**磁盘上真函数体** (import 真模块取方法), 只把窗口/屏幕对象换成桩 (`FakeWin` / `FakeCb` 记录
  `setCurrentIndex` 调用次数), 屏幕用假 `QRect` 列表注入 (PyQt 类属性不让改 → 换掉模块命名空间里的 `QtWidgets`)。
- 覆盖三个方向: 旧状态≠新状态 (必须切) × 2 方向 + 两边一致 (不许乱切, 断言调用次数 0)。
- ⚠️ **桩绑定 `@staticmethod` 必须 `staticmethod(...)` 包一层**, 否则被当实例方法绑 self → TypeError 被
  被测代码的 `except Exception: pass` 吞掉 → **"不许动"的 case 全部假 PASS**。
  排查口诀: 若某个**本该发生动作**的 case 也 `moved/switched=False`, 先怀疑异常被吞, 不是逻辑对
  (诊断: 临时把 `except Exception: pass` 换 `traceback.print_exc()` 跑一遍, 定位后还原)。
- 真窗口级 A/B 台架见 pyqt5-gui-development `scripts/multiscreen_clamp_probe.py`
  (老实现从 `git show HEAD:<file>` 抠出来跑同一台架 — 同台架 old❌/new✅ 才算证据)。

## ② 数据源级 (换了源, 真的出帧了吗) — 直接起真采集器收 N 帧

"窗口不报错 / 日志说已启动"**不是**数据源可用的证据 (同族教训: 影子臂 `calls>0` 实为空转)。
做法: 绕过窗口, 直接实例化真采集器 (`g = _SimGrabber(q, False); g.start()`), 限时收 ≥3 帧, 逐项断言
**形状 + 来源标识 + 设备身份**:
```
帧1: shape=(480, 480, 3)  src=sim:metaworld corner2  device=mujoco 渲染 (非真机相机)
```
对真机源同理: 断言 `device` 里的 VID:PID/序列号 + `age_s`/`seq` 递增 (别只看"有帧")。

## ③ 报告口径 (老倪)

- 他问"为什么" → 先**根因 + 证据** (现场复现数字 / 代码文件:行号 / 真跑输出), 别先给方案列表。
- 说清"改了什么"(哪些文件/行为变化) + 需要他做什么 (重启 GUI / 重开窗口)。
