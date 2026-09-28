# -*- coding: utf-8 -*-
"""节点执行派发 (runtime) —— 双击运行/演示播放走的都是这里; 不含任何 GUI 依赖。

搬运自 tools/gui/node_logic.py (2026-09-28), 行为逐字保留:
  · execute_node_logic(module, node, label, trace, demo) — 节点名 → 注册表 key → 真函数
  · _trace_exec  — debug 式逐行执行 (VSCode 断点优先, 否则 sys.settrace)
  · _demo_node_output — ▶运行 演示播放: 打印引擎真实算出的该节点 out
"""
import inspect
import sys
import time

from .registry import NODE_LOGIC, match_node

def _trace_exec(fn, ctx, log):
    """🐛 2026-08-30 老倪: debug 式逐行执行 — 每行显示代码 + 输入/输出变量具体数值变化
    用 sys.settrace 行追踪 (只追踪 fn 自己函数体的行), 赋值/参数变化实时输出
    🐛 2026-08-31: VSCode attach 调试时禁用 settrace — sys.settrace 会覆盖 debugpy
    的 tracer → 断点不命中; 调试器已连接时直接执行, 断点交给 VSCode"""
    try:
        import debugpy
        if debugpy.is_client_connected():
            return fn(ctx)
    except Exception:
        pass
    import sys as _sys
    src_lines = None
    try:
        src_lines = inspect.getsource(fn).splitlines()
    except (OSError, TypeError):
        pass
    base = fn.__code__.co_firstlineno
    last_locals = {}
    skip = ("module", "log", "ctx", "p", "info")

    def _fmt(v, maxlen=42):
        try:
            s = repr(v)
        except Exception:
            s = "<?>"
        return s if len(s) <= maxlen else s[:maxlen] + "…"

    def tracer(frame, event, arg):
        if event != "line":
            return tracer
        # 只追踪目标函数自身的行 (防递归进子函数/库代码刷屏)
        if frame.f_code is not fn.__code__:
            return tracer
        lineno = frame.f_lineno
        if src_lines is None or not (base <= lineno < base + len(src_lines)):
            return tracer
        line = src_lines[lineno - base].strip()
        loc = dict(frame.f_locals)
        # 变化的变量: 新增或值变 (输入→输出数值)
        changed = {k: loc[k] for k in loc
                   if k not in last_locals or last_locals[k] != loc[k]}
        show = []
        for k, v in changed.items():
            if k in skip or k.startswith("_"):
                continue
            if isinstance(v, (int, float, str, bool)) or v is None:
                show.append(f"{k}={_fmt(v)}")
            else:
                show.append(f"{k}=<{type(v).__name__}>")
        if log:
            tail = " → " + "  ".join(show) if show else ""
            log(f"  ▶ L{lineno - base + 1}: {line[:58]}{tail}")
        last_locals.update(loc)
        return tracer

    _sys.settrace(tracer)
    try:
        return fn(ctx)
    finally:
        _sys.settrace(None)


