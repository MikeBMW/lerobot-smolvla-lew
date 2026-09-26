# 控制台两大"看起来是产品坏了"的真因 (2026-09-26 实测, 都已修)

## ① 打开就卡 → GUI 主线程在做阻塞 I/O（不是机器慢）

**实测根因**：首页「硬件资源卡」`refresh()` 直接在**主线程**跑:
```
HTTP 127.0.0.1:8799/api/hardware       1266 ms   ← 主凶
CPU 采样 time.sleep(0.12)               120 ms
nvidia-smi                               24 ms
-----------------------------------------------
单次 refresh 阻塞                       1414 ms   而定时器**每 2s** 一次 ⇒ 主线程 ~70% 时间冻结
```

**度量（先量后改, 别凭手感）**
- `tools/profile_hw_card.py` — monkeypatch `subprocess.run` / `urllib.urlopen` 计时, 逐外部调用列出耗时, 一眼定位阻塞步
- `tools/measure_ui_jitter.py` — 主线程跑 10ms 心跳 QTimer, 记录**两次心跳最大间隔**（= 人眼"卡一下"）:
  ```
  旧行为(主线程同步采集)  最大间隙 1415.2 ms · >100ms 卡顿 4 次/8s
  新行为(后台线程采集)    最大间隙   15.8 ms · >100ms 卡顿 0 次        → 89×
  ```

**修法（采集进线程, GUI 只贴字符串; 改动小、可回退）**
```python
def _collect(_rs):
    """采集全部硬件数据 → {label_key: html} —— 只允许在工作线程调用"""
    out = {}
    class _Rec:
        __slots__ = ("k",)
        def __init__(s, k): s.k = k
        def setText(s, v): out[s.k] = v          # 模拟 QLabel 接口, 收进 dict
    class _Proxy:
        def __getattr__(s, name):
            return _Rec(name) if name.startswith("lb_") else getattr(_rs, name)
    self = _Proxy()          # ← 参数名改成 _rs 才可能重绑 self; 非 lb_* 属性访问回落真对象
    ...原 refresh 函数体一行不改...
    return out

class _HwFetcher(QThread):                      # 每 2s 后台采集 → 信号回主线程
    got = pyqtSignal(dict)
    def run(self):
        while not self._stop:
            d = self.card._collect()
            if d: self.got.emit(d)
            ...sleep 0.1 × 20...

def refresh(self):                              # GUI 侧: 零 I/O, 实测 <1ms
    for k, v in (self._last or {}).items():
        lb = getattr(self, k, None)
        if lb is not None: lb.setText(v)
```
**坑**：
- 代理法要求 `_collect` 体内**没有 `self.X = 赋值`**（有就加 `__setattr__` 转发）; 写前先 `awk` 扫一遍确认。
- 线程里**不能碰任何 Qt 控件**; 结果用 `pyqtSignal` 回主线程。
- 按钮触发的**推送类动作**（如「🔔 发飞书」）同样要后台线程 + 信号回填日志 —— 否则从"每 2s 卡一下"变成"点一下卡 30s"。
- 排查清单: 每个 `QTimer.timeout.connect` 的回调都过一遍, 看有没有 subprocess / HTTP / `sleep`（本次 1s 的 `_update_stats`、100ms 的 ws_poll 都干净, 阻塞源只此一处）。

## ② 画布"加载失败" / 点图标起旧 GUI → 共享检出被别的线切了分支

**现象**：弹「状态空间模型画布加载失败」; 或点桌面图标起来的是**旧版本 GUI**（少了近期功能）。

**根因（实测）**：加载只拼 `<仓库根>/flows/state_space_obs.json`。共享检出 `/home/ubuntu/lerobot-smolvla-lew`
被并行 APP 线切到 `mac-hw` 分支 → 该目录**没有 `flows/`**（画布真源只在 main 线）, 且那棵树的 `studio.py`
是旧版（v5.6.0 vs main v5.15.x）; 更隐蔽的是**桌面启动器 `Exec=` 与 `launch_studio.sh` 都硬编码了那棵树**
⇒ 用户点图标永远起旧 GUI。

**修法三件套**
1. **路径多候选**（画布/库/cicd_workflow 全走它）:
   ```python
   def _flows_path(name):
       cands = [os.path.join(_repo_root_path(), "flows", name),
                os.path.join("/home/ubuntu/zmax_rel", "flows", name),      # main worktree 兜底
                os.path.join(os.path.expanduser("~"), "lerobot-smolvla-lew", "flows", name)]
       env = os.environ.get("ZMAX_FLOWS_DIR")                             # 环境变量优先
       if env: cands.insert(0, os.path.join(env, name))
       for c in cands:
           if c and os.path.isfile(c): return c
       return cands[0]                                                    # 找不到仍返回原路径(零回退)
   ```
   取证: `tools/verify_canvas_load_fix.py`（模拟"仓库根=另一检出"仍能回落到真画布 + 画布真加载节点数）8/8
2. **启动器按自身位置定位**（禁止硬编码检出路径）:
   `GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` + `REPO_ROOT="$GUI_DIR/../.."`, venv 多候选;
   `.desktop`（桌面 + `~/.local/share/applications` 两份）的 `Exec=` 一起改, 改前备份。
3. **非 git 运行时产物软链进代码树**（否则"代码树缺 models/runs/data" ↔ "产物树缺代码/画布"二选一）:
   `runs/ outputs/` 目录级软链 · `models/`、`data/` 逐项补软链（本次 23 + 52 项）。

**同类连锁（同源故障, 一起查）**：**systemd unit 引用的脚本**也在那棵树里 → 重启即
`FileNotFoundError`（实测 `ss-remote-tap` 重启即挂、真机只读采集链断流）。处置: 逐个 unit 重指
main worktree（含 docker `-v` 挂载路径）+ venv 软链 + 重启复核 `6/6 active`。

**收尾纪律**：改完必须"用真实入口跑一遍"（点启动器 → 查进程 cwd 是否 main worktree、实例数=1、启动日志 0 错误）,
不能只看源码 diff。
