# 定时刷新的槽里做阻塞 I/O = 整个界面"打开就卡" (2026-09-26 实测, 已量化)

用户原话: 「控制台，为什么打开感觉很卡顿？什么引起的？修好，不要有这么大的延迟」
上一轮同项目的"按钮慢"见 `main-thread-io-and-button-evidence-2026-09-16.md`(那是**点击槽**);
本篇是**定时器槽**——影响面更大: 不是某个按钮慢, 而是**整个事件循环被周期性冻住**, 表现为"打开就卡、鼠标一顿一顿"。

## 1. 先量: 主线程事件循环最大间隙 (人眼卡顿的客观口径)

不要猜渲染/定时器数量, 直接量"心跳间隙":

```python
# 主线程跑 10ms 心跳, 记录相邻两次心跳的最大间隔 = 用户感知的"卡一下"
gaps, last = [], [time.time()]
def beat():
    now = time.time(); gaps.append((now - last[0]) * 1000.0); last[0] = now
hb = QTimer(); hb.timeout.connect(beat); hb.start(10)
# 跑 N 秒 (期间 app.processEvents()) → 报 max(gaps) / 中位 / >100ms 的次数
```

再逐项拆"阻塞体到底卡在哪"——用 monkeypatch 记录每次外部调用耗时 (比读代码快):

```python
_orig_run = subprocess.run
def timed_run(*a, **k):
    t0 = time.time()
    try: return _orig_run(*a, **k)
    finally: CALLS.append((round((time.time()-t0)*1000, 1), str(a[0])[:70]))
subprocess.run = timed_run
# 同理包 urllib.request.urlopen → 打印 CALLS 排序前 6
```

本机实测(硬件资源卡 2s 定时刷新):

| 项 | 阻塞 GUI 线程 |
|---|---|
| `HTTP 127.0.0.1:8799/api/hardware` | **1266 ms** ← 主凶 |
| CPU 采样 `time.sleep(0.12)` | 120 ms |
| `nvidia-smi` (subprocess) | 24 ms |
| **每次 refresh 合计** | **1414 ms / 每 2s 一次 ⇒ 主线程 ~70% 时间被冻** |

修前后同口径 A/B (主线程 10ms 心跳最大间隙):

| | 最大间隙 | >100ms 卡顿次数 (8s 内) |
|---|---|---|
| 旧: 主线程同步采集 | **1415.2 ms** | 4 |
| 新: 采集搬工作线程 | **15.8 ms** | **0** |

## 2. 修法: 采集/渲染分离 + 工作线程 (不用改 UI 逻辑)

关键技巧: **不用手改几十处 `label.setText()`** —— 给"取数函数"套一个轻量代理, 把控件写入自动收成 dict:

```python
def _collect(_rs):                      # ← 参数改名, 函数内再绑 self=代理
    """阻塞 I/O 全在这里; 只允许工作线程调用"""
    out = {}

    class _Rec:                         # 模拟 QLabel 的最小接口
        __slots__ = ("k",)
        def __init__(s, k): s.k = k
        def setText(s, v): out[s.k] = v  # noqa: N802

    class _Proxy:
        def __getattr__(s, name):
            return _Rec(name) if name.startswith("lb_") else getattr(_rs, name)
            # 非 lb_* 属性/方法 (self._sh / self._fetch_remote / self._src_cache) 全部走真 self

    self = _Proxy()                     # ← 原函数体一行不用改
    import shutil
    try:
        ... 原 refresh() 的整段取数代码 ...
    except Exception as e:
        self.lb_ts.setText("采样失败: %s" % str(e)[:40])
    return out
```

前提核对 (动手前 grep 一遍, 30 秒): 函数体内**没有 `self.X = ...` 赋值**、控件名统一前缀(`lb_*`)、
被调用的自有方法(`self._fetch_remote()`)经代理走真实例。
> 若有过 `self.X = ...` 赋值, 给 `_Proxy.__setattr__` 加转发即可。

GUI 侧只剩贴字符串 (零 I/O), 工作线程循环采集:

```python
class _HwFetcher(QThread):
    got = pyqtSignal(dict)
    def __init__(self, card, interval=2.0):
        super().__init__(card); self.card, self.interval, self._stop = card, float(interval), False
    def run(self):
        while not self._stop:
            try:
                d = self.card._collect()
                if d: self.got.emit(d)
            except Exception: pass
            waited = 0.0
            while waited < self.interval and not self._stop:
                time.sleep(0.1); waited += 0.1
    def stop(self): self._stop = True

# __init__: 删掉原来的 QTimer(2000)+refresh, 换成
self._last = {}
self._worker = _HwFetcher(self, interval=2.0)
self._worker.got.connect(self._on_fetched)   # _on_fetched = 存 _last + 调 refresh()
self._worker.start()

def refresh(self):                            # GUI 线程, 零 I/O, 实测 <1ms
    for k, v in (self._last or {}).items():
        lb = getattr(self, k, None)
        if lb is not None:
            try: lb.setText(v)
            except Exception: pass
```

配套要点:
- **数据实时性不变**: 采集间隔仍 2s, 只是不再占用主线程。
- **"刷新"按钮语义**: 清掉源缓存(`self._src_cache=None`)→ 下一轮后台采集自动重探, 不要在点击槽里同步重取。
- **静态清查同类风险**: `grep QTimer *.timeout.connect` 出的每个槽都过一遍"体内有没有 subprocess/urlopen/sleep/ssh",
  本项目 1s 的 `_update_stats`、100ms 的 ws_poll 体内干净 → 只剩这一处, 不用全改。

## 3. 度量脚本的两个坑

- **别用 `| tail` 看 rc**: `python x.py | tail` 的退出码是 tail 的 → 脚本崩了也报 0 (同项目曾因此把"仿真链路已跑通"假报成功)。
- **cyclonedds/子线程在解释器退出时 core dump**: offscreen 度量跑完直接 `sys.stdout.flush(); os._exit(0)`,
  不要走 Qt/DDS 的清理路径 (否则看到 "timeout: the monitored command dumped core" 误以为被测代码崩了)。

## 4. 复用件
- 度量脚本: `scripts/ui_jitter_probe.py` (本技能) —— 直接跑就能拿到"最大卡顿间隙"的前后对比。
- 逐调用耗时脚本模板见本文 §1 第二段 (monkeypatch subprocess.run / urlopen)。
