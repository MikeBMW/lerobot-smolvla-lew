# 字号/DPI 口径 + 支持文件索引 (2026-09-26)

## 1. 老倪字号口径 (连纠两次: "字体太小, 看不清" → "比刚才好点, 但还是太小, 再放大")

- 高分屏 (实测工位机 192 DPI) 上 QSS `font-size: Npx` 的**视觉观感约为设计值的一半** →
  12px 的数值行用户直接判"看不清"。宽屏大字号不是"美化", 是**可读性底线**。
- **一次给到位, 别小步试探**: 第一次只把 12px 提到 15px → 被判"比刚才好点, 但还是太小"。
  正解 = 直接上 **~2.3×**(12px → **28px**), 同批配 标题 **34px** / 列表 **24px** / 按钮 **20px**
  (padding 9×18), 卡内 `setContentsMargins(24,20,24,20)` + `setSpacing(14)`。
- **改完必须给客观数字**(用户按数字验收, 不接受"我觉得大了"): 写
  `tools/measure_<组件>_fonts.py` → offscreen 真实例化该组件 → 逐行打印
  `font().pixelSize()` / `fontMetrics().height()`。本次实测: 主数值 28px/行高 39 ·
  标题 34px/行高 47 · 时间戳 18px/行高 26 · 卡片 sizeHint 570→734px。
- 卡片变高前确认父容器**可滚动**(首页在 QScrollArea + `setWidgetResizable(True)` → 安全;
  固定行高的面板会截断底部行)。
- 先量后改再量: 报"原来 X px → 现在 Y px, 行高 Z"。没量之前别反复调(会白跑轮次)。
- 重启才生效: 改完 studio.py 要杀旧实例再起(否则用户看到的还是旧字号, 会再报"没变")。

## 2. 本技能支持文件索引 (新会话优先看这几个)

| 文件 | 何时看 |
|---|---|
| `references/periodic-timer-blocking-io-worker-thread-2026-09-26.md` | **GUI 卡顿根因家族**: 定时器槽在主线程做阻塞 I/O (HTTP / 子进程 / `time.sleep`) → 主线程被冻; 含定量方法(逐调用耗时 + 心跳最大间隙)与"采集搬 QThread + 代理收 setText"的修法。改任何刷新/轮询逻辑前必读 |
| `scripts/ui_jitter_probe.py` | 主线程 10ms 心跳测"最大间隙"(= 用户感知的"卡一下"), 直接可跑 |
| `references/main-thread-io-and-button-evidence-2026-09-16.md` | 主线程 I/O + 按钮取证(同类问题的更早一例) |
| `references/gui-patch-safety-and-side-effects-2026-09-19.md` | 大 GUI 单文件改动的安全流程 |
| `references/display-refresh-honesty-and-window-stubs-2026-09-17.md` | 刷新/显示的"看着变了其实没变"类坑 |

## 3. 一句话铁律(与 §1 同源)

主线程只做**渲染**; 取数(HTTP/子进程/sleep/重算)一律进工作线程;
**字号这类用户主观项, 用客观测量 + 一次给足, 别小步试探**。
