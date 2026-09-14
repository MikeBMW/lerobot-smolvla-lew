# VcXsrv 狂闪黑条 / SIGSEGV / 显示不全 / 前馈PD特征解 (2026-08-15)

新家 = Docker Desktop 容器 + Windows VcXsrv(网络合成)。同日老倪连续报:
①启动狂闪黑条 ②崩溃 SIGSEGV ③背景字显示不全 ④数据字典没对应上 ⑤前馈PD特征解怎么得到。

## ① 启动/运行狂闪黑条 — SimLinkItem 无条件 80ms QTimer (最顽固)

**根因**: `SimLinkItem.__init__` 每条连线构造时 `self._anim_timer.start(80)` —
无条件、任何画布、任何时刻。每 80ms 全画布连线重绘一次。旧家 WSLg 本地合成快,
没暴露; 新家 VcXsrv 每帧走网络把全画布传去 Windows → 闪成黑条。

**修复 = timer 惰性化** (simulink_module.py):
```python
# __init__: 不再 start
self._anim_timer = QTimer()
self._anim_timer.timeout.connect(self._tick_flow)

def _wake_flow_anim(self):
    """外部唤醒: 真正在流动才启动动画"""
    if self._switch_active() and self.src.node.get("status") in ("success", "running"):
        if not self._anim_timer.isActive():
            self._anim_timer.start(80)
    else:
        if self._anim_timer.isActive():
            self._anim_timer.stop()
        if self._flow_offset != 0:
            self._flow_offset = 0
            self.update()

def _tick_flow(self):
    if self._switch_active() and self.src.node.get("status") in ("success", "running"):
        self._flow_offset += 2.0
        self.update()
    else:
        self._anim_timer.stop()          # 不流动立即自停, 不再空转重绘
        if self._flow_offset != 0:
            self._flow_offset = 0
            self.update()
```
唤醒点: `_wake_flow_anim_all()` 批量遍历 `self._link_items` 调 `_wake_flow_anim()`,
挂在 ①`_draw_links` 尾部(画布加载后) ②`_sim_node` 状态变化后(节点 success/running 才流)。
⚠️ patch 时曾误删 `_switch_active` 方法 — 用"方法签名+docstring"当 old_string 时
new_string 必须把涉及的所有方法签名成对保留。

## ② 崩溃 SIGSEGV — QObject::killTimer from another thread

日志尾: `QObject::killTimer: Timers cannot be stopped from another thread` +
`QObject::~QObject` 同款 → SIGSEGV (-11)。**根因**: 清画布/切画布时旧 SimLinkItem
的 QTimer 还在跑, scene.clear() 把 item 跨线程析构。

**修复**: `clear()` 清画布前先停所有连线 timer:
```python
def clear(self):
    self._clear_model_rows()
    for li in getattr(self, "_link_items", []):
        try:
            t = getattr(li, "_anim_timer", None)
            if t is not None and t.isActive():
                t.stop()
        except Exception:
            pass
    self.canvas._scene.clear()
    ...
```
排查口诀: X 端口通(`echo > /dev/tcp/host.docker.internal/6000`) ≠ 无崩溃 —
先查有没有 QTimer/QThread 跨线程析构。

## ③ row_bg 背景长名显示不全

**根因**: row_bg paint 左侧大字固定 `QRectF(8, 0, 126, h)` 126px 宽 —「前馈 PD
顶层系统」15px Bold ≈135px 被裁剪; 且只有名字含 "+" 才拆两行。

**修复** (simulink_module.py SimNodeItem.paint row_bg 分支):
```python
avail_w = 122.0
painter.setPen(QColor("#ffffff"))          # ⚠️ patch 时容易丢, 丢了字变黑
fs = 15
while fs >= 9:
    painter.setFont(QFont("Arial", fs, QFont.Bold))
    fm = painter.fontMetrics()
    if fm.horizontalAdvance(name) <= avail_w:
        break
    fs -= 1
# 仍超 → 按空格/括号拆两行, 每行再自适应
```
验证: 名字宽度 ≤122px 即不裁剪(「前馈 PD 顶层系统」→ 10px 116px 完整)。

## ④ 数据字典 list 参数跳过 (limit 没对应上)

**根因**: model_tree.py `refresh()` 里 `isinstance(v, (dict, list)): continue` —
limit=[-1,1] 等数组标定参数全部跳过, 用户看不到。

**修复**: ①显示 — list 格式化 `"[−1, 1]"` 作第二列, UserRole 仍存 (node, key);
②标定 — `_on_item_dbl` 加分支:
```python
elif isinstance(old, list):
    import re as _re
    parts = [p.strip() for p in _re.split(r"[,\s\[\]]+", val) if p.strip()]
    node["params"][key] = [float(p) for p in parts]
```

## ⑤ 前馈PD特征解 — analyze_system 数学化 (拉普拉斯复数空间)

需求: "我应该看到前馈PD系统的特征解…有拉普拉斯变换的复数空间表示么?"

原 analyze_system 把 Z700 当黑盒 1/(0.1s+1) → 二重极点 −10, 没体现 PD 参数。
**修复**: 检测 `params.z700_internal` 节点 → 构造真闭环:
- 控制器(PD): C(s) = Kp + Kd·s  (状态机=Kp=2.0 P 增益, 动作=Kd=0.3 D 增益)
- 被控对象(右脑一阶近似): G(s) = 1/(1+Ts), T=0.1
- 开环 L=C·G → 闭环 1+L=0 → **特征方程 (T+Kd)s + (1+Kp) = 0** → 0.4s+3=0
- **特征解 s = −(1+Kp)/(T+Kd) = −7.5** (唯一实极点, 左半平面稳定, 无振荡=临界阻尼)
- 时域原函数(单位阶跃): **y(t) = Kp/(1+Kp)·(1 − e^{s*·t}) = 0.667(1−e^{−7.5t})**
- 静差 e_ss = 1/(1+Kp) = 0.333 — 纯 PD 无积分项, 由前馈 K_ff 补偿
- 零点 s = −Kp/Kd = −6.67; 复平面图自动画极点×/零点○

⚠️ **取参必须按节点名过滤**:
```python
def _p(name, key, dflt):
    for n in internals:
        if name in n.get("name", "") and key in n.get("params", {}):
            return float(n["params"][key])
    return dflt
Kp = _p("状态机", "Kp", 2.0)   # 不是 next(含Kp的节点)!
```
感知链也有 Kp=1.0(观测环节 y=Cx, 非 PID 组件) — 不点名过滤会读到它 → 极点错成 −5.0。
_show_math 加 `res.get("ff_pd")` 分支输出: 特征方程/特征解/τ=1/|s*|/原函数/静差/前馈补偿。

## 验证
- 连线惰性: offscreen load ff_pd_top → 静止画布所有连线 `_anim_timer.isActive()` 全 False;
  某节点 status=success → 其出边启动; 回落 idle → tick 自停; clear() 后无残留。
- 数学: analyze_system(ff_pd_top) → poles=[-7.5] 且 `abs(poles[0] − (−(1+Kp)/(T+Kd))) < 1e-9`;
  t=τ 时 y = 63.2%·y_ss (一阶标准)。