def _demo_node_output(module, node, ctx):
    """▶运行 播放演示: 读 DataWorld 当前帧该节点的 out (引擎真实算的), 打印展示。
    🐛 v3.4.8 老倪「运行后没有连续动作, 好像卡住了」: 播放每帧 execute 真跑
    📡传感器融合 → YOLO aligner 冷加载/采样 1.6s+ 冻结主线程 → 卡顿。
    演示不重跑节点函数; 数值取自 dw 帧 = 引擎该步真实输出 (同源不伪造)。"""
    name = node.get("name", "")
    log = ctx.get("log")
    # 🧩 原子技能节点 (2026-09-07 老倪: 技能层 demo 也要真实数值 — 轻量读 tr, 无副作用)
    try:
        if (match_node(name) or "").startswith("sssk"):
            return node_ss_atomic(ctx)
    except Exception:
        pass
    # 🧩 2026-09-20 老倪: ▶运行 播放到「SU(2) 统一状态空间」节点 → 真跑一次轻量群映射
    #   (demo_light=True: 不冷加载 YOLO/metaworld, 只用缓存 obs43; 群运算 ~1ms 不卡播放)
    #   根因: ▶运行 走 demo 路径(不重跑节点真实函数) → 原实现下 su2.py 根本不执行,
    #        在 su2.py 里设的断点永远不命中。
    try:
        if (ctx.get("params") or {}).get("su2_unified_state") or "SU(2)" in str(name):
            return node_ss_su2({**ctx, "demo_light": True})
    except Exception:
        pass
    # 🅰️🅱️🅾️ 通用算子 A/B/C (2026-09-10 老倪: L2 原子技能行最左侧万能节点,
    #   L4 动态参数更新接口 — 参数写入/微调/校验)
    try:
        if (ctx.get("params") or {}).get("universal_op"):
            return node_ss_abc(ctx)
    except Exception:
        pass
    # 🎯 2026-09-03 老倪: ▶运行 播放轮转到「🎯 YOLO 目标检测」时, 展示真实采样值
    #   (detect_3d 已由 _real_yolo_sense_once 真执行, conf/3D 模型真输出) — 不用
    #   引擎帧 conf -- (引擎无 YOLO 模型)。无缓存(采样失败/无节点)才落回 dw 帧。
    if match_node(name) == "ss_yolo" and _YOLO_CACHE.get("det3d"):
        try:
            d3 = _YOLO_CACHE.get("det3d") or {}
            d2 = _YOLO_CACHE.get("det2d") or {}
            parts = [f"{k}=[{v[0]:.3f},{v[1]:.3f},{v[2]:.3f}]"
                     + (f" conf={d2[k]['conf']:.2f}" if k in d2 else "")
                     for k, v in sorted(d3.items())]
            if log:
                log(f"⏩ {name} (真实YOLO采样): {len(d3)}/3 目标 · " + " · ".join(parts))
            return True
        except Exception:
            pass
    try:
        import numpy as _np
        dw = getattr(module, "_dw", None)
        if dw is not None:
            mo = dw.module_out_values(name)
            if mo:
                parts = []
                for _k, _v in list(mo.items())[:4]:
                    if isinstance(_v, _np.ndarray):
                        parts.append(f"{_k}=" + "[" + ",".join(f"{x:.3f}" for x in _np.asarray(_v).ravel()[:6]) + "]")
                    elif isinstance(_v, (float, int)):
                        parts.append(f"{_k}={_v:.4f}")
                    else:
                        parts.append(f"{_k}={_v}")
                if log:
                    log(f"⏩ {name}: " + " · ".join(parts))
                return True
        if log:
            log(f"⏩ {name}: (演示)")
        return True
    except Exception:
        return True


def execute_node_logic(module, node, label=None, trace=None, demo=False):
    """双击环节节点 → 执行节点逻辑 (用户可修改版). 未注册返回 None → 框架兜底
    trace=True → debug 式逐行执行 (每行代码 + 变量数值变化, 2026-08-30 老倪)
    demo=True → ▶运行 播放演示模式: 不重跑节点真实函数 (传感器融合/YOLO 采样等会
    冷加载 1.6s+ 卡死播放), 改读 DataWorld 当前帧该节点的引擎真实 out 展示
    (数值与引擎同源不伪造)。调试 (单步/右键运行/双击) 仍走真实执行 fn。"""
    name = node.get("name", "")
    key = match_node(name)
    if key is None:
        return None
    info = NODE_LOGIC[key]
    # 🐛 2026-08-30 老倪: VSCode 断点调试 — env ZMAX_DEBUG_BREAK (launch.json 自动配) 时
    # 执行节点逻辑先停在此处, F10 单步逐行 (debugpy.breakpoint 非调试时无害)
    # 🐛 2026-09-01: 支持子串过滤 — ZMAX_DEBUG_BREAK=metaworld 只停数据源节点,
    #   免逐节点 F5 (根因: open_in_vscode 每次右键重写 launch.json 覆盖掉 env → 断点永不触发)
    _brk = os.environ.get("ZMAX_DEBUG_BREAK")
    if _brk:
        try:
            import debugpy
            if _brk == "1" or _brk in name:
                # 🐛 2026-09-01 老倪: 暂停前打提示 — 断点命中时主线程冻结, Windows 必弹
                #   "studio.py is not responding"(正常现象); 用户看到日志知道去 VSCode F5,
                #   不会误以为卡死去点「关闭程序」(点关闭=杀进程, 断点全丢)
                try:
                    _log = getattr(module, "_log", None)
                    if _log:
                        _log(f"🔴 调试断点: 暂停「{name}」— 切到 VSCode 按 F5 继续 "
                             f"(Windows 弹 not responding 属正常, 点「等待」勿点「关闭程序」)")
                except Exception:
                    pass
                debugpy.breakpoint()
        except Exception:
            pass
    ctx = {"module": module, "params": node.get("params", {}),
           "log": getattr(module, "_log", None), "name": name, "label": label}
    # 🎯 v3.4.8: ▶运行 播放演示 = 轻量展示路径 (读 DataWorld 帧, 不重跑重函数)
    if demo:
        return _demo_node_output(module, node, ctx)
    if trace is None:
        trace = bool(getattr(module, "_trace_nodes", False))
    if trace:
        return _trace_exec(info["fn"], ctx, getattr(module, "_log", None))
    return info["fn"](ctx)
