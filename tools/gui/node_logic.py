# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
Z-MAX 节点逻辑库 (Node Logic) — 每个节点的可编辑逻辑
══════════════════════════════════════════════════════════════════

🛠 使用规则 (重要, 请先读):
  · 本文件是「节点背后的逻辑」— 双击节点运行、右键节点查看的就是这里
  · 每个函数中间标有:
        # === ✏️ 可修改区 START ===
        ... 这一段 = 你可以随便改 (参数/日志/判断逻辑)
        # === ✏️ 可修改区 END ===
  · 可修改区之外 (函数签名 / 开头结尾) = 🔒 框架区, 不要动
    — 改了可能导致节点无法运行, 保存时会警告
  · 保存后立即生效 (热重载, 无需重启控制台)
  · 「恢复默认」= 回到出厂模板

📖 节点 = 函数 对照:
  · 环节节点 (双击运行): 采集 / 训练 / 验证 / 集成 / 部署 / 推理
  · 结构节点 (右键查看): 📦metaworld数据 / ResNet18 / CVAE / Encoder / Decoder / ActionHead / Ensemble
══════════════════════════════════════════════════════════════════
"""
import importlib
import inspect
import os
import time

_LOGIC_FILE = os.path.abspath(__file__)

# ── 🔒 框架区: 注册表 (勿改) ──────────────────────────────────────
NODE_LOGIC = {}   # 语义key → {match:[关键字], fn, doc}
NODE_ORDER = []   # 注册顺序 (UI 列表展示)
_SOURCE_CACHE = {}  # key → 用户修改后的源码 (get_node_source 优先取)


def _reg(key, matches, doc, fn):
    NODE_LOGIC[key] = {"match": matches, "fn": fn, "doc": doc}
    NODE_ORDER.append(key)


def match_node(name):
    """节点名 → 语义key (最长关键字匹配, 避免「训练」抢先匹配「全新训练」)"""
    best, best_key = 0, None
    for key, info in NODE_LOGIC.items():
        for m in info["match"]:
            if m in name and len(m) > best:
                best, best_key = len(m), key
    return best_key


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


def get_node_source(key):
    """语义key → 函数源码 (供编辑器展示)"""
    info = NODE_LOGIC.get(key)
    if not info:
        return None, None
    if key in _SOURCE_CACHE:
        return _SOURCE_CACHE[key], info["doc"]
    try:
        src = inspect.getsource(info["fn"])
    except (OSError, TypeError):
        src = None
    return src, info["doc"]


def get_node_location(key):
    """语义key → 代码位置 (path, line, modified) 供 VSCode 打开.

    path: 绝对路径 (原始=node_logic.py; 用户修改过=仍在 node_logic.py, 但逻辑是动态加载)
    line: 函数定义行号 (修改版为 None, 动态 exec 无行号)
    modified: True=用户改过(动态生效, 未落盘)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return None, None, False
    # 📂 外部源码映射优先 (left_right 等真实实现不在 node_logic.py, 2026-08-10)
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    if ext:
        line = ext[1]
        # 🐛 2026-09-04 静静: 手写行号随源码改动漂移 (parallel.py 重写后 class
        #   FeedforwardAccelerator 21→71, 右键跳到 import 区=看起来"没跳") →
        #   有符号名时按文件现搜, 动态定位一劳永逸; 搜不到回退手写行号。
        if len(ext) > 2 and ext[2]:
            try:
                _sym = ext[2]
                with open(ext[0], encoding="utf-8", errors="ignore") as _f:
                    for _i, _ln in enumerate(_f, 1):
                        if _ln.lstrip().startswith(_sym):
                            line = _i
                            break
            except Exception:
                pass
        return ext[0], line, False
    fn = info["fn"]
    modified = key in _SOURCE_CACHE
    path = getattr(fn.__code__, "co_filename", None)
    line = getattr(fn.__code__, "co_firstlineno", None)
    if not path or not path.endswith(".py"):
        path = _LOGIC_FILE
        line = None
    return path, line, modified


def get_node_external_symbol(key):
    """外部源码映射的真实符号名 (VSCode 定位显示用) — 无映射返回 None"""
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    return ext[2] if ext else None


def _probe_data_root():
    """🆕 2026-08-30 老倪: 探测本机训练数据仓库 — 返回 '路径 · 帧数/集数 · 特征' 或 None
    优先级与 _ensure_training_data 一致: Orin真实(closed_loop) → metaworld_peg_long → metaworld_peg → ss_insert_lerobot"""
    import json as _j, os as _os
    root = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".."))
    for cand in ("data/closed_loop", "data/metaworld_peg_long", "data/metaworld_peg",
                 "data/ss_insert_lerobot"):
        d = _os.path.join(root, cand)
        ij = _os.path.join(d, "meta", "info.json")
        if not _os.path.isfile(ij):
            ij = _os.path.join(d, "info.json")
        if not _os.path.isfile(ij):
            continue
        try:
            info = _j.load(open(ij, encoding="utf-8"))
            nf = info.get("total_frames", "?")
            ne = info.get("total_episodes", "?")
            feats = list(info.get("features", {}).keys())
            fstr = ",".join(str(f).replace("observation.", "") for f in feats[:3])
            src = "Orin真实" if cand == "data/closed_loop" else ("状态空间" if "ss" in cand else "metaworld占位")
            return f"{cand} · {nf}帧/{ne}集 · {src} · 特征[{fstr}]"
        except Exception:
            continue
    return None


def explain_node(name, module=None, out=None):
    """🧩 代码讲解 (2026-08-30 老倪): 运行节点时终端输出 — 从代码角度解释
    语法/功能/赋值 (可修改区逐行 + 行尾注释), 从全局目标/数据空间角度
    统一描述数据变化趋势 (画布拓扑位置 + 上下游 + 本步输出).
    返回多行文本; 未注册逻辑返回 None."""
    key = match_node(name)
    if not key:
        return None
    info = NODE_LOGIC.get(key, {})
    fn = info.get("fn")
    doc = info.get("doc", "")
    L = [f"🧩 代码讲解 · {name}"]
    if doc:
        L.append(f"  功能: {doc}")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        src = ""
    in_mod = False
    syn_n = 0
    MAX_SYN = 6   # 🆕 2026-08-30: 语法行上限 (train 等复杂节点不刷屏), 超了提示看编辑器
    for raw in src.splitlines():
        line = raw.strip()
        if "可修改区 START" in line:
            in_mod = True
            continue
        if "可修改区 END" in line:
            in_mod = False
            continue
        if not line or line.startswith(("def ", '"""', "# ═", "# ─", "# ===")):
            continue
        if line.startswith("#"):
            continue
        if line.startswith("return"):
            L.append(f"  框架: {line}   ← 调度/激活动作 (框架区勿改)")
        elif in_mod:
            if syn_n < MAX_SYN:
                L.append(f"  语法: {line}")
                syn_n += 1
            elif syn_n == MAX_SYN:
                L.append(f"  …(共 {sum(1 for r2 in src.splitlines() if r2.strip() and not r2.strip().startswith(('#', 'def ', 'return')))} 行, 其余省略 — 右键「查看/编辑节点逻辑」看全量)")
                syn_n += 1
    # 全局定位 + 数据空间 (画布上下文)
    if module is not None:
        try:
            nodes = getattr(module, "nodes", []) or []
            n = next((x for x in nodes if x.get("name") == name), None)
            if n is not None:
                total = len(nodes)
                idx = next((i for i, x in enumerate(nodes) if x.get("name") == name), -1) + 1
                up, dn = [], []
                for lk in getattr(module, "links", []) or []:
                    if lk.get("t") == n["id"]:
                        s = next((x for x in nodes if x.get("id") == lk.get("f")), None)
                        if s:
                            up.append(str(s["name"]).lstrip("📦🎯🔌🖐🧠🔮🧪"))
                    if lk.get("f") == n["id"]:
                        d = next((x for x in nodes if x.get("id") == lk.get("t")), None)
                        if d:
                            dn.append(str(d["name"]).lstrip("📦🎯🔌🖐🧠🔮🧪"))
                pos = f"画布 {idx}/{total} 节点"
                if up:
                    pos += f" · 上游 ← {' / '.join(up[:3])}"
                if dn:
                    pos += f" · 下游 → {' / '.join(dn[:3])}"
                L.append(f"  全局: {pos}")
                p = n.get("params", {})
                dims = p.get("dims") or p.get("desc", "")
                if dims:
                    L.append(f"  数据: 空间 {dims}")
                # 🆕 2026-08-30 老倪: 数据源真实路径 + dataset/dataloader 机制 + 形象比喻
                if key in ("data",) or (p.get("source") and not p.get("run_env")):
                    pl = _probe_data_root()
                    if pl:
                        L.append(f"  仓库: {pl}")
                    L.append("  比喻: 📦 数据源 = 原料仓库 — 训练前把仓库里的帧整理成数据集"
                             "(dataset 分拣台: 逐帧读取 + 算归一化 mean/std), "
                             "再由 dataloader(传送带) 按 batch 送进训练")
                elif key == "train":
                    L.append("  数据链: 仓库 data/ → LeRobotDataset(分拣台: 按帧读取 + "
                             "归一化统计) → DataLoader(传送带: 每步喂 batch 个样本) → "
                             "模型参数更新 → checkpoint(成品 outputs/train/)")
                    L.append("  比喻: 🚀 训练 = 流水线 — 原料(帧)经分拣台(dataset)上"
                             "传送带(dataloader)进机床(模型反向传播), 产出成品(checkpoint)")
                if out is not None:
                    L.append(f"  趋势: 本步输出「{out}」→ 沿链路向下游传递")
        except Exception:
            pass
    return "\n".join(L)


def get_external_source(key):
    """外部真实实现的源码块 (按符号截取, 只读参考) — left_right 等节点
    显示 modeling_left_right.py 的 class LeftBrainMLP 全文, 不是 node_logic 占位函数"""
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    if not ext:
        return None
    path, line, sym = ext
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return None
    # 🐛 2026-08-12 老倪: 用符号名定位 (sym="class RightBrainWM") — 映射行号错位时
    # 源码截取从空行开始 → 面板只显示"源码结束"标记 → 改用名称搜索, 行号仅兜底
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        # 🐛 2026-08-18: 支持类定义冒号 (class X:) — 原来只匹配 sym/sym(, 类名带冒号
        # 匹配不上 → 回退行号定位 → 重写后的类行号偏移 → 截错位置 (源码显示几行)
        if s == sym or s.startswith(sym + "(") or s.startswith(sym + ":"):
            start = i
            break
    if start is None:
        start = max(0, line - 1)
    out = []
    for i in range(start, len(lines)):
        ln = lines[i]
        if out and (ln.startswith("class ") or ln.startswith("def ") or ln.startswith("@")):
            break  # 下一个顶层定义
        out.append(ln)
        # 符号体结束: 空行后出现顶格非空行 (缩进归零, 非注释/docstring)
        if i > start and not ln.strip() and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt and not nxt[0].isspace() and not nxt.startswith(("#", '"""', "'''", "from ", "import ")):
                break
    if not out:
        return None
    return "\n".join(out) + f"\n\n# ── {sym} 源码结束 (文件 {os.path.basename(path)}:{start + 1}) ──"


def save_node_logic(key, new_code):
    """保存用户修改 → exec 原地替换函数 (即时生效, 无需重启/热重载).

    返回 (ok, msg, warn列表)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return False, f"未知节点逻辑: {key}", []
    try:
        # 语法检查
        compile(new_code, f"<node:{key}>", "exec")
    except SyntaxError as ex:
        return False, f"❌ 语法错误 (第{ex.lineno}行): {ex.msg}", []
    fn_name = info["fn"].__name__
    ns = {}
    try:
        exec(compile(new_code, f"<node:{key}>", "exec"), globals(), ns)
    except Exception as ex:
        return False, f"❌ 代码执行失败: {ex}", []
    new_fn = ns.get(fn_name)
    if new_fn is None:
        return False, f"❌ 新代码里找不到函数定义 def {fn_name}(...)", []
    # 原地替换: 注册表指向新函数 + 缓存源码 (simulink 侧同模块对象, 立即生效)
    NODE_LOGIC[key]["fn"] = new_fn
    _SOURCE_CACHE[key] = new_code
    return True, f"✅ 已保存并生效 ({fn_name})", []


def restore_default(key):
    """恢复出厂逻辑: 从文件重新 exec 取原始函数 (真实文件行号 + 清修改缓存).

    返回 (ok, msg)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return False, f"未知节点逻辑: {key}"
    fn_name = info["fn"].__name__
    try:
        with open(_LOGIC_FILE, encoding="utf-8") as f:
            code = f.read()
        ns = {"__file__": _LOGIC_FILE, "__name__": __name__}
        # filename=真实路径 → exec 出的函数 co_filename/co_firstlineno 指向文件真实位置
        exec(compile(code, _LOGIC_FILE, "exec"), ns)
        orig_fn = ns.get(fn_name)
        if orig_fn is None:
            return False, f"❌ 文件中找不到 def {fn_name}"
        NODE_LOGIC[key]["fn"] = orig_fn
        _SOURCE_CACHE.pop(key, None)   # 清修改标记
        return True, f"✅ 已恢复出厂逻辑 ({fn_name})"
    except Exception as ex:
        return False, f"❌ 恢复失败: {ex}"


def reload_node_logic():
    """热重载本模块 (保存后调用, 新逻辑立即生效)"""
    return importlib.reload(__import__(__name__))


def list_logic():
    """所有节点逻辑一览: [(key, match, doc)]"""
    return [(k, v["match"], v["doc"]) for k, v in NODE_LOGIC.items()]


# ════════════════════════════════════════════════════════════════
# ① 采集 — 拉取 Orin 真实数据 (relay → 修复 action → 落地)
# ════════════════════════════════════════════════════════════════
def node_collect(ctx):
    """① 采集 — Orin 真实数据拉取"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    endpoint = "https://datadrive.world/api/relay"   # 数据中转端点 (ECS nginx 反代)
    fix_action = True          # action 恒等修复开关 (True=标准, False=保留原始 action)
    timeout = 8                # 网络超时秒数
    if log:
        log(f"📡 采集配置: {endpoint} · 修复action={fix_action} · 超时{timeout}s")
    # 想加自己的处理逻辑? 在这里写 (例如: 只收 n_joint==6 的包、记录来源统计)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实拉取 relay → 落地 (勿改)
    return module.on_collect(timeout=timeout, fix_action=fix_action, endpoint=endpoint)


# ════════════════════════════════════════════════════════════════
# ② 训练 — ACT 策略训练 (lerobot_train)
#   同时服务「🚀 全新训练」节点 (metaworld 全新训练) 与「② 训练」环节
# ════════════════════════════════════════════════════════════════
def node_train(ctx):
    """② 训练 — ACT/SmolVLA 策略训练 (参数在可修改区, 真实写入训练配置)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    steps = p.get("steps", 1000)     # 训练步数 (2026-08-06 正式对比 500 步) (4060 实测 ACT ~13步/s, 300步≈40s; SmolVLA 更慢)
    batch_size = 8                   # batch size (SmolVLA 显存小可改 1)
    lr = 1e-4                        # 学习率 (S3 真机微调用 1e-5)
    data_source = "auto"             # auto(画布switch决定) | orin(只拉真实) | metaworld(占位集)
    policy = p.get("policy", "act")  # act | smolvla_lew (⚔️ 对比模板两训练节点各设一种, 节点params指定)
    if log:
        log(f"🧠 训练配置: steps={steps} · batch={batch_size} · lr={lr} · 数据源={data_source} · policy={policy}")
    # 2026-08-06 老倪: 蒸馏 MLP / 官方专家 入画布
    if policy == "expert_mlp":
        import subprocess, sys as _sys, re as _re, json as _json
        log("🎓 专家蒸馏训练: 300 episodes 官方专家数据 → BC 蒸馏 MLP")
        repo = _REPO_ROOT  # 仓库根 (frozen/env/探测统一, 勿用 dirname×2 — 那指向 tools/)
        r = subprocess.run([_sys.executable, os.path.join(repo, "tools", "distill_expert.py")], capture_output=True, text=True, cwd=repo)
        tail = (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-100:])
        log(f"  {tail}")
        # 📈 落曲线 (2026-08-07): epoch loss → Scope 对比图表可见 MLP 蒸馏进度
        try:
            pts = [(int(m[0]), float(m[1])) for m in _re.findall(r"epoch (\d+): loss=([\d.eE+-]+)", r.stdout)]
            os.makedirs(os.path.join(repo, "reports"), exist_ok=True)
            with open(os.path.join(repo, "reports", "train_curve_expert_mlp.json"), "w", encoding="utf-8") as f:
                _json.dump({"policy": "expert_mlp", "name": "MLP 蒸馏", "ts": time.strftime("%Y%m%d_%H%M%S"),
                            "curve": pts, "step_s": 0, "ckpt": "outputs/rl_peg/expert_mlp.pt",
                            "success": "抓起18/20 插入11/20 (55%)"}, f, ensure_ascii=False)
            log(f"📈 MLP 蒸馏曲线已存: reports/train_curve_expert_mlp.json ({len(pts)} epochs)")
        except Exception:
            pass
        return {"ok": True, "policy": "expert_mlp", "ckpt": "outputs/rl_peg/expert_mlp.pt"}
    if policy == "expert_policy":
        log("📏 官方专家基准: 非训练 (metaworld 内置规则策略), 成功率 19/20 抓起 17/20 插入 (85%)")
        # 📈 落基准数据 (2026-08-07): 让 Scope 对比图表把专家作为真值锚点显示
        try:
            import json as _json
            repo = _REPO_ROOT
            os.makedirs(os.path.join(repo, "reports"), exist_ok=True)
            with open(os.path.join(repo, "reports", "train_curve_expert_policy.json"), "w", encoding="utf-8") as f:
                _json.dump({"policy": "expert_policy", "name": "官方专家", "ts": time.strftime("%Y%m%d_%H%M%S"),
                            "curve": [], "step_s": 0, "ckpt": "", "success": "85% (19/20抓起 17/20插入)"}, f, ensure_ascii=False)
        except Exception:
            pass
        return {"ok": True, "policy": "expert_policy", "success": "85%"}
    # 想改训练逻辑? 在这里写 (例如: 按数据帧数自动调整 steps)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实 lerobot_train (数据源智能选择, 勿改)
    return module.on_train(steps=steps, batch_size=batch_size, lr=lr, data_source=data_source, policy=policy)


# ════════════════════════════════════════════════════════════════
# ③ 验证 — Simulink 模型验证 (validate_flow --strict)
# ════════════════════════════════════════════════════════════════
def node_validate(ctx):
    """③ 验证 — 流程拓扑合规检查"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    strict = True     # True=严格模式 (全部 8 项检查) / False=只查格式与连线
    if log:
        log(f"🛡 验证配置: strict={strict}")
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实 validate_flow (勿改)
    return module.on_validate(strict=strict)


# ════════════════════════════════════════════════════════════════
# ④ 集成 — checkpoint 打包 → 上传 ECS 中转
# ════════════════════════════════════════════════════════════════
def node_integrate(ctx):
    """④ 集成 — 打包最新 checkpoint → 上传 ECS"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("📦 集成: 打包最新 checkpoint → 上传 ECS 中转 (cicd_deploy.py push)")
    # 自定义前置检查 (真执行): 例如要求训练产物存在才允许集成
    # import os
    # if not os.path.exists(os.path.expanduser("~/lerobot-smolvla-lew/outputs/train")):
    #     return False, "没有训练产物, 无法集成"
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: cicd_deploy.py push (勿改)
    return module.on_integrate()


# ════════════════════════════════════════════════════════════════
# ⑤ 部署 — ECS 部署状态 / 推送到产线
# ════════════════════════════════════════════════════════════════
def node_deploy(ctx):
    """⑤ 部署 — 部署状态检查与推送"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("🚚 部署: 检查 ECS 部署状态 (cicd_deploy.py status)")
    # 自定义部署前检查 (真执行): 例如要求 Orin 心跳在线才报告成功
    # import requests
    # try:
    #     o = requests.get("https://datadrive.world/api/relay/orin/status", timeout=5).json()
    #     if not o.get("online"):
    #         return False, "Orin 离线, 部署无意义"
    # except Exception as ex:
    #     return False, f"Orin 状态查询失败: {ex}"
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: cicd_deploy.py status (勿改)
    return module.on_deploy()


# ════════════════════════════════════════════════════════════════
# ⑥ 推理 — Orin 推理服务状态
# ════════════════════════════════════════════════════════════════
def node_mode_switch(ctx):
    """🔀 训练/推理模式开关 — 双击切换 train ⇄ infer, 激活路径金色高亮, 未激活灰显
    数据流: 📦数据源 → 🔀开关 → 🚀训练 | 📷推理(rollout)
    train → 训练节点激活(推理灰显); infer → 推理节点激活(训练灰显)
    真实实现: simulink_module.py _toggle_mode / _apply_mode_highlight / paint(mode_active 灰显)"""
    log = ctx["log"]
    node = ctx.get("node", {})
    p = node.get("params", {})
    mode = p.get("mode", "train")
    log(f"🔀 模式开关: 当前={'训练' if mode == 'train' else '推理'} (双击切换, 激活路径高亮)")
    return True


def node_infer_rollout(ctx):
    """📷 推理 (rollout) — 加载最新双脑 checkpoint → 仿真插拔 rollout → 评估+视频
    后台 worker: gen_insert_video.py (最新模型按 mtime 排序, 归一化从 preprocessor 读)
    输出: reports/insert_success_demo.mp4 → 自动发飞书 dataworld 群
    真实实现: simulink_module.py on_infer_rollout (_start_worker) + tools/gen_insert_video.py"""
    log = ctx["log"]
    node = ctx.get("node", {})
    p = node.get("params", {})
    log(f"📷 推理 rollout: policy={p.get('policy', 'left_right')} frames={p.get('frames', 60)} → 评估插拔成功率+视频")
    return True


def node_eval_state_space(ctx):
    """📊 模型评估 (状态空间) — Z700 双脑稳定性评估 (2026-08-12 老倪)
    指标: ①L2增益(左脑Lipschitz) ②BIBO(有界输入有界输出) ③自回归谱半径ρ(右脑预测误差)
    ④状态机覆盖(8阶段可达+成功率) ⑤李雅普诺夫势能 ⑥谱范数 ⑦潜空间频谱 ⑧接触分离 ⑨动作平滑度
    状态空间: X=[X_obs(43D), X_latent(潜), X_sm(8阶段状态机)]
    真实实现: tools/eval_state_space.py → reports/eval_state_space.json + 飞书"""
    log = ctx["log"]
    node = ctx.get("node", {})
    log("📊 状态空间评估: L2增益 → BIBO → 自回归ρ → 状态机覆盖 → 稳定性结论")
    return True


def node_spectral_norm(ctx):
    """🧮 谱归一化分析 — 左脑 MLP 逐层谱范数 σ_max + Lipschitz 上界 (2026-08-12 老倪)
    原理: ||f(x1)-f(x2)|| ≤ L·||x1-x2||, L = Πσ_max(W_i) (ReLU 导数 0/1 不放大)
    数据来自: 左脑权重 SVD (eval_state_space.py spectral_norm_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 谱归一化: 左脑逐层 σ_max → Lipschitz 上界 (双击已触发 Z 分析)")
    return True


def node_gru_gate(ctx):
    """🧮 GRU 门控机制 — 右脑潜空间门控收缩分析 (2026-08-12 老倪)
    原理: 重置门 r=σ(W_hr·h) · 更新门 z=σ(W_hz·h); ρ(W_hz)<1 → 潜状态指数收敛防爆炸
    数据来自: 右脑 GRU 权重谱半径 (eval_state_space.py gru_gate_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 GRU 门控: 右脑潜空间 ρ(W) 收缩分析 (双击已触发 Z 分析)")
    return True


def node_force_limit(ctx):
    """🧮 力幅值限幅 — 插入阶段动作饱和 → 临界阻尼估计 (2026-08-12 老倪)
    原理: 二阶系统 Mẍ+Bẋ+Kx=0, 阻尼比 ζ=B/(2√MK); 限幅 [-0.6,0.6] = 非线性阻尼 → ζ→1
    数据来自: rollout 动作差分 (eval_state_space.py force_limit_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 力幅值限幅: 插入阶段饱和 → 临界阻尼 ζ 估计 (双击已触发 Z 分析)")
    return True


def node_eval_report_pdf(ctx):
    """📄 稳定性评估 PDF — 汇总报告节点 (2026-08-14 老倪)
    内容: 摘要结论 + 状态空间建模(公式) + 三工程图详释 + 九指标表 + 三模块公式 + 调优建议
    数据: reports/eval_state_space.json + 三张 png → gen_report_state_space.py → PDF → 飞书"""
    log = ctx["log"]
    log("📄 稳定性评估 PDF: 九指标+三模块+三图详释 → 汇总报告 → 飞书")
    return True


def node_ff_pd_control(ctx):
    """⚙️ 前馈 PD 控制器 — 顶层控制模型 (2026-08-14 老倪)
    思想: 系统 = 带前馈的增益调度 PID
      状态机 = 强力 P (e×Kp: delta=光模块−hand, act+=delta*2.0)
      物理限幅 = 隐性 D 与饱和 (死区/限幅=非线性阻尼, 放弃 I 避免积分饱和)
      左脑 MLP = 前馈控制器 (直接预测动作, 偏差产生前给力)
      右脑 WM = 预测器 (预判接触提前减速)
    层级: ⚙️前馈PD=顶层控制模型, Z700双脑+状态机=底层执行模型
    数据: LeftRightPolicy 动作 → PD 分析 → 模型评估汇总 (ff_pd_analysis.py)
    双击 → 前馈 vs 纯 PD 对比仿真 + 图 + 飞书"""
    log = ctx["log"]
    log("⚙️ 前馈 PD: 增益调度 P + 隐性 D + 前馈预测 → 对比仿真 (顶层控制模型)")
    return True


def node_ff_ref_input(ctx):
    """📡 参考输入 u(t) — 前馈 PD 顶层系统输入 (2026-08-14 老倪)
    增益调度各阶段的期望: 目标位置/力参考, 误差 e(t) = 参考 − 实际"""
    log = ctx["log"]
    log("📡 参考输入 u(t): 目标位置/力参考 → 误差 e(t) 驱动增益调度 P 控制")
    return True


def node_ff_scope(ctx):
    """🖥 输出 Scope — 前馈 PD 顶层系统输出 (2026-08-14 老倪)
    y(t): 完成状态/误差曲线 (等效 PD 响应), 反映 Z700 子系统对参考输入的跟踪"""
    log = ctx["log"]
    log("🖥 输出 Scope: y(t) = Z700 子系统对参考输入的响应 (误差/完成状态)")
    return True


def node_z700_internal(ctx):
    """🔬 Z700 内部模块 (顶层只读展示) — 2026-08-14 老倪
    前馈PD顶层视角: 感知→双脑→接近→抓取→抬起→转移→插入→完成 模块链 (输入输出可见)
    双击 → 提示进入上方「🔬 Z700 子系统」完整画布 (训练/评估/交付全功能)"""
    log = ctx["log"]
    log("🔬 Z700 内部模块 (只读): 感知→双脑→状态机链 — 完整功能请双击上方 Z700 子系统块")
    return True


def node_neural_kalman(ctx):
    """🔮 右脑 · 非线性卡尔曼滤波器 — 世界模型 (2026-08-16 老倪: 脑科学映射)
    卡尔曼滤波两件事 = GRU 黑盒版:
      预测 Predict: 状态转移 A ≈ GRU 循环权重 W_hh (记住"世界怎么演")
                   + 控制输入 B ≈ action 输入 (动作如何改变状态)
      更新 Update: 卡尔曼增益 K ≈ GRU 更新门/重置门 (自动调节相信预测 vs 相信观测)
    先验注入: ctx_proj (VLM 高层语义) 初始化 h0 ≈ 带先验的卡尔曼迭代
    输出: out1=状态预测, out2=contact 概率 (预测误差 → 状态机触发减速/重试)
    双击 → 标定 A/K (预测强度 / 更新增益)"""
    log = ctx["log"]
    log("🔮 右脑·非线性卡尔曼: 预测(A≈循环权重) + 更新(K≈门控) → 状态估计+contact 概率")
    return True


def node_neural_cerebellum(ctx):
    """🧠 左脑 · 小脑 (前馈逆动力学) — 2026-08-16 老倪: 脑科学映射
    小脑 = 前馈控制 (Feedforward) + 感觉-运动映射: 不依赖漫长反馈回路,
    根据当前状态直接算"该用什么力" → 毫秒级无意识纠偏
    左脑 MLP = 学习过的逆动力学模型: obs → action 直接映射, 无递归无延迟
    双击 → 标定 K_ff (前馈增益; 幅度要小, 0.5 会与 P 项冲突, 0.2 最佳)"""
    log = ctx["log"]
    log("🧠 左脑·小脑: 前馈逆动力学 obs→action 直接给力 (无递归无延迟, 熟练工直觉)")
    return True


def node_neural_cortex(ctx):
    """🧭 皮层 · 状态机 (认知决策) — 2026-08-16 老倪: 脑科学映射
    前额叶 = 规划与决策: 卡尔曼只估计"世界在什么状态", 不决定"该做什么"
    状态机根据右脑 contact 概率 + 几何误差 → 决定阶段切换 (接近→抓取→…→完成)
    认知层: 判断当前任务是否完成 → 改变控制策略
    双击 → 标定 contact_th (接触判定阈值) / Kp (阶段 P 增益) / thresh (几何误差阈值)"""
    log = ctx["log"]
    log("🧭 皮层·状态机: contact 概率 + 几何误差 → 阶段切换决策 (认知层)")
    return True


def node_neural_alpha(ctx):
    """⚖️ α 融合层 (置信度旋钮) — 2026-08-16 老倪: 右脑世界模型的可调节性
    经典卡尔曼增益 K 无法直接改 GRU 的 A 矩阵 → 在预测/观测之间外挂残差加权器:
      fused = (1−α)·pred + α·meas       α ∈ [0,1] = 等效卡尔曼增益
      α=0 完全信任世界模型 (传感器噪声大/瞬态干扰)
      α=1 完全信任传感器 (信号平滑准确)
    增益调度表 α(Stage): 接近 0.3 (靠模型快速驱动) / 插入 0.9 (绝对依赖实时反馈)
    双击 → 标定 α (默认/接近/插入阶段增益)"""
    log = ctx["log"]
    log("⚖️ α 融合层: fused = (1−α)·预测 + α·观测 — α≈卡尔曼增益旋钮 (0=纯模型 1=纯传感器)")
    return True


def node_neural_calib(ctx):
    """🔧 左脑标定实验 — 2026-08-16 老倪: 左脑标定靠数据不靠权重
    工程标定三旋钮 (tools/cerebellum_calib.py):
      ① 感知零偏标定: 静止记录 obs → 新 x_mean (校准零点, 光模块换位不重训)
      ② 执行力标定: act=act*act_gain+clip(delta*err_gain) — act_gain=肌肉记忆占比 err_gain=误差纠正力度
      ③ 现场微调: 采集 20-30 条示教 → 4090 微调 5 分钟 → 热加载 .pt (小脑急性手术)
    双击 → 跑三件套标定 + gate 仿真图 (reports/cerebellum_calib.json + cerebellum_gate.png)"""
    log = ctx["log"]
    log("🔧 左脑标定实验: ①感知零偏x_mean ②执行力act_gain/err_gain ③现场微调 → 数据标定不碰权重")
    return True


def node_neural_climbing(ctx):
    """🧬 攀缘纤维 · 误差警戒 — 2026-08-16 老倪: 生物标定机制
    小脑标定 = 配平误差, 不是死记硬背:
      平行纤维(上下文) = 左脑 MLP 输出 (携带"我猜应该这么做"的预设动作)
      攀缘纤维(误差信号) = 力传感器实测 vs 右脑 contact 预测 → 大误差 = 复杂脉冲
    当力传感器显示 5N 而右脑预测 0.5N → 误差 = 复杂脉冲 → 触发 gate 抑制 (LTD)
    双击 → 标定 gate_th (误差阈值N) / gate_min (最大抑制)"""
    log = ctx["log"]
    log("🧬 攀缘纤维: 力传感器 vs 右脑预测 → 大误差=复杂脉冲 → 触发 LTD gate 抑制")
    return True


def node_neural_ltd(ctx):
    """🛡 gate · 突触抑制 (LTD) — 2026-08-16 老倪: 生物标定机制
    长时程抑制: 左脑预测不准时, 不改 MLP 权重, 瞬间降 gate 压制左脑输出:
      gate 1.0 → 0.1 → 0.01 (完全移交物理传感器)
    标定完成(恢复期): 接触安全位置 → 状态机切阶段 → gate 恢复 1.0 → 左脑继续主导
    工程类比: 小脑物理锁定错误动作, 强行走完正确后半程
    双击 → 标定 gate (全开) / gate_off (压制) / gate_off2 (完全移交)"""
    log = ctx["log"]
    log("🛡 gate·LTD: 左脑不准 → gate 1.0→0.1 压制 MLP, 控制权移交传感器; 恢复期 gate 复原")
    return True


def node_infer(ctx):
    """⑥ 推理 — 产线推理服务状态查询"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("⚡ 推理: 查询 Orin 推理服务状态 (infer_count/延迟/心跳)")
    # 自定义推理检查 (真执行): 例如要求推理次数 > 0
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: Orin 状态查询 (勿改)
    return module.on_infer()


# ════════════════════════════════════════════════════════════════
# 📦 metaworld 数据 — 训练数据源 (hardware 节点)
#   双击=切换激活; 右键=查看/修改数据选择逻辑
# ════════════════════════════════════════════════════════════════
def node_metaworld_data(ctx):
    """📦 metaworld 数据 — 训练数据源选择"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    source = p.get("source", "metaworld")   # metaworld(占位集) | orin(真实产线)
    frames = p.get("frames", 696)           # 期望帧数 (展示用)
    # 📂 真实数据层 (2026-09-02 老倪: 数据源必须接 lerobot 框架 src/lerobot/datasets/,
    #   不是控制台模板 — 与传感器融合/前馈节点同构: 右键打开 + VSCode 断点都进 datasets 真实实现)
    # 🐛 2026-09-02: 改用 exec(compile(src, 真实路径, "exec")) 加载 — spec_from_file_location
    #   动态加载的模块 debugpy 不感知 (断点设置时文件未加载 → 绑定不生效, 实测 probe 执行了
    #   但 62 行断点不命中); compile 带真实 filename → 函数 co_filename 指向真实文件,
    #   debugpy 按路径查表必定命中 (同引擎 perception/cognition 断点行为)
    try:
        _p = os.path.join(_REPO_ROOT, "src", "lerobot", "datasets", "metaworld_data_source.py")
        _ns = {"__file__": _p, "__name__": "lerobot.datasets.metaworld_data_source"}
        with open(_p, encoding="utf-8") as _f:
            _src = _f.read()
        exec(compile(_src, _p, "exec"), _ns)
        _probe = _ns.get("probe_data_source")
        if _probe is None:
            raise RuntimeError("数据层缺少 probe_data_source")
        _info = _probe()
        if log:
            if _info:
                log(f"📦 数据源: {source} · 真实仓库 {_info['path']} · "
                    f"{_info['frames']}帧/{_info['episodes']}集 · {_info['label']} · "
                    f"特征[{','.join(_info['features'])}]")
            else:
                log(f"📦 数据源: {source} · 本机无训练仓库 (仅画布占位) · 期望 {frames}帧")
    except Exception as _e:
        if log:
            log(f"📦 数据源: {source} · 数据层探测失败: {_e}")
    # 数据源策略: 想强制某来源训练, 在「训练」节点的 data_source 里改
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 激活数据源 (勿改)
    return module._toggle_source_ctx(ctx["name"])


# ════════════════════════════════════════════════════════════════
# 🖼 视觉主干 ResNet18 — 官方 ACT.backbone (特征提取)
# ════════════════════════════════════════════════════════════════
def node_resnet18(ctx):
    """🖼 视觉主干 ResNet18 — ACT.backbone → layer4 特征图 (B,C,H,W)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "resnet18")   # 主干网络
    pretrained = p.get("pretrained", True)     # 是否用 ImageNet 预训练权重
    if log:
        log(f"🖼 ResNet18: backbone={backbone} · pretrained={pretrained}")
    # 官方源码: self.backbone = ResNet18(pretrained) → 输出 512 通道特征图
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"ResNet18 配置: {backbone} pretrained={pretrained}")


# ════════════════════════════════════════════════════════════════
# 🧬 VAE 编码器 CVAE — 官方 ACT.vae_encoder (潜变量分布 μ,logσ²)
# ════════════════════════════════════════════════════════════════
def node_cvae(ctx):
    """🧬 VAE 编码器 CVAE — 动作条件变分自编码器"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    use_vae = p.get("use_vae", False)       # 是否启用 VAE (False=确定性策略)
    latent_dim = p.get("latent_dim", 32)   # 潜变量维度 (官方默认 32)
    if log:
        log(f"🧬 CVAE: use_vae={use_vae} · latent_dim={latent_dim}")
    # 官方源码: self.vae_encoder = CVAE(latent_dim=32)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"CVAE 配置: latent_dim={latent_dim}")


# ════════════════════════════════════════════════════════════════
# 🔤 Transformer Encoder — 官方 ACT.encoder (状态+视觉特征融合)
# ════════════════════════════════════════════════════════════════
def node_encoder(ctx):
    """🔤 Transformer Encoder — 视觉特征 + 状态 → 上下文向量"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    dim_model = p.get("dim_model", 512)    # 模型宽度 (官方默认 512)
    n_heads = p.get("n_heads", 8)          # 注意力头数
    if log:
        log(f"🔤 Encoder: dim_model={dim_model} · n_heads={n_heads}")
    # 官方源码: ACT.encoder = nn.TransformerEncoder(...) 6 层
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"Encoder 配置: dim={dim_model} heads={n_heads}")


# ════════════════════════════════════════════════════════════════
# 🔡 Transformer Decoder — 官方 ACT.decoder (动作序列生成)
# ════════════════════════════════════════════════════════════════
def node_decoder(ctx):
    """🔡 Transformer Decoder — 自回归生成动作 chunk"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    num_layers = p.get("num_layers", 6)    # 解码器层数 (官方默认 6)
    if log:
        log(f"🔡 Decoder: num_layers={num_layers}")
    # 官方源码: ACT.decoder = nn.TransformerDecoder(...) 生成未来 T 步动作
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"Decoder 配置: layers={num_layers}")


# ════════════════════════════════════════════════════════════════
# 🎯 Action Head 4D — 官方 action_head (线性映射到动作空间)
# ════════════════════════════════════════════════════════════════
def node_action_head(ctx):
    """🎯 Action Head — 解码特征 → 关节动作 (维度=数据动作维度)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    action_dim = p.get("action_dim", 4)      # ★ 4=metaworld(sawyer) / 6=真机Orin珞石
    chunk_size = p.get("chunk_size", 7)      # 每次预测的动作步数
    if log:
        log(f"🎯 ActionHead: action_dim={action_dim} · chunk={chunk_size} (真机Orin为6D)")
    # 官方源码: self.action_head = nn.Linear(dim_model, action_dim)
    #   输出维度自动取自数据特征, 训练数据决定, 改这里仅影响说明
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"ActionHead 配置: {action_dim}D chunk={chunk_size}")


# ════════════════════════════════════════════════════════════════
# ⏳ Temporal Ensemble — 官方 ACTTemporalEnsembler (动作平滑)
# ════════════════════════════════════════════════════════════════
def node_ensemble(ctx):
    """⏳ Temporal Ensemble — 多步预测加权平均, 抑制抖动"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    coeff = p.get("coeff", 0.01)     # 平滑系数 (官方默认 0.01, 越大越平滑但延迟更高)
    if log:
        log(f"⏳ Ensemble: coeff={coeff}")
    # 官方源码: ACTTemporalEnsembler(coeff=0.01) — 指数滑动平均
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Ensemble 配置: coeff={coeff}")


# ════════════════════════════════════════════════════════════════
# 📊 Scope 示波器 — 训练效果观察 (Simulink Scope 对标)
# ════════════════════════════════════════════════════════════════
def node_scope(ctx):
    """📊 Scope 示波器 — 显示训练 loss 曲线/执行效果"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("📊 Scope: 打开示波器查看训练 loss 曲线 (Simulink Scope 对标)")
    # 想加通道? 在这里写 (例如: 训练完同时统计 action 输出范围)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 打开示波器对话框 (勿改)
    return module.on_scope()


# ════════════════════════════════════════════════════════════════
# 🧠 SmolVLM2-500M — SmolVLA 视觉语言主干 (多模态编码, 冻结/参与训练)
# ════════════════════════════════════════════════════════════════
def node_smolvlm2(ctx):
    """🧠 SmolVLM2-500M — 视觉语言主干 (SmolVLM2-500M-Video-Instruct)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    freeze = p.get("freeze", True)      # True=冻结(VLM 只做编码) / False=参与训练(LEW 需要)
    smolvlm = p.get("smolvlm", "HuggingFaceTB/SmolVLM2-500M-Video-Instruct")
    if log:
        log(f"🧠 SmolVLM2-500M: freeze={freeze} · {smolvlm}")
    # 官方源码: modeling_smolvla_lew.py SmolVLALewPolicy — SmolVLM2 多模态编码
    #   视觉+语言 → 多模态 embeds → DiT 动作解码; LEW 分支要求 freeze=False
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 SmolVLA 配置 (勿改)
    return (True, f"SmolVLM2: freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🌀 DiT-B 动作解码 — SmolVLA action_model (扩散去噪生成动作块)
# ════════════════════════════════════════════════════════════════
def node_dit_b(ctx):
    """🌀 DiT-B 动作解码 — SmolVLA 扩散动作生成器 (含 base VLA 冻结版)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    hidden = p.get("hidden", 256)       # DiT 隐藏宽度 (4060 精简 256)
    layers = p.get("layers", 1)         # 层数 (1=精简, 官方更多)
    timesteps = p.get("timesteps", 2)   # 推理扩散步数 (num_inference_timesteps)
    freeze = p.get("freeze", False)     # VLA-Touch base VLA 冻结版=True
    if log:
        log(f"🌀 DiT-B: hidden={hidden} · layers={layers} · timesteps={timesteps} · freeze={freeze}")
    # 官方源码: action_model_type="DiT-B" — 噪声预测网络, 条件=多模态 embeds
    #   VLA-Touch 中作 base VLA 冻结 (不训练, 只出粗动作给 Interpolant 精炼)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"DiT-B: hidden={hidden} layers={layers} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🌐 LeWorldModel — 世界模型旁路 (视频帧+动作 → 预测下一帧)
# ════════════════════════════════════════════════════════════════
def node_lew(ctx):
    """🌐 LeWorldModel — 潜空间世界模型 (SigLIP 编码→AdaLN-zero 调制→预测下一帧)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    lew_loss_weight = p.get("lew_loss_weight", 0.1)   # 世界模型 loss 权重 (总loss=扩散+0.1×LEW)
    num_video_frames = p.get("num_video_frames", 2)   # 输入视频帧数
    if log:
        log(f"🌐 LeWorldModel: loss_weight={lew_loss_weight} · frames={num_video_frames}")
    # 官方源码: world_model_le.py LeWorldModel — forward(videos, actions):
    #   SigLIP 编码视频帧 + action_encoder 编码动作 → ARPredictor 预测下一帧
    #   与 DiT-B 并列 (训练时用真值动作), loss 按 lew_loss_weight 加权
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"LEW: weight={lew_loss_weight}")


# ════════════════════════════════════════════════════════════════
# 🖼 DINOv2 视觉编码 — VLA-Touch visual_encoder (视觉嵌入条件)
# ════════════════════════════════════════════════════════════════
def node_dinov2(ctx):
    """🖼 DINOv2 视觉编码 — VLA-Touch 视觉条件 (dinov2-small 22M 冻结)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "dinov2-small")
    freeze = p.get("freeze", True)
    if log:
        log(f"🖼 DINOv2: {backbone} · freeze={freeze} (22M, 4060 无压力)")
    # 官方源码: residual_controller/visual_encoder.py DINOv2Encoder
    #   视觉嵌入 → Interpolant 控制器条件 (π_I(â|s,a,m) 的视觉通道)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"DINOv2: {backbone} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 📍 Marker 触觉跟踪 — VLA-Touch marker_tracker (GelSight 标记位移→力)
# ════════════════════════════════════════════════════════════════
def node_marker(ctx):
    """📍 Marker 触觉跟踪 — GelSight 标记位移 → 低维力信号 m"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    grid = p.get("grid", "7x9")        # 标记网格 (GelSight 默认 7x9)
    dim = p.get("dim", 4)              # 输出力信号维度
    if log:
        log(f"📍 Marker: grid={grid} · dim={dim} (⚠️ metaworld 无真触觉, 当前状态差分模拟, 真机换 H06)")
    # 官方源码: residual_controller/tactile/marker/marker_tracker.py
    #   EnhancedMarkerTracker: 预处理→检测标记→位移→低维触觉信号 m_t
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Marker: {grid} dim={dim}")


# ════════════════════════════════════════════════════════════════
# 🌉 Interpolant 控制器 — VLA-Touch StochasticInterpolants (桥式扩散精炼)
# ════════════════════════════════════════════════════════════════
def node_interpolant(ctx):
    """🌉 Interpolant 控制器 — 触觉精炼 VLA 动作 (桥式扩散, 唯一训练模块)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    diffuse_steps = p.get("diffuse_steps", 10)   # 采样扩散步数
    hidden = p.get("hidden", 256)                # 控制器隐藏宽度
    if log:
        log(f"🌉 Interpolant: diffuse_steps={diffuse_steps} · hidden={hidden}")
    # 官方源码: residual_controller/bridge/bridge_model.py StochasticInterpolants
    #   输入 x0=VLA 动作 / x1=专家动作 / cond=视觉+触觉+状态 → velocity_loss
    #   4060 精简: base VLA 冻结, 只训练此控制器 (≈1M 参数)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Interpolant: steps={diffuse_steps} hidden={hidden}")


# ════════════════════════════════════════════════════════════════
# 🖐 SigLIP 视触觉编码 — AWE 场景原生 (视觉+力觉/触觉 原生融合)
# ════════════════════════════════════════════════════════════════
def node_siglip(ctx):
    """🖐 SigLIP 视触觉编码 — AWE 原生多模态 (视觉+力觉/触觉 场景级融合)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "siglip-base")
    freeze = p.get("freeze", True)
    tactile_dim = p.get("tactile_dim", 4)
    if log:
        log(f"🖐 SigLIP 视触觉: {backbone} · freeze={freeze} · tactile_dim={tactile_dim} (⚠️ metaworld 力觉为模拟)")
    # 官方源码: 对标它石 Born as One — 视觉·触觉·力觉·动作 从基因层面融合
    #   train_awe_zflow.py HJEPAEncoder: proj_vis + proj_state + proj_tactile 同层相加
    #   (非后期"乐高式"拼接)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"SigLIP 视触觉: {backbone} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🧠 H-JEPA 三层潜空间 — AWE zFlow (z₁空间/z₂物体/z₃语义)
# ════════════════════════════════════════════════════════════════
def node_hjepa(ctx):
    """🧠 H-JEPA 三层潜空间 — 空间/物体/语义 分层潜表示"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    d_z1 = p.get("d_z1", 128)    # z₁空间 (物体位姿)
    d_z2 = p.get("d_z2", 128)    # z₂物体 (类别属性)
    d_z3 = p.get("d_z3", 64)     # z₃语义 (任务目标)
    if log:
        log(f"🧠 H-JEPA: z₁={d_z1} z₂={d_z2} z₃={d_z3} (4060 等比缩小自 256/256/128)")
    # 官方源码: train_awe_zflow.py HJEPAEncoder — 三层潜空间头分离
    #   对标它石 OmniVTA / H-JEPA: 从被动感知 → 主动预测接触演化
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"H-JEPA: z₁={d_z1} z₂={d_z2} z₃={d_z3}")


# ════════════════════════════════════════════════════════════════
# 🌊 zFlow 世界引擎 — AWE GRU 预测器 (潜空间推演未来状态)
# ════════════════════════════════════════════════════════════════
def node_zflow(ctx):
    """🌊 zFlow 世界引擎 — GRU 预测未来潜状态 (轻量, Orin Nano 可部署)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gru = p.get("gru", 128)      # GRU 隐藏宽度
    layers = p.get("layers", 1)
    if log:
        log(f"🌊 zFlow: GRU hidden={gru} · layers={layers}")
    # 官方源码: train_awe_zflow.py GRUPredictor — 潜状态+动作历史 → 未来潜状态
    #   对标它石 zFlow 世界引擎: 世界模型驱动后训练, 潜空间推演未来状态
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"zFlow: GRU={gru}")


# ════════════════════════════════════════════════════════════════
# 🔀 未来决策交叉注意力 — AWE CrossAttnInject (预测潜状态 K/V 注入动作解码)
# ════════════════════════════════════════════════════════════════
def node_cross_attn(ctx):
    """🔀 未来决策交叉注意力 — 三层未来潜状态各作 K/V 注入动作解码 (真 CrossAttention, 分层门控 1.0/0.1/0.01)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gates = p.get("gates", "1.0/0.1/0.01")   # 三层潜状态门控权重 (z₁空间/z₂物体/z₃语义)
    if log:
        log(f"🔀 未来决策交叉注意力: gates={gates} (训练注入 / 推理门控归零可剥离, 零额外开销)")
    # 官方源码: train_awe_zflow.py CrossAttnInject (2026-08-05 老倪纠正为真 CrossAttention):
    #   z₁/z₂/z₃ 各自独立投影为 K/V token (ModuleList, 层间不共享) → Q=解码隐层
    #   → 逐层 MultiheadAttention 交互 → 每层输出乘各自门控再残差融合
    #   ⚠️ 不能拼接成单 token (那退化成恒等, 非真注意力)
    #   对标它石 LAS 隐空间丝滑动作 / OmniVTA 分层注入
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"CrossAttn: gates={gates}")


# ════════════════════════════════════════════════════════════════
# ☑ 训练开关 — checkbox 打勾=训练 / 不打=不训练 (train_gate 节点)
# ════════════════════════════════════════════════════════════════
def node_train_gate(ctx):
    """☑ 训练开关 — 打勾=训练 / 不打=不训练 (放最前边控全链路)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    train_enabled = p.get("train_enabled", True)
    if log:
        log(f"☑ 训练开关: {'打勾 → 训练启用' if train_enabled else '不打勾 → 训练跳过'} (双击切换)")
    # 想自定义判定? 在这里写 (例如: 按时间段/产线状态自动决定是否训练)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 切换开关状态 (勿改)
    return module._toggle_train_gate_ctx(ctx["name"], train_enabled)


# ════════════════════════════════════════════════════════════════
# 🎯 YOLO 感知开关 — 有 YOLO(39D) / 无 YOLO(3D) (2026-08-06 老倪: state 输入 switch,
#    默认加载 YOLO 状态)
# ════════════════════════════════════════════════════════════════
def node_yolo_gate(ctx):
    """🎯 YOLO 感知开关 — 开=39D完整观测(YOLO检测产出) / 关=3D末端位置(无感知)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    yolo_enabled = p.get("yolo_enabled", True)  # 默认加载 YOLO (39D)
    state_dim = 39 if yolo_enabled else 3
    if log:
        log(f"🎯 YOLO 感知开关: {'开 → state 39D (YOLO检测产出, 含销钉/孔坐标)' if yolo_enabled else '关 → state 3D (仅末端位置, 无目标感知)'} · 默认开")
    # 想自定义判定? 在这里写 (例如: 按相机可用性自动切换)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 记录开关状态到节点 (勿改)
    return module._toggle_yolo_gate_ctx(ctx["name"], yolo_enabled)


# ════════════════════════════════════════════════════════════════
# 🎥 视频显示 — 推理效果对比 (rollout 视频播放窗口)
# ════════════════════════════════════════════════════════════════
def node_video_display(ctx):
    """🎥 视频显示 — 训练后 rollout 推理效果 (多窗口同步播放)"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("🎥 视频显示: 双击 → 多模型 rollout 视频同步播放对比 (推理效果)")
    # 想自定义? 例如: 只播放指定模型的视频
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 推理效果对比 (勿改)
    return module.on_infer_video()


# ════════════════════════════════════════════════════════════════
# 📄 PDF 技术选型报告 — 五模型对比实验 → 11 章专业报告
# ════════════════════════════════════════════════════════════════
def node_pdf_report(ctx):
    """📄 PDF 技术选型报告 — 概况/系统全貌/分系统功能/接口/参数/架构/功能/性价比/优劣势"""
    module = ctx["module"]
    log = ctx["log"]
    if log:
        log("📄 生成五模型对比技术选型报告 (数据: 曲线+视频+画布拓扑)")
    # === ✏️ 可修改区 END ===
    return module.on_pdf_report()


# ── 🔒 框架区: 注册表 (勿改) ──────────────────────────────────────
_reg("collect",    ["采集"],        "① 采集 — 拉取 Orin 真实数据 → 修复 action → 落地", node_collect)
_reg("train",      ["训练", "全新训练"], "② 训练 — ACT 策略训练 (含 metaworld 全新训练)", node_train)
_reg("validate",   ["验证"],        "③ 验证 — 流程拓扑合规检查 (validate_flow)", node_validate)
_reg("integrate",  ["集成"],        "④ 集成 — 打包 checkpoint → 上传 ECS 中转", node_integrate)
_reg("deploy",     ["部署"],        "⑤ 部署 — 部署状态检查与推送", node_deploy)
_reg("infer",      ["推理"],        "⑥ 推理 — 产线推理服务状态", node_infer)
_reg("mode_switch", ["训练/推理", "模式开关"], "🔀 训练/推理模式开关 — 双击切换 train⇄infer", node_mode_switch)
_reg("infer_rollout", ["推理 (rollout)", "rollout"], "📷 推理 (rollout) — 最新模型仿真插拔评估+视频", node_infer_rollout)
_reg("eval_state_space", ["模型评估 (状态空间)", "状态空间评估"], "📊 状态空间稳定性评估 — L2/BIBO/谱半径/状态机覆盖", node_eval_state_space)
_reg("spectral_norm", ["谱归一化"], "🧮 谱归一化 — 左脑逐层 σ_max → Lipschitz 上界", node_spectral_norm)
_reg("gru_gate", ["GRU 门控"], "🧮 GRU 门控机制 — 右脑潜空间 ρ(W) 收缩", node_gru_gate)
_reg("force_limit", ["力幅值限幅"], "🧮 力幅值限幅 — 插入阶段饱和 → 临界阻尼 ζ", node_force_limit)
_reg("eval_report_pdf", ["稳定性评估 PDF"], "📄 稳定性评估汇总 PDF — 公式+图+数据+结论 → 飞书", node_eval_report_pdf)
_reg("ff_pd_control", ["前馈 PD"], "⚙️ 前馈 PD 控制器 — 顶层增益调度PID+前馈, Z700=底层", node_ff_pd_control)
_reg("ff_ref_input", ["参考输入"], "📡 参考输入 u(t) — 前馈PD顶层输入", node_ff_ref_input)
_reg("ff_scope", ["输出 Scope"], "🖥 输出 Scope — 前馈PD顶层输出响应", node_ff_scope)
_reg("z700_internal", ["Z700 内部"], "🔬 Z700 内部模块 (顶层只读展示)", node_z700_internal)
# 🧠 神经同构行 (2026-08-16 老倪: 左脑MLP≈小脑 / 右脑GRU≈非线性卡尔曼 / 状态机≈皮层)
_reg("neural_kalman", ["右脑 · 非线性卡尔曼", "非线性卡尔曼"], "🔮 右脑·非线性卡尔曼 — 世界模型: 预测(状态转移A)+更新(门控K)", node_neural_kalman)
_reg("neural_alpha", ["α 融合层", "置信度旋钮"], "⚖️ α融合层 — fused=(1−α)·预测+α·观测, α≈等效卡尔曼增益", node_neural_alpha)
_reg("neural_calib", ["左脑标定实验", "标定实验"], "🔧 左脑标定 — 感知零偏/执行力act_gain·err_gain/现场微调 三件套", node_neural_calib)
_reg("neural_climbing", ["攀缘纤维"], "🧬 攀缘纤维 — 力传感器vs右脑预测→复杂脉冲→LTD gate 抑制", node_neural_climbing)
_reg("neural_ltd", ["gate · 突触抑制", "突触抑制"], "🛡 gate·LTD — 左脑不准→瞬间降gate压制, 控制权移交传感器", node_neural_ltd)
_reg("neural_cerebellum", ["左脑 · 小脑", "小脑 (前馈)"], "🧠 左脑·小脑 — 前馈逆动力学 obs→action 直接映射", node_neural_cerebellum)
_reg("neural_cortex", ["皮层 · 状态机"], "🧭 皮层·状态机 — contact+几何误差→阶段切换决策", node_neural_cortex)
_reg("data",       ["metaworld 数据", "metaworld数据"], "📦 数据源选择", node_metaworld_data)
_reg("resnet18",   ["ResNet18", "resnet18"], "🖼 视觉主干 — ACT.backbone", node_resnet18)
_reg("cvae",       ["CVAE", "cvae"], "🧬 VAE 编码器 — 动作条件变分自编码器", node_cvae)
_reg("encoder",    ["Encoder", "encoder"], "🔤 Transformer Encoder — 上下文向量", node_encoder)
_reg("decoder",    ["Decoder", "decoder"], "🔡 Transformer Decoder — 动作序列", node_decoder)
_reg("action_head", ["Action Head", "action_head"], "🎯 Action Head — 关节动作映射", node_action_head)
_reg("ensemble",   ["Temporal Ensemble", "Ensemble"], "⏳ Temporal Ensemble — 动作平滑", node_ensemble)
_reg("scope",      ["Scope"], "📊 Scope 示波器 — 训练效果波形", node_scope)
# 🆕 2026-08-08 老倪: 总系统节点标准化 — Subsystem 双击展开「🔬 模型对比」
def node_topsys(module, node, label=None):
    """🔬 总系统 (Subsystem) — 双击展开「🔬 模型对比」七模型训练线"""
    try:
        sub = (node.get("params") or {}).get("subsystem", "🔬 模型对比")
        if getattr(module, "load_reference_app_by_name", None):
            module.load_reference_app_by_name(sub)
            module._log(f"🔬 总系统 → 展开子系统: {sub}")
    except Exception:
        pass
    return None, "总系统子系统"

_reg("topsys",     ["总系统", "Subsystem"], "🔬 总系统 — Subsystem 双击展开模型对比", node_topsys)
# 🆕 2026-08-05 新增模型节点 (五模型对比 / VLA-Touch / AWE 管道)
_reg("smolvlm2",   ["SmolVLM2"], "🧠 SmolVLM2-500M — 视觉语言主干", node_smolvlm2)
_reg("dit_b",      ["DiT-B", "DiT"], "🌀 DiT-B 动作解码 — 扩散动作生成器", node_dit_b)
_reg("lew",        ["LeWorldModel"], "🌐 LeWorldModel — 潜空间世界模型", node_lew)
_reg("dinov2",     ["DINOv2"], "🖼 DINOv2 视觉编码 — VLA-Touch 视觉条件", node_dinov2)
_reg("marker",     ["Marker"], "📍 Marker 触觉跟踪 — GelSight 标记位移→力", node_marker)
_reg("interpolant", ["Interpolant"], "🌉 Interpolant 控制器 — 桥式扩散精炼", node_interpolant)
_reg("siglip",     ["SigLIP"], "🖐 SigLIP 视触觉编码 — AWE 原生多模态融合", node_siglip)
_reg("hjepa",      ["H-JEPA"], "🧠 H-JEPA 三层潜空间 — z₁/z₂/z₃ 分层潜表示", node_hjepa)
_reg("zflow",      ["zFlow"], "🌊 zFlow 世界引擎 — GRU 预测未来潜状态", node_zflow)
_reg("cross_attn", ["交叉注意力"], "🔀 未来决策交叉注意力 — 未来潜状态 K/V 注入", node_cross_attn)
_reg("train_gate", ["训练开关"], "☑ 训练开关 — 打勾=训练 / 不打=不训练", node_train_gate)
_reg("yolo_gate", ["YOLO 感知开关", "YOLO开关"], "🎯 YOLO 感知开关 — 开=39D(有YOLO) / 关=3D(无YOLO), 默认开", node_yolo_gate)


# ── 🎯 YOLO 3D 感知链 (2026-08-12 老倪: 源码显示 yolo_3d/, 右键菜单也可打开)
# 🐛 2026-09-01 老倪: 画布节点必须真实执行 — 原 node_yolo_3d/node_yolo_align 只打日志
#   (用户在 align() 打断点进不去的根因); 现真实加载 YoloStateAligner → metaworld 渲染帧
#   → detect_3d → align(), 断点可进 yolo_state_aligner.py
_YOLO_ALIGNER = None      # YoloStateAligner 单例 (权重+env 只加载一次, 复用 gen_metaworld_data.py:39 方案)
_YOLO_CACHE = {}          # 跨节点共享: det3d / obs39 / img (🎯 YOLO 3D → 📐 2D→3D 链路)
_YOLO_READY = False       # import 链是否已在主线程就绪 (2026-09-02)


def _yolo_prepare_imports():
    """主线程预 import YOLO 依赖链 (yolo_state_aligner + metaworld→gymnasium→cv2 Qt 插件).

    🐛 2026-09-02 老倪: 必须在主线程且 QApplication 创建后执行 — 后台线程 import
    metaworld 会 QObject::moveToThread 归属错误 + debugpy realpath abort (GUI 启动崩,
    实测 Fatal Python error: Aborted); import 就绪后构造/推理可放后台线程 (纯计算不碰 Qt).
    """
    global _YOLO_READY
    if _YOLO_READY:
        return
    import sys as _sys
    os.environ.setdefault("MUJOCO_GL", "glfw")
    _sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "yolo_3d"))
    import yolo_state_aligner  # noqa: F401
    import metaworld as _mt   # noqa: F401  Qt 依赖链 — 必须主线程!
    _YOLO_READY = True


def _yolo_ensure_aligner(log):
    """懒加载真实 YoloStateAligner — 权重 runs/detect/outputs/yolo_peg/peg_v1/best.pt + metaworld env
    绕过 lerobot 包 __init__ (同 gen_metaworld_data.py:39, 避免 huggingface_hub 等重量级依赖)"""
    global _YOLO_ALIGNER
    if _YOLO_ALIGNER is not None:
        return _YOLO_ALIGNER
    import sys as _sys
    os.environ.setdefault("MUJOCO_GL", "glfw")
    _sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "yolo_3d"))
    import yolo_state_aligner
    _cands = ["runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
              "outputs/yolo_peg/peg_v1/weights/best.pt"]
    _w = next((c for c in _cands if os.path.isfile(os.path.join(_REPO_ROOT, c))), _cands[0])
    # 🎯 深度模型权重候选 (YOLO depth head) — 🐛 2026-09-03 老倪: 原构造漏传
    #   depth_weights → depth_model=None → detect_3d 全程走「写死 z 平面」回退
    #   (断点停在 118 行). 候选与 gen_insert_video.py:36 同款, GPU 自动校准版优先.
    _d_cands = ["outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt",   # GPU自动校准版 (scale 0.978/0.885)
                "outputs/yolo_peg_depth/peg_depth_v1/weights/best.pt",      # 旧 CPU 版 (已作废, 回退用)
                "outputs/yolo_peg_depth/peg_depth_smoke/weights/best.pt"]
    _dw = next((c for c in _d_cands if os.path.isfile(os.path.join(_REPO_ROOT, c))), None)
    import metaworld as _mt
    _mt_env = _mt.MT1("peg-insert-side-v3")
    _env0 = _mt_env.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    _env0._freeze_rand_vec = False
    _env0.set_task(_mt_env.train_tasks[0])
    _env0.reset(seed=0)
    _env0._freeze_rand_vec = True
    _YOLO_ALIGNER = yolo_state_aligner.YoloStateAligner(os.path.join(_REPO_ROOT, _w), _env0,
                                                        depth_weights=(os.path.join(_REPO_ROOT, _dw) if _dw else None))
    if log:
        log(f"🎯 YOLO 真实模型已加载: {_w} · metaworld peg-insert-side-v3 (corner2)"
            + (f" · 深度 {_dw}" if _dw else " · ⚠️ 无深度权重 → detect_3d 走写死 z 回退"))
    return _YOLO_ALIGNER


def _yolo_detect2d(aligner, img, conf=0.4):
    """同帧真实 2D 检测 (与 detect_3d 同预处理 rot90+BGR) → {cls: {box, conf, cx, cy}}
    🐛 2026-09-03 老倪: detect_3d 只返回 3D 坐标不带 conf — ▶运行 注入引擎轨迹
    需要真实 conf (引擎 _io_snapshot 曾写死 conf 0.99 伪装), 故同帧补一次 2D predict。
    """
    import numpy as np
    import cv2
    if img.dtype != np.uint8:
        img = (img * 255).astype(np.uint8)
    img_rot = np.rot90(img, k=2)
    img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
    res = aligner.model.predict(img_bgr, conf=conf, verbose=False)[0]
    out = {}
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        out[cls] = {"box": [x1, y1, x2, y2], "conf": float(b.conf[0]),
                    "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2}
    return out


def _yolo_capture(log, aligner):
    """真实采样一帧: env reset(seed=0) → render → 39D obs → detect_3d, 缓存供下游节点"""
    import numpy as np
    aligner.env._freeze_rand_vec = False
    aligner.env.reset(seed=0)
    aligner.env._freeze_rand_vec = True
    img = aligner.env.render()
    obs39 = np.asarray(aligner.env._get_obs(), dtype=np.float64).ravel()
    det3d = aligner.detect_3d(img)
    det2d = _yolo_detect2d(aligner, img)   # 真实 conf/框 (detect_3d 不带 conf)
    _YOLO_CACHE.update({"det3d": det3d, "det2d": det2d, "obs39": obs39, "img": img})
    return det3d, obs39, img


def node_yolo_3d(ctx):
    """🎯 YOLO 3D — 真实执行: metaworld 渲染帧 → YOLO 检测 → 3D 反投影
    源码: src/lerobot/policies/yolo_3d/yolo_state_aligner.py (detect_3d / align)
    ─────────────────────────────────────────────
    数据流: 相机图像 → YOLO {hand, 光模块, hole} → 反投影 3D → 缓存 → 📐 2D→3D 节点 align 进 39D"""
    log = ctx["log"]
    try:
        aligner = _yolo_ensure_aligner(log)
        det3d, obs39, img = _yolo_capture(log, aligner)
        if log:
            if det3d:
                for k, v in sorted(det3d.items()):
                    log(f"🎯 YOLO 3D: {k}=[{v[0]:.3f} {v[1]:.3f} {v[2]:.3f}]m")
                log(f"🎯 检测 {len(det3d)}/3 目标 (hand/peg/hole) · 39D 状态已采样")
            else:
                log("🎯 YOLO 3D: ⚠️ 本帧未检出目标 (conf<0.4) — 重试或换帧")
        return bool(det3d)
    except Exception as e:
        if log:
            log(f"⚠️ YOLO 3D 真实执行失败: {e}")
        return False


def node_yolo_align(ctx):
    """📐 2D→3D 解算 — 真实执行: YOLO 检测 3D → align() 替换 39D 对应段
    源码: yolo_state_aligner.py align() — hand→[0:3], 光模块→[4:7]+[22:25], hole→[36:39]
    🐛 旧版误把 光模块 写进 [18:21](prev_hand), 真 光模块 段 [4:7]/[22:25] 一直漏真值 → 训练泄漏 (2026-08-23 已修)"""
    log = ctx["log"]
    try:
        import numpy as np
        aligner = _yolo_ensure_aligner(log)
        det3d = _YOLO_CACHE.get("det3d")
        obs39 = _YOLO_CACHE.get("obs39")
        if det3d is None or obs39 is None:
            # 单独执行本节点 (未先跑 🎯 YOLO 3D) → 同源采样一帧
            det3d, obs39, _ = _yolo_capture(log, aligner)
        aligned = aligner.align(obs39, det3d)
        if log:
            log(f"📐 2D→3D 解算: hand={np.round(aligned[0:3],3)} · "
                f"光模块={np.round(aligned[4:7],3)} · hole={np.round(aligned[36:39],3)} (真实对齐)")
            log("📐 39D 对齐完成 · 断点可进 yolo_state_aligner.align()")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 2D→3D 真实执行失败: {e}")
        return False


def node_yolo_tactile(ctx):
    """📍 Marker 触觉跟踪 — 真实执行: gen_tactile.py synth_tactile 从 39D 合成 4D (夹持/接触/方向)
    🐛 2026-09-01 真实化: 原只打日志, gen_tactile.py 断点永不命中"""
    log = ctx["log"]
    try:
        import numpy as np
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
            _SS_STATE["obs39"] = obs39
        tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
        _SS_STATE["tactile4"] = tac
        if log:
            log(f"📍 Marker 触觉 (真实): grasp={tac[0]:.3f} contact={tac[1]:.3f} "
                f"dir=({tac[2]:.2f},{tac[3]:.2f}) (gen_tactile.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 触觉合成真实执行失败: {e}")
        return False


_reg("yolo_3d",     ["YOLO 3D"], "🎯 YOLO 3D — 检测销钉/插孔/末端 → 2D→3D → 39D state (源码 yolo_3d/)", node_yolo_3d)
_reg("yolo_align",  ["2D→3D"], "📐 2D→3D 解算 — 像素→3D 坐标 (源码 yolo_3d/yolo_state_aligner.py)", node_yolo_align)
_reg("yolo_tactile", ["Marker 触觉", "触觉感知"], "📍 Marker 触觉跟踪 — 4D 触觉信号 (源码 yolo_3d/gen_tactile.py)", node_yolo_tactile)


# ── 📦 Z700 数据源 / 适配 / obs (2026-08-12 老倪: 每个节点都有代码) ──
def node_metaworld_peg(ctx):
    log = ctx["log"]
    """📦 metaworld_peg — 仿真插拔数据集 (39D 状态 + 图像, 24集 4800帧)
    数据生成: tools/gen_metaworld_data.py; 触觉增强: src/lerobot/policies/yolo_3d/gen_tactile.py (39D→43D)"""
    p = ctx.get("params", {})
    log(f"📦 metaworld_peg: frames={p.get('frames', 4800)} dims={p.get('dims', '4D/4D')} · 数据源: 喂感知链+训练")
    return True


def node_state_adapter(ctx):
    log = ctx["log"]
    """🔌 State Adapter — 感知融合: 视觉 39D + 触觉 4D = 43D 统一输入
    数据流适配: 归一化/拼接/维度对齐 (策略输入接口, 与训练配置 processor 对应)"""
    p = ctx.get("params", {})
    log(f"🔌 State Adapter: in={p.get('in_dim', 43)} out={p.get('out_dim', 43)} normalize={p.get('normalize', True)} · 视觉39D+触觉4D=43D")
    return True


def node_obs43(ctx):
    log = ctx["log"]
    """📊 43D obs 输入 — 感知链与策略的统一状态输入 (39D 视觉/关节 + 触觉 4D)

    结构: 43D = 当前帧(18) + 上一帧(18) + 目标(3) + 触觉(4)   [双帧堆叠 + Marker 触觉]
    ─────────────────────────────────────────────
    39D 部分 (metaworld peg-insertion 观测, 与 node_obs39 一致):
    [0:3]    hand_pos      末端执行器位置 xyz    单位: 米(m)
    [3]      gripper       夹爪开度 (归一化)     0=闭合 · 1=张开
    [4:7]    peg_pos       销钉位置 xyz          单位: 米(m)
    [7:11]   peg_quat      销钉姿态四元数 xyzw   单位四元数 (w=1 无旋转)
    [11:18]  pad           填充槽 ×7 (固定 0)    物体槽位余量
    [18:21]  prev_hand_pos 上一帧末端位置 xyz    单位: 米(m)
    [21]     prev_gripper  上一帧夹爪开度        0=闭合 · 1=张开
    [22:25]  prev_peg_pos  上一帧销钉位置 xyz    单位: 米(m)
    [25:29]  prev_peg_quat 上一帧销钉四元数 xyzw 单位四元数
    [29:36]  prev_pad      填充槽 ×7 (固定 0)
    [36:39]  hole_pos      插孔目标位置 xyz      单位: 米(m) (goal)
    ─────────────────────────────────────────────
    触觉 4D (Marker 触觉跟踪, gen_tactile.py 从 39D state 合成):
    [39]     grasp_force   夹持力   = 1 − gripper   (夹爪闭合=1, 张开=0)
    [40]     contact_force 接触力   = 1/(1+5d)      (d=|光模块−hole|, 越近越大)
    [41]     contact_dir_x 接触方向x = (peg_x−hole_x)/d
    [42]     contact_dir_z 接触方向z = (peg_z−hole_z)/d
    ─────────────────────────────────────────────
    说明: 视觉/关节 39D 双帧堆叠感知时序, 触觉 4D 补力觉通道 (metaworld 无 GelSight 真实触觉)"""
    p = ctx.get("params", {})
    log(f"📊 43D obs: dims={p.get('dims', 43)} · 39D 结构(双帧堆叠+目标) + 触觉4D")
    return True


def node_solution_web(ctx):
    log = ctx["log"]
    """🌐 方案介绍 — 打开方案介绍分页 (datadrive.world/solution.html, 含PDF下载)
    网页: zmax-website/solution.html + Z700-方案介绍.pdf (线上部署)"""
    p = ctx.get("params", {})
    log("🌐 方案介绍: 打开 https://datadrive.world/solution.html · 光模块工厂5大场景/架构/节点职责")
    return True


_reg("metaworld_peg", ["metaworld_peg"], "📦 metaworld_peg — 插拔数据集 39D+图像 (源码 tools/gen_metaworld_data.py)", node_metaworld_peg)
_reg("state_adapter", ["State Adapter"], "🔌 State Adapter — 视觉39D+触觉4D=43D 融合适配", node_state_adapter)
_reg("obs43", ["43D obs"], "📊 43D obs 输入 — 39D结构+触觉4D=43D 统一输入", node_obs43)
_reg("solution_web", ["方案介绍"], "🌐 方案介绍 — 打开方案分页 (datadrive.world/solution.html)", node_solution_web)


# ── ➤ 状态机 6 阶段 (2026-08-12 老倪: 每阶段代码, 参数对应 configuration_left_right.py) ──
def node_stage_approach(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 接近: bias={p.get('bias', 'act*0.3 + hand→peg方向*2.0')} · 规则方向+学习修正 (5/8 vs 0/8)")
    return True


def node_stage_grasp(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 抓取: effort={p.get('effort', 0.6)} · 专家式夹持+位置锁定")
    return True


def node_stage_lift(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 抬起: height={p.get('height', 0.08)}m force={p.get('force', 0.8)} · 避开台面")
    return True


def node_stage_transfer(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 转移: tolerance={p.get('tolerance', 0.05)}m · 光模块 有导向")
    return True


def node_stage_insert(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 插入: tolerance={p.get('tolerance', 0.05)}m · 完成插拔")
    return True


def node_stage_done(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 完成: stage={p.get('stage', 'done')} · 释放/复位, 进入下一循环")
    return True


_reg("stage_approach", ["➤ 接近"], "➤ 接近 — 偏置接近 (状态机第1阶段, 源码 left_right/)", node_stage_approach)
_reg("stage_grasp",    ["➤ 抓取"], "➤ 抓取 — 专家式夹持 0.6 (状态机第2阶段)", node_stage_grasp)
_reg("stage_lift",     ["➤ 抬起"], "➤ 抬起 — +8cm 避台面 (状态机第3阶段)", node_stage_lift)
_reg("stage_transfer", ["➤ 转移"], "➤ 转移 — 容差 5cm (状态机第4阶段)", node_stage_transfer)
_reg("stage_insert",   ["➤ 插入"], "➤ 插入 — 完成插拔 (状态机第5阶段)", node_stage_insert)
_reg("stage_done",     ["➤ 完成"], "➤ 完成 — 释放复位 (状态机第6阶段)", node_stage_done)


# ════════════════════════════════════════════════════════════════
# 🧩 坐标叠加 (CoordOverlay) — 2026-08-08 老倪架构: 坐标是逻辑主线,
#    图像是背景 — state 叠加进 latent (latent += 坐标投影), 不混合进 token 序列
# ════════════════════════════════════════════════════════════════
def node_coord_overlay(ctx):
    """🧩 坐标叠加 — 坐标投影叠加到 latent (逻辑主线), 图像作背景 token (旁路)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gate = p.get("overlay_gate", 1.0)      # 叠加门控: 1.0=坐标完全叠加, 0.0=禁用叠加
    state_dim = p.get("state_dim", 45)     # 39D 或 45D (含相对向量)
    if log:
        log(f"🧩 坐标叠加: latent += 坐标投影 × {gate} (state {state_dim}D) — 图像降为背景 token, 坐标是逻辑主线")
    # 想自定义? 例如: 按任务切换 gate 或 state_dim
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 记录叠加状态到节点 (勿改)
    fn = getattr(module, "_set_coord_overlay_ctx", None)
    return fn(ctx["name"], gate, state_dim) if fn else None


_reg("coord_overlay", ["结构条件", "坐标叠加", "CoordOverlay"], "🧩 结构条件 — state 叠加进 latent (逻辑主线), 图像作背景", node_coord_overlay)
_reg("video_display", ["视频"], "🎥 视频显示 — 推理效果 rollout 播放", node_video_display)
_reg("pdf_report",   ["PDF"], "📄 PDF 报告 — 五模型技术选型 (11章)", node_pdf_report)


# ════════════════════════════════════════════════════════════════
# 🧠 left_right 双脑工程 (2026-08-10 老倪: 左脑MLP动作 + 右脑WM判断 + 状态机)
#   真实实现: src/lerobot/policies/left_right/modeling_left_right.py
#   位置映射: _EXTERNAL_LOC (VSCode 打开真实源码)
# ════════════════════════════════════════════════════════════════
# 📂 外部源码位置: 语义key → (绝对路径, 行号, 真实符号名) — 覆盖 node_logic.py 自身位置
_EXTERNAL_LOC = {}
# node_logic.py 在 <root>/tools/gui/ → 仓库根 = dirname ×3
# 🐛 2026-08-26: Windows exe/绿色版 __file__ 在 AppData 解压目录 → 上溯三级拼出
#   C:\Users\Admin\AppData\Local\src\... (不存在)。与 state_space_sim 同款多候选探测:
#   env ZMAX_REPO_ROOT → frozen _MEIPASS → 上溯三级 → 向上逐级找含 src/lerobot 的仓库根
import sys as _sys

def _node_repo_root():
    """仓库根定位 (多候选): env ZMAX_REPO_ROOT → frozen _MEIPASS → __file__ 上溯三级 → 向上逐级探测"""
    env = os.environ.get("ZMAX_REPO_ROOT")
    if env and os.path.isdir(env):
        return env
    if getattr(_sys, "frozen", False):
        return getattr(_sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(_LOGIC_FILE))))
    _d = os.path.dirname(_LOGIC_FILE)
    while True:
        if os.path.isdir(os.path.join(_d, "src", "lerobot")):
            return _d
        _p = os.path.dirname(_d)
        if _p == _d:
            break
        _d = _p
    return os.path.dirname(os.path.dirname(os.path.dirname(_LOGIC_FILE)))  # 兜底: 上溯三级

_REPO_ROOT = _node_repo_root()
_LR_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "left_right")
_EXTERNAL_LOC["left_brain"]  = (os.path.join(_LR_DIR, "modeling_left_right.py"), 45, "class LeftBrainMLP")   # 🐛 2026-08-10: 显示真实符号名, 不是 node_logic 函数名
_EXTERNAL_LOC["right_brain"] = (os.path.join(_LR_DIR, "modeling_left_right.py"), 60, "class RightBrainWM")
_EXTERNAL_LOC["left_right"]  = (os.path.join(_LR_DIR, "modeling_left_right.py"), 76, "class LeftRightPolicy")
_EXTERNAL_LOC["lr_contact"]  = (os.path.join(_LR_DIR, "configuration_left_right.py"), 34, "class LeftRightConfig")  # 🐛 2026-08-12: 原 sym 非符号名定位失败 → 显示整个配置类 (含接触/状态机阈值)

# 🎯 YOLO 3D 感知链 (2026-08-12 老倪: 查看/编辑节点逻辑 → 显示真实源码 yolo_3d/)
_YOLO_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "yolo_3d")
_EXTERNAL_LOC["yolo_3d"] = (os.path.join(_YOLO_DIR, "yolo_state_aligner.py"), 37, "class YoloStateAligner")   # 🎯 YOLO 3D 检测+2D→3D 核心
# 🐛 2026-09-04 静静: 原映射指向 pixel_to_ray(11行) — 2026-08-23 改 cam_mat0 矩阵反投影后已成死代码,
#   全仓库零执行调用 → 查看源码/断点永不命中 (老倪断点停在 detect_3d 126 才发现). 改指真实反投影 detect_3d.
_EXTERNAL_LOC["yolo_align"] = (os.path.join(_YOLO_DIR, "yolo_state_aligner.py"), 53, "def detect_3d")  # 📐 2D→3D 解算: YOLO 框→cam_mat0 反投影→3D (深度优先/写死z回退) — 断点打 104-110 行
_EXTERNAL_LOC["yolo_tactile"] = (os.path.join(_YOLO_DIR, "gen_tactile.py"), 21, "def synth_tactile")  # 🐛 2026-09-02: 符号 gen_tactile 不存在, 实际 def synth_tactile                  # 📍 Marker 触觉跟踪 (触觉数据生成)
_EXTERNAL_LOC["ss_aoi"]   = (os.path.join(_YOLO_DIR, "quality_check.py"), 40, "class AOIQualityChecker")  # 🐛 2026-09-02: 外观质量检测缺映射 → 双击显示 node_ss_aoi 胶水函数而非真实源码 (同 ss_yolo 断点问题)
# 🐛 2026-08-12: state_adapter 不挂外部源码 — 原误指 yolo_state_aligner.py (与 YOLO 3D 相同, 用户指出);
#   State Adapter 是融合节点 (视觉39D+触觉4D=43D), 无独立实现 → 显示 node_state_adapter 自身函数 (可编辑区)
# 注: obs39 不注册外部映射 — 用户要的是结构说明 (node_obs39 函数体), 不是 metaworld 内部源码


def node_obs39(ctx):
    """📊 39D obs 输入 — metaworld peg-insertion 完整观测 (2026-08-10 实测确认)

    结构: 39D = 当前帧(18) + 上一帧(18) + 目标(3)   [帧堆叠]
    ─────────────────────────────────────────────
    [0:3]    hand_pos      末端执行器位置 xyz    单位: 米(m)
    [3]      gripper       夹爪开度 (归一化)     0=闭合 · 1=张开
    [4:7]    peg_pos       销钉位置 xyz          单位: 米(m)
    [7:11]   peg_quat      销钉姿态四元数 xyzw   单位四元数 (w=1 无旋转)
    [11:18]  pad           填充槽 (固定 0)       物体槽位余量
    [18:21]  prev_hand_pos 上一帧末端位置 xyz    单位: 米(m)
    [21]     prev_gripper  上一帧夹爪开度        0=闭合 · 1=张开
    [22:25]  prev_peg_pos  上一帧销钉位置 xyz    单位: 米(m)
    [25:29]  prev_peg_quat 上一帧销钉四元数 xyzw 单位四元数
    [29:36]  prev_pad      填充槽 (固定 0)
    [36:39]  hole_pos      插孔目标位置 xyz      单位: 米(m) (goal)
    ─────────────────────────────────────────────
    说明: peg-insertion 观测 = 末端+夹爪+销钉(位姿) 双帧堆叠 + 目标孔位。
    45D 版本 = 39D + 6D 相对向量 (peg-hand, hole-光模块); 49D 加触觉; 58D 加 W2-CoT。
    left_right 工程用 39D (无相对向量)。
    """
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    dim = p.get("dim", 39)
    if log:
        log(f"📊 39D obs: 末端{3}+夹爪{1}+销钉{7} ×2帧 + 孔位{3} = 39D (帧堆叠, 单位 m/四元数)")
    # === ✏️ 可修改区 END ===
    return True


def _ss_load_modeling(log):
    """懒加载 modeling_left_right.py (LeftBrainMLP/RightBrainWM 真实 torch 网络, 文件自带 lerobot 兜底)"""
    if "modeling" in _SS_MODS:
        return _SS_MODS["modeling"]
    import importlib.util as _ilu
    import sys as _sys
    _p = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "left_right", "modeling_left_right.py")
    _name = "left_right.modeling_left_right"
    spec = _ilu.spec_from_file_location(_name, _p)
    m = _ilu.module_from_spec(spec)
    _sys.modules[_name] = m   # 🐛 2026-09-01: fallback dataclass 装饰器查 sys.modules, 未注册→None.__dict__
    spec.loader.exec_module(m)
    _SS_MODS["modeling"] = m
    return m


def _ss_load_config(log):
    """懒加载 configuration_left_right.py (LeftRightConfig 真实阈值: 接触/抓取/抬起/转移/插入)"""
    if "config" in _SS_MODS:
        return _SS_MODS["config"]
    import importlib.util as _ilu
    import sys as _sys
    _p = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "left_right", "configuration_left_right.py")
    _name = "left_right.configuration_left_right"
    spec = _ilu.spec_from_file_location(_name, _p)
    m = _ilu.module_from_spec(spec)
    _sys.modules[_name] = m   # 🐛 2026-09-01: 同 modeling — dataclass 需 sys.modules 注册
    spec.loader.exec_module(m)
    _SS_MODS["config"] = m
    return m


def _ss_try_load_ckpt(net, key):
    """尝试加载最新训练权重 (outputs/train/*/checkpoints/…/model.pt → {left,right,...})
    🐛 2026-09-04: glob 原为 outputs/train/*/checkpoints/model.pt, 实际产物在
    checkpoints/003000/pretrained_model/model.pt (多两级) → 命中 0, 画布左/右脑节点
    一直跑随机初始化权重 (日志显示"随机初始化(无ckpt)")。现两种层级都匹配。"""
    import glob as _g
    _cks = sorted(
        _g.glob(os.path.join(_REPO_ROOT, "outputs", "train", "*", "checkpoints", "model.pt"))
        + _g.glob(os.path.join(_REPO_ROOT, "outputs", "train", "*", "checkpoints", "*",
                               "pretrained_model", "model.pt")),
        key=os.path.getmtime)
    if not _cks:
        return False
    try:
        import torch
        _sd = torch.load(_cks[-1], map_location="cpu")
        if isinstance(_sd, dict) and key in _sd:
            _w = _sd[key]
            if hasattr(_w, "state_dict"):
                _w = _w.state_dict()
            net.load_state_dict(_w)
            return True
    except Exception:
        pass
    return False


def node_left_brain(ctx):
    """🧠 左脑 LeftBrainMLP — 真实执行: modeling_left_right.py LeftBrainMLP.forward(obs39) → 4D 动作
    🐛 2026-09-01 真实化: 原只打日志, modeling_left_right.py 断点永不命中; 权重优先加载最新 ckpt"""
    log = ctx["log"]
    try:
        import numpy as np, torch
        ml = _ss_load_modeling(log)
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
            _SS_STATE["obs39"] = obs39
        net = ml.LeftBrainMLP(obs_dim=39, act_dim=4)
        loaded = _ss_try_load_ckpt(net, "left")
        net.eval()
        with torch.no_grad():
            act = net(torch.tensor(np.asarray(obs39, dtype=np.float32)).unsqueeze(0)).numpy().squeeze()
        _SS_STATE["act4"] = act
        if log:
            log(f"🧠 左脑 LeftBrainMLP (真实 forward): {'加载最新ckpt' if loaded else '随机初始化(无ckpt)'} · "
                f"obs39 → 4D 动作 [{act[0]:+.3f} {act[1]:+.3f} {act[2]:+.3f} {act[3]:.2f}] (modeling_left_right.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 左脑真实执行失败: {e}")
        return False


def node_right_brain(ctx):
    """🧠 右脑 RightBrainWM — 真实执行: modeling_left_right.py RightBrainWM.forward(obs,act) → next_obs+contact"""
    log = ctx["log"]
    try:
        import numpy as np, torch
        ml = _ss_load_modeling(log)
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
            _SS_STATE["obs39"] = obs39
        act4 = _SS_STATE.get("act4", np.zeros(4))
        net = ml.RightBrainWM(obs_dim=39, act_dim=4)
        loaded = _ss_try_load_ckpt(net, "right")
        net.eval()
        with torch.no_grad():
            _o = torch.tensor(np.asarray(obs39, dtype=np.float32)).unsqueeze(0)
            _a = torch.tensor(np.asarray(act4, dtype=np.float32)).unsqueeze(0)
            nxt, contact = net(_o, _a)
            nxt = nxt.numpy().squeeze()
            contact = float(contact.numpy().squeeze())
        _SS_STATE.update({"next_obs": nxt, "contact": contact})
        if log:
            log(f"🧠 右脑 RightBrainWM (真实 forward): {'加载最新ckpt' if loaded else '随机初始化(无ckpt)'} · "
                f"contact={contact:.3f} · next_obs 预测={np.round(nxt[:3],3)} (modeling_left_right.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 右脑真实执行失败: {e}")
        return False


def node_left_right_policy(ctx):
    """◉ LeftRightPolicy — 真实执行: 左脑动作 + 右脑 contact + 状态机阈值 (configuration_left_right.py)"""
    log = ctx["log"]
    try:
        import numpy as np
        cfg = _ss_load_config(log).LeftRightConfig()
        ml = _ss_load_modeling(log)
        contact = _SS_STATE.get("contact", 0.0)
        # 状态机转移判定 (真实阈值): 接近→抓取 需要 contact + 距离阈值
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
        d_hp = float(np.linalg.norm(obs39[0:3] - obs39[4:7]))
        grasp_ok = contact > cfg.grasp_contact_threshold and d_hp < cfg.grasp_d_hp
        _SS_STATE["grasp_ok"] = grasp_ok
        if log:
            log(f"◉ LeftRightPolicy (真实): 接触阈={cfg.grasp_contact_threshold} · d_hp阈={cfg.grasp_d_hp} · "
                f"实际 contact={contact:.3f} d_hp={d_hp:.4f} → {'✅ 触发抓取' if grasp_ok else '⏳ 继续接近'} "
                f"(configuration_left_right.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ LeftRightPolicy 真实执行失败: {e}")
        return False


def node_lr_contact(ctx):
    """❖ 接触判定 — 真实执行: 右脑 contact 概率 + 钳口-销钉距离 联合判定 (configuration_left_right.py 阈值)"""
    log = ctx["log"]
    try:
        import numpy as np
        cfg = _ss_load_config(log).LeftRightConfig()
        contact = _SS_STATE.get("contact", 0.0)
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
        d_hp = float(np.linalg.norm(obs39[0:3] - obs39[4:7]))
        hit = contact > cfg.grasp_contact_threshold and d_hp < cfg.grasp_d_hp
        if log:
            log(f"❖ 接触判定 (真实): contact={contact:.3f} > {cfg.grasp_contact_threshold} 且 "
                f"d_hp={d_hp:.4f} < {cfg.grasp_d_hp} → {'✅ 接触成立' if hit else '❌ 未接触'} "
                f"(configuration_left_right.py)")
        return bool(hit)
    except Exception as e:
        if log:
            log(f"⚠️ 接触判定真实执行失败: {e}")
        return False


_reg("left_brain",  ["LeftBrainMLP"], "🧠 左脑 LeftBrainMLP — 39D→4D 连续动作 (547K, 源码 modeling_left_right.py:44)", node_left_brain)
_reg("right_brain", ["RightBrainWM"], "🧠 右脑 RightBrainWM — contact 时机判断 (87K, 源码 modeling_left_right.py:59)", node_right_brain)
_reg("left_right",  ["LeftRightPolicy"], "◉ LeftRightPolicy — 双脑+状态机 lerobot 封装 (源码 modeling_left_right.py:75)", node_left_right_policy)
_reg("lr_contact",  ["接触判定"], "❖ 接触判定 — contact 阈值 + 距离联合判定 (参数在 configuration_left_right.py:44)", node_lr_contact)
_reg("obs39",       ["39D obs", "39D"], "📊 39D obs 输入 — metaworld 完整观测结构 (末端/夹爪/销钉×2帧+孔位, 含单位与解释)", node_obs39)


# ════════════════════════════════════════════════════════════════
# 🧮 状态空间模型画布 (2026-08-18 老倪: 六层源码注册 — 双击/右键显示真实实现)
#   真实实现: src/lerobot/policies/left_right/state_space/*.py (六层模块)
#   画布: flows/state_space_obs.json (14 节点: 4 背景行 + 10 功能节点)
#   映射方式: _EXTERNAL_LOC → NodeLogicDialog 显示真实源码 (只读, 同 left_right 模式)
# ════════════════════════════════════════════════════════════════
_SS_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "left_right", "state_space")


# ── 🧮 状态空间节点真实执行 (2026-09-01 老倪: 右键打开的源码必须能进断点 —
#    原 _ss_run 只打日志, perception.py/parallel.py 等真实源码断点永不命中; 现真实调用) ──
_SS_STATE = {}          # 链路缓存: obs43/obs39/u_ff/latent/prior/z_k/residual/contact_p/stage/u/u_sat/u_prev/tactile4
_SS_MODS = {}           # 真实模块懒加载缓存


def _ss_import(modname):
    """懒加载 state_space 真实模块 (perception/parallel/dynamics/cognition/safety/execution)"""
    if modname in _SS_MODS:
        return _SS_MODS[modname]
    import importlib.util as _ilu
    import sys as _sys
    _p = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "left_right", "state_space", modname + ".py")
    _name = "state_space." + modname
    spec = _ilu.spec_from_file_location(_name, _p)
    m = _ilu.module_from_spec(spec)
    _sys.modules[_name] = m   # 🐛 2026-09-01: dataclass 装饰器查 sys.modules[cls.__module__], 未注册→None.__dict__
    spec.loader.exec_module(m)
    _SS_MODS[modname] = m
    return m


def _ss_tactile_mod():
    """懒加载 gen_tactile.py (真实触觉合成, 与数据生成同源)"""
    if "gen_tactile" in _SS_MODS:
        return _SS_MODS["gen_tactile"]
    import importlib.util as _ilu
    import sys as _sys
    _p = os.path.join(_REPO_ROOT, "src", "lerobot", "policies", "yolo_3d", "gen_tactile.py")
    _name = "yolo_3d.gen_tactile"
    spec = _ilu.spec_from_file_location(_name, _p)
    m = _ilu.module_from_spec(spec)
    _sys.modules[_name] = m   # 🐛 2026-09-01: 统一 sys.modules 注册 (dataclass 兜底)
    spec.loader.exec_module(m)
    _SS_MODS["gen_tactile"] = m
    return m


def _ss_env_obs(log):
    """真实采样: metaworld env (复用 YOLO env) → (obs39, img)"""
    import numpy as np
    aligner = _yolo_ensure_aligner(log)
    aligner.env._freeze_rand_vec = False
    aligner.env.reset(seed=0)
    aligner.env._freeze_rand_vec = True
    img = aligner.env.render()
    obs39 = np.asarray(aligner.env._get_obs(), dtype=np.float64).ravel()
    return obs39, img


def _ss_ensure_obs43(log):
    """真实 43D obs: metaworld 39D + 触觉合成 → fuse_sensors (perception.py), 缓存供下游"""
    import numpy as np
    if "obs43" in _SS_STATE:
        return _SS_STATE["obs43"]
    obs39, _img = _ss_env_obs(log)
    tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
    obs43 = _ss_import("perception").fuse_sensors(obs39, np.zeros(6), tac)
    _SS_STATE.update({"obs43": obs43, "obs39": obs39})
    return obs43


def node_ss_s1(ctx):
    """S1 时空感知前端 — 📡传感器融合: metaworld 采样 39D + 触觉合成 → fuse_sensors() → 43D (perception.py)
    🐛 2026-09-01 真实执行: 原 _ss_run 只打日志, perception.py 断点永不命中"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        if "状态向量" in name or "obs" in name.lower():
            obs43 = _ss_ensure_obs43(log)
            if log:
                log(f"🧩 43D obs (真实): 39D 视觉 [0:39] + 触觉4D [39:43] · "
                    f"grasp={obs43[39]:.3f} contact={obs43[40]:.3f} dir=({obs43[41]:.2f},{obs43[42]:.2f})")
            return True
        obs39, _img = _ss_env_obs(log)
        tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
        obs43 = _ss_import("perception").fuse_sensors(obs39, np.zeros(6), tac)
        _SS_STATE.update({"obs43": obs43, "obs39": obs39})
        if log:
            log(f"📡 传感器融合 (真实): 39D+触觉4D → 43D · hand={np.round(obs39[0:3],3)} "
                f"光模块={np.round(obs39[4:7],3)} hole={np.round(obs39[36:39],3)} · 触觉={np.round(tac,3)}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 传感器融合真实执行失败: {e}")
        return False


def node_ss_s2(ctx):
    """S2 并行处理层 — ⚡前馈加速器(FeedforwardAccelerator) / 🔮状态估计器(AdaptiveStateEstimator) (parallel.py)"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        par = _ss_import("parallel")
        obs43 = _ss_ensure_obs43(log)
        if "估计" in name:
            est = par.AdaptiveStateEstimator()
            act4 = np.concatenate([_SS_STATE.get("u_prev", np.zeros(3)), [0.0]])
            lat = _SS_STATE.get("latent", obs43[:4])
            latent_pred = est.predict(np.asarray(lat, dtype=float), act4)
            # 🐛 2026-09-02 老倪: 估计器必须预测+校正闭环 — 原只 predict 没 update,
            #   "自适应状态估计器"的卡尔曼校正(用观测 z_k 修正先验)根本没执行, 名不副实
            obs39 = _SS_STATE.get("obs39")
            if obs39 is None:
                obs39, _ = _ss_env_obs(log)
            z_k = np.concatenate([obs39[0:3], [obs39[3]]])   # 观测: 手位置 + 夹爪开度 (与 latent 同维)
            latent = est.update(np.asarray(latent_pred, dtype=float), np.asarray(z_k, dtype=float))
            _SS_STATE["latent"] = np.asarray(latent, dtype=float)
            if log:
                log(f"🔮 状态估计器 (真实): predict→{np.round(latent_pred,4)} · "
                    f"update(K·(z−x̂₋))→latent={np.round(latent,4)} (parallel.py AdaptiveStateEstimator)")
            return True
        accel = par.FeedforwardAccelerator()
        u_ff = accel.forward(obs43)
        _SS_STATE["u_ff"] = np.asarray(u_ff, dtype=float)
        _SS_STATE["ff_probe"] = accel.probe   # 🧠 探针缓存 (前馈激活直方图节点消费)
        if log:
            # 🧠 探针 (2026-09-04): 展示 MLP 在想什么 — 层活跃/能量 + 输出归因 top 单元
            _p = accel.probe
            if _p and "layers" in _p:
                _ls = _p["layers"]
                _act = " · ".join(f"L{i+1}:{l['active']}/{l['dim']}活 E={l['act_l2']:.1f}"
                                  for i, l in enumerate(_ls))
                _top = " · ".join(
                    f"u{d+1}←单元{j}({c:+.3f})" for d in range(3)
                    for j, c in _p["out_contrib"][d][:1])
                log(f"⚡ 前馈加速器 (真实): u_ff={np.round(u_ff,3)} · 🧠[{_act}] · 归因 {_top} "
                    f"(parallel.py; obs: 手{_p['obs']['hand']}→目标{_p['obs']['target']} d={_p['obs']['d_h']})")
            else:
                log(f"⚡ 前馈加速器 (真实): forward(obs43) → u_ff={np.round(u_ff,3)} (parallel.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 并行处理层真实执行失败: {e}")
        return False


_FF_HIST_WIN = None  # 🧠 前馈激活直方图窗口 (全局单实例, 主线程)
_FF_ATTR_WIN = None  # 🎯 归因分工窗口 (全局单实例)


def node_ss_ff_hist(ctx):
    """🧠 前馈激活直方图 — 读 ⚡前馈加速器探针 (ff_probe) → 三层 512 激活分布直方图
    引线: ⚡前馈加速器 → 本节点 (数据经 _SS_STATE['ff_probe'] 流通)"""
    log = ctx.get("log")
    try:
        probe = _SS_STATE.get("ff_probe")
        if not probe or "act_raw" not in probe:
            if log:
                log("🧠 前馈激活: 无探针数据 — 先运行 ⚡前馈加速器节点 (▶运行或单步)")
            return False
        global _FF_HIST_WIN
        _win = getattr(ctx.get("module"), "_ff_hist_win", None)   # 优先 module 侧单例 (双击同窗)
        if _win is None:
            if _FF_HIST_WIN is None:
                from ff_hist_view import FFHistView   # 同目录, 延迟 import (Qt 依赖)
                _FF_HIST_WIN = FFHistView()
            _win = _FF_HIST_WIN
            if ctx.get("module") is not None:
                try:
                    ctx["module"]._ff_hist_win = _win
                except Exception:
                    pass
        _FF_HIST_WIN = _win
        _win.push(probe)
        if not _win.isVisible():
            _win.show()
        _win.raise_()
        _win.activateWindow()
        if log:
            ls = probe.get("layers") or []
            _act = " · ".join(f"L{i+1}:{l.get('active', 0)}/512" for i, l in enumerate(ls))
            log(f"🧠 前馈激活直方图: 已更新 [{_act}] · u_ff={np.round(probe.get('u_ff', []), 3)} "
                f"(窗口: 三层激活分布, 0=ReLU截断)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 前馈激活直方图失败: {e}")
        return False


def node_ss_ff_attrib(ctx):
    """🎯 归因·分工 — ⚡前馈探针 → 归因堆叠图 (谁在指挥) + 512单元功能散点 (PCA/t-SNE)
    引线: ⚡前馈加速器 → 本节点"""
    log = ctx.get("log")
    try:
        probe = _SS_STATE.get("ff_probe")
        if not probe or "act_raw" not in probe:
            if log:
                log("🎯 归因分工: 无探针数据 — 先运行 ⚡前馈加速器节点")
            return False
        global _FF_ATTR_WIN
        _win = getattr(ctx.get("module"), "_ff_attr_win", None)   # 优先 module 侧单例 (双击同窗)
        if _win is None:
            if _FF_ATTR_WIN is None:
                from ff_attrib_view import FFAttribView   # 延迟 import (Qt 依赖)
                _FF_ATTR_WIN = FFAttribView()
            _win = _FF_ATTR_WIN
            if ctx.get("module") is not None:
                try:
                    ctx["module"]._ff_attr_win = _win
                except Exception:
                    pass
        _FF_ATTR_WIN = _win
        _win.push(probe)
        if not _win.isVisible():
            _win.show()
        _win.raise_()
        _win.activateWindow()
        if log:
            log("🎯 归因分工: 已更新 (堆叠=4维驱动能量 · 散点: 点 PCA 或 t-SNE 生成)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 归因分工失败: {e}")
        return False


def node_ss_dyn(ctx):
    """动力学预测-校正 — 📈先验动力学预测器(PriorDynamicsPredictor) / 🧪状态校正器(state_correction)"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        obs43 = _ss_ensure_obs43(log)
        act4 = np.concatenate([_SS_STATE.get("u_prev", np.zeros(3)), [0.0]])
        if "校正" in name:
            cog = _ss_import("cognition")
            prior = _SS_STATE.get("prior")
            if prior is None:
                dyn = _ss_import("dynamics")
                lat = _SS_STATE.get("latent", obs43[:4])
                prior = dyn.PriorDynamicsPredictor(A=1.0, B=0.02).predict(np.asarray(lat, dtype=float), act4)
                _SS_STATE["prior"] = np.asarray(prior, dtype=float)
            obs39 = _SS_STATE.get("obs39")
            if obs39 is None:
                obs39, _ = _ss_env_obs(log)
            tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
            z_k = np.concatenate([obs39[0:3], [tac[1]]])
            corrected, residual = cog.state_correction(np.asarray(prior, dtype=float), z_k, K=0.5)
            r = float(np.linalg.norm(residual))
            cp = float(cog.contact_probability(r, gain=8.0))
            _SS_STATE.update({"residual": np.asarray(residual, dtype=float), "contact_p": cp,
                              "corrected": np.asarray(corrected, dtype=float)})
            if log:
                log(f"🧪 状态校正器 (真实): state_correction(prior,z_k) → residual={np.round(residual,4)} · "
                    f"接触概率={cp:.3f} (cognition.py)")
            return True
        dyn = _ss_import("dynamics")
        lat = _SS_STATE.get("latent", obs43[:4])
        prior = dyn.PriorDynamicsPredictor(A=1.0, B=0.02).predict(np.asarray(lat, dtype=float), act4)
        _SS_STATE["prior"] = np.asarray(prior, dtype=float)
        if log:
            log(f"📈 先验动力学预测器 (真实): predict(latent,act) → next_obs={np.round(prior,4)} (dynamics.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 动力学预测-校正真实执行失败: {e}")
        return False


def node_ss_s3(ctx):
    """S3 认知决策层 — 🧭动作调制器(ActionModulator.decide 8阶段状态机) / 🛡安全执行边界(saturate)"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        if "边界" in name:
            u = _SS_STATE.get("u", np.zeros(4))
            u_sat = _ss_import("safety").saturate(np.asarray(u, dtype=float), limit=0.6)
            _SS_STATE["u_sat"] = np.asarray(u_sat, dtype=float)
            if log:
                log(f"🛡 安全执行边界 (真实): saturate(u={np.round(u,3)}, limit=0.6) → "
                    f"u_sat={np.round(u_sat,3)} (safety.py)")
            return True
        cog = _ss_import("cognition")
        u_ff = _SS_STATE.get("u_ff", np.zeros(4))
        cp = _SS_STATE.get("contact_p", 0.1)
        res = _SS_STATE.get("residual", np.zeros(4))
        r = float(np.linalg.norm(res))
        u_fb = np.concatenate([np.clip(0.5 * np.asarray(res, dtype=float)[:3], -0.5, 0.5), [0.0]])
        mod = cog.ActionModulator()
        u, stage = mod.decide(np.asarray(u_ff, dtype=float), u_fb, float(cp), r)
        if np.ndim(u) == 0:
            u = np.zeros(4)
        u = np.asarray(u, dtype=float).copy()
        u[3] = mod.gripper_cmd(u_ff[3])
        _SS_STATE.update({"u": u, "stage": stage})
        if log:
            log(f"🧭 动作调制器 (真实): decide(u_ff,u_fb,cp={cp:.2f},r={r:.3f}) → 阶段「{stage}」· "
                f"u={np.round(u,3)} (cognition.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 认知决策层真实执行失败: {e}")
        return False


def node_ss_exec(ctx):
    """执行层 — 🤖机器人执行器(RobotExecutor.execute) / 🌍物理世界(PhysicalWorld 质量/惯量)"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        ex = _ss_import("execution")
        if "物理" in name:
            w = ex.PhysicalWorld()
            _SS_STATE["world"] = w
            if log:
                try:
                    gm = np.asarray(w.generalized_mass())
                    gd = np.round(np.diag(gm)[:4], 3) if gm.ndim == 2 and gm.shape[0] == gm.shape[1] else np.round(gm.ravel()[:4], 3)
                except Exception:
                    gd = "?"
                log(f"🌍 物理世界 (真实): total_mass={w.total_mass}kg · 广义质量≈{gd} · "
                    f"7自由度 (execution.py)")
            return True
        u_sat = _SS_STATE.get("u_sat", np.zeros(4))
        u_vec = ex.RobotExecutor().execute(np.asarray(u_sat, dtype=float))
        if np.ndim(u_vec) == 0:
            u_vec = np.zeros(4)
        _SS_STATE["u_prev"] = np.asarray(u_vec, dtype=float)[:3]
        if log:
            log(f"🤖 机器人执行器 (真实): execute(u_sat={np.round(u_sat,3)}) → 指令={np.round(u_vec,4)} "
                f"(execution.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 执行层真实执行失败: {e}")
        return False


def node_ss_video(ctx):
    """🎥 操作视频 — 双击打开 metaworld 训练后 rollout 视频对比窗口 (多模型同步播放)"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    if label == "▶运行":
        # 🐛 2026-09-01 老倪: ▶运行动画播放中不自动弹窗 — 弹窗置顶(_show_nonmodal) +
        #   断点暂停时主线程冻结 → 窗口关不掉 + "studio.py is not responding"; 双击才弹
        log = ctx.get("log")
        if log:
            log("🎥 操作视频: 运行模式跳过弹窗 — 双击节点打开")
        return True
    if module and hasattr(module, "on_infer_video"):
        module.on_infer_video()
    return True


def node_ss_3d_view(ctx):
    """🧭 3D 视图 — 打开 Apollo 风格 3D 分层视图 (可视化层观察器, 源=物理世界)
    ▶运行 模式跳过弹窗 (同操作视频); 双击/右键运行 → 打开/置顶 3D 窗口"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    log = ctx.get("log")
    if label == "▶运行":
        if log:
            log("🧭 3D 视图: 运行模式跳过弹窗 — 双击节点打开 (防断点冻结关不掉)")
        return True
    if module and hasattr(module, "open_ss_3d"):
        module.open_ss_3d()
        if log:
            log("🧭 3D 视图: 已打开 (Apollo 风格分层视图, 与引擎/画布同源)")
        return True
    if log:
        log("⚠️ 3D 视图: 无 module 上下文 (仅画布内双击/右键运行可用)")
    return False


def node_ss_scope(ctx):
    """📊 仿真波形 — 双击显示最近一次状态空间仿真波形 (距离/残差/接触概率 + 阶段切换)"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    if label == "▶运行":
        # 🐛 2026-09-01 老倪: 同 node_ss_video — 运行模式不弹窗, 双击节点才打开
        log = ctx.get("log")
        if log:
            log("📊 仿真波形: 运行模式跳过弹窗 — 双击节点查看")
        return True
    if module and hasattr(module, "show_state_space_scope"):
        module.show_state_space_scope()
    return True


# 外部源码位置: 语义key → (绝对路径, 行号兜底, 真实符号名)
_EXTERNAL_LOC["ss_bg1"]    = (os.path.join(_SS_DIR, "perception.py"), 20, "def fuse_sensors")
_EXTERNAL_LOC["ss_sensor"] = (os.path.join(_SS_DIR, "perception.py"), 20, "def fuse_sensors")
_EXTERNAL_LOC["ss_obs"]    = (os.path.join(_SS_DIR, "perception.py"), 20, "def fuse_sensors")
_EXTERNAL_LOC["ss_bg2"]    = (os.path.join(_SS_DIR, "parallel.py"), 71, "class FeedforwardAccelerator")  # 行号动态定位(符号名), 手写值仅回退
_EXTERNAL_LOC["ss_ff"]     = (os.path.join(_SS_DIR, "parallel.py"), 71, "class FeedforwardAccelerator")
_EXTERNAL_LOC["ss_est"]    = (os.path.join(_SS_DIR, "parallel.py"), 128, "class AdaptiveStateEstimator")  # 🐛 2026-09-04: 45→128 (重写后漂移; 现按符号动态定位)
_EXTERNAL_LOC["ss_pred"]   = (os.path.join(_SS_DIR, "dynamics.py"), 14, "class PriorDynamicsPredictor")
_EXTERNAL_LOC["ss_correct"] = (os.path.join(_SS_DIR, "cognition.py"), 17, "def state_correction")
_EXTERNAL_LOC["ss_bg3"]    = (os.path.join(_SS_DIR, "cognition.py"), 30, "class ActionModulator")
# 🐛 2026-09-02 老倪: 动作调制器节点双击 → 直接显示 decide 方法本体 (否决权+前馈反馈相加+阶段限速),
#   不是整个类 (原映射 class 行号 27 也不准, 实际 30)
_EXTERNAL_LOC["ss_sched"]  = (os.path.join(_SS_DIR, "cognition.py"), 167, "def decide")
_EXTERNAL_LOC["ss_limit"]  = (os.path.join(_SS_DIR, "safety.py"), 17, "def saturate")
_EXTERNAL_LOC["ss_bg4"]    = (os.path.join(_SS_DIR, "execution.py"), 14, "class RobotExecutor")
_EXTERNAL_LOC["ss_act"]    = (os.path.join(_SS_DIR, "execution.py"), 14, "class RobotExecutor")
_EXTERNAL_LOC["ss_world"]  = (os.path.join(_SS_DIR, "execution.py"), 25, "class PhysicalWorld")

# 🧮 标定层 (2026-09-02): 与 datasets/policies 同级别 — src/lerobot/calibration/calibration_layer.py
_CALIB_DIR_LOC = os.path.join(_REPO_ROOT, "src", "lerobot", "calibration")
_EXTERNAL_LOC["ss_calib"] = (os.path.join(_CALIB_DIR_LOC, "calibration_layer.py"), 73, "class CalibrationLayer")

# 📦 metaworld 数据源 (2026-09-02 老倪: 数据源节点必须接 lerobot 框架数据层 —
#   与感知/决策节点同构: 右键打开 + VSCode 断点进 datasets 真实源码,
#   不再是 tools/gui/node_logic.py 的控制台模板)
# 🐛 2026-09-02: line 必须指向第一行实际代码 (61, root=...), 不是 def 行(54) —
#   debugpy 对 def/docstring 行断点不命中 (函数第一条语句是 docstring), 踩过
_EXTERNAL_LOC["data"] = (os.path.join(_REPO_ROOT, "src", "lerobot", "datasets",
                                      "metaworld_data_source.py"), 54, "def probe_data_source")

_reg("ss_bg1",   ["时空感知前端"], "S1 时空感知前端 — 传感器融合 → 43D obs (源码 state_space/perception.py)", node_ss_s1)
_reg("ss_sensor", ["传感器融合"], "📡 传感器融合 — RGB-D+力觉+触觉 → 43D obs (源码 perception.py fuse_sensors)", node_ss_s1)
_reg("ss_obs",   ["43D", "统一状态向量"], "🧩 43D 统一状态向量 — 39D 视觉结构 + 触觉 4D (源码 perception.py)", node_ss_s1)
_reg("ss_bg2",   ["并行处理层"], "S2 并行处理层 — 快慢分离 (源码 state_space/parallel.py)", node_ss_s2)
_reg("ss_ff",    ["前馈加速器"], "⚡ 前馈加速器 — 快路径 obs→u_ff 建议 (权重 30%, 源码 parallel.py FeedforwardAccelerator)", node_ss_s2)
_reg("ss_est",   ["自适应状态估计器"], "🔮 自适应状态估计器 — 慢路径 递归潜状态+卡尔曼预测-校正 (源码 parallel.py AdaptiveStateEstimator)", node_ss_s2)
_reg("ss_ff_hist", ["前馈激活", "激活直方图"], "🧠 前馈激活直方图 — 读 ⚡前馈加速器探针, 三层512激活分布 (稀疏/能量/ReLU截断, 引线 S2→本节点)", node_ss_ff_hist)
_reg("ss_ff_attrib", ["归因", "分工", "堆叠", "t-SNE"], "🎯 归因·分工 — 512单元按输出维分工: 归因堆叠图(谁在指挥)+单元功能散点(PCA/t-SNE, 引线 S2→本节点)", node_ss_ff_attrib)
_reg("ss_pred",  ["先验动力学"], "📈 先验动力学预测器 — x̂ₖ₋=A·x̂ₖ₋₁+B·uₖ 预测 next_obs (源码 dynamics.py)", node_ss_dyn)
_reg("ss_correct", ["状态校正器"], "🧪 状态校正器 — 残差 r = z_k−ĥ(x̂ₖ₋) & 接触概率 → 卡尔曼校正 (源码 cognition.py state_correction)", node_ss_dyn)
_reg("ss_bg3",   ["认知决策层"], "S3 认知决策层 — 调度器握否决权 (源码 state_space/cognition.py)", node_ss_s3)
_reg("ss_sched", ["动作调制器"], "🧭 动作调制器 — 8阶段状态机(接近→对位→下降→抓取→抬起→转移→插入→完成, 与操作视频状态机同构) + 否决权 + 夹持锁存 + 按阶段融合 (源码 cognition.py ActionModulator)", node_ss_s3)
_reg("ss_limit", ["安全执行边界"], "🛡 安全执行边界 — 饱和限幅 (速度/力/位置上限, 源码 safety.py saturate)", node_ss_s3)
_reg("ss_bg4",   ["物理闭环"], "执行层 · 物理闭环 — 执行器→物理世界→z_k 反馈 (源码 state_space/execution.py)", node_ss_exec)
_reg("ss_act",   ["机器人执行器"], "🤖 机器人执行器 — 机械臂/夹爪接收物理指令执行 (源码 execution.py RobotExecutor)", node_ss_exec)
_reg("ss_world", ["物理世界"], "🌍 物理世界 — 执行结果→传感器反馈 z_k→卡尔曼校正闭环 (源码 execution.py PhysicalWorld)", node_ss_exec)
_reg("ss_video", ["操作视频"], "🎥 操作视频 — metaworld 训练后 rollout 视频对比窗口 (多模型同步播放, InferenceVideoDialog)", node_ss_video)
_reg("ss_scope", ["仿真波形"], "📊 仿真波形 — 最近一次状态空间仿真波形 (距离/前馈/残差/接触概率 + 阶段切换标注)", node_ss_scope)
_reg("ss_3d_view", ["3D 视图"], "🧭 3D 视图 — Apollo 风格 3D 分层视图 (与引擎/画布同源, 可视化层观察器; 源=物理世界)", node_ss_3d_view)


# ════════════════════════════════════════════════════════════════
# 🧠 大模型层 · 云端任务规划 (2026-08-20 老倪: 大模型管"想", 小模型管"动")
#   真实实现: src/lerobot/policies/left_right/state_space/planner.py
#   慢决策: 只在任务开始/异常时介入, 不进实时控制回路
# ════════════════════════════════════════════════════════════════
_EXTERNAL_LOC["ss_bg5"]    = (os.path.join(_SS_DIR, "planner.py"), 94, "class TaskPlanner")  # 🐛 2026-09-02: sym 误写路径字符串, 非符号
_EXTERNAL_LOC["ss_llm_in"] = (os.path.join(_SS_DIR, "planner.py"), 94, "class TaskPlanner")
_EXTERNAL_LOC["ss_llm"]    = (os.path.join(_SS_DIR, "planner.py"), 94, "class TaskPlanner")
_EXTERNAL_LOC["ss_reason"] = (os.path.join(_SS_DIR, "planner.py"), 196, "class ExceptionReasoner")
_EXTERNAL_LOC["ss_skill"]  = (os.path.join(_SS_DIR, "planner.py"), 246, "class SkillComposer")


def node_ss_llm(ctx):
    """🧠 任务规划器 — 指令 → 技能Token序列 → 下发状态机 (慢决策, 回路外; 双击=规划演示)"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        path = os.path.join(_SS_DIR, "planner.py")
        spec = _ilu.spec_from_file_location("state_space.planner", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        p = m.TaskPlanner()
        ins = (ctx.get("params") or {}).get("instruction", "插入光模块")
        tokens = p.plan(ins)
        names = []
        for t in tokens:
            for s in p.skills.values():
                if s["tokens"]["id"] == t:
                    names.append(s["name"])
                    break
        if log:
            log(f"🧠 任务规划器: 「{ins}」 → 技能序列 (共 {len(tokens)} 步)")
            for i, (t, nm) in enumerate(zip(tokens, names), 1):
                log(f"   {i}. {t}  {nm}")
            log(f"   📚 Token 序列已下发 🧭动作调制器 (慢决策 · 回路外, 状态机握否决权)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 任务规划器演示失败: {e}")
        return False


def node_ss_reason(ctx):
    """🔍 异常推理器 — 连续否决/阶段卡死 → 异常分类 + 恢复建议 (双击=诊断演示)"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        path = os.path.join(_SS_DIR, "planner.py")
        spec = _ilu.spec_from_file_location("state_space.planner", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        r = m.ExceptionReasoner()
        p = ctx.get("params") or {}
        kind, advice = r.diagnose(
            stage=p.get("stage", "接近"),
            residual=float(p.get("residual", 0.0)),
            contact_p=float(p.get("contact_p", 0.5)),
            dist_h=float(p.get("dist_h", 0.05)),
            dwell_time=float(p.get("dwell_time", 0.0)),
            veto_count=int(p.get("veto_count", 0)),
            max_veto=int(p.get("max_veto", 3)))
        if log:
            log(f"🔍 异常推理器: 阶段={p.get('stage','接近')} 残差={p.get('residual',0.0)} "
                f"接触概率={p.get('contact_p',0.5)}")
            log(f"   → 诊断: {kind or '运行正常'} | {advice}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 异常推理器演示失败: {e}")
        return False


def node_ss_skill(ctx):
    """🛠 技能编排器 — 新型号规格 → 新技能序列 + 力阈值/节拍 (双击=编排演示)"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        path = os.path.join(_SS_DIR, "planner.py")
        spec = _ilu.spec_from_file_location("state_space.planner", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        c = m.SkillComposer()
        spec_text = (ctx.get("params") or {}).get("spec", "新型 OSFP 光模块, 高插入力")
        out = c.compose(spec_text)
        if log:
            log(f"🛠 技能编排器: 规格「{spec_text}」")
            for i, t in enumerate(out["sequence"], 1):
                log(f"   {i}. {t}")
            pr = out["params"]
            log(f"   ⚙ 参数: 力阈值 {pr.get('force_limit')}N · 节拍 {pr.get('tact_time')}s · "
                f"插入深度 {pr.get('insert_depth')}m")
            log(f"   📚 新技能序列已注册进 🧠任务规划器技能库")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 技能编排器演示失败: {e}")
        return False


def node_ss_bg5(ctx):
    """大模型层背景行 — 云端任务规划 (慢决策 · 回路外)"""
    log = ctx.get("log")
    if log:
        log(f"🧠 大模型层 (背景): 任务规划/异常推理/技能编排 — 慢决策回路外 (planner.py)")
    return True


def node_ss_llm_in(ctx):
    """📝 任务指令 — MES 工单 / 自然语言指令输入 → 真实下发 TaskPlanner (planner.py)"""
    log = ctx.get("log")
    try:
        ins = (ctx.get("params") or {}).get("instruction", "插入光模块")
        _SS_STATE["instruction"] = ins
        if log:
            log(f"📝 任务指令 (真实): 「{ins}」 → 已下发 🧠任务规划器 (planner.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 任务指令处理失败: {e}")
        return False


_reg("ss_bg5",   ["大模型层"], "大模型层 · 云端任务规划 — 慢决策, 回路外; 指令→技能Token→状态机 (源码 planner.py)", node_ss_bg5)
_reg("ss_llm_in", ["任务指令"], "📝 任务指令 — MES 工单/自然语言 → 任务规划器 (源码 planner.py)", node_ss_llm_in)
_reg("ss_llm",   ["任务规划器"], "🧠 任务规划器 — 指令→技能Token序列 (242条原子技能, 规则校验) → 状态机; 双击=规划演示 (源码 planner.py TaskPlanner)", node_ss_llm)
_reg("ss_reason", ["异常推理器"], "🔍 异常推理器 — 连续否决/阶段卡死→异常分类+恢复建议; 双击=诊断演示 (源码 planner.py ExceptionReasoner)", node_ss_reason)
_reg("ss_skill", ["技能编排器"], "🛠 技能编排器 — 新型号规格→新技能序列+力阈值/节拍; 双击=编排演示 (源码 planner.py SkillComposer)", node_ss_skill)


# ════════════════════════════════════════════════════════════════
# 🎯 YOLO 目标检测 — 检测目标清单 (2026-08-20 老倪: 需求说明书 → 22 目标 6 类)
#   数据源: flows/detection_targets.json · 导出: yolo_3d/detection_targets.py
# ════════════════════════════════════════════════════════════════
_EXTERNAL_LOC["ss_yolo"] = (os.path.join(_YOLO_DIR, "yolo_state_aligner.py"), 37, "class YoloStateAligner")


def node_ss_yolo(ctx):
    """🎯 YOLO 目标检测 — 真实执行: metaworld 渲染帧 → YOLO detect_3d → align() 替换 39D 段
    源码: yolo_state_aligner.py (YoloStateAligner / detect_3d / align) — 右键源码与真实执行同源, 断点可进
    🐛 2026-09-01: 原执行 detection_targets.py 清单(≠右键源码 yolo_state_aligner.py) → 断点永不命中"""
    log = ctx.get("log")
    try:
        import numpy as np
        aligner = _yolo_ensure_aligner(log)
        det3d, obs39, _img = _yolo_capture(log, aligner)
        aligned = aligner.align(obs39, det3d)
        _YOLO_CACHE["aligned39"] = aligned
        if log:
            n = len(det3d)
            det2d = _YOLO_CACHE.get("det2d", {})
            desc = " ".join(
                f"{k}=[{v[0]:.3f},{v[1]:.3f},{v[2]:.3f}]"
                + (f" conf={det2d[k]['conf']:.2f}" if k in det2d else "")
                for k, v in sorted(det3d.items()))
            log(f"🎯 YOLO 目标检测 (真实): {n}/3 目标 · {desc}")
            log(f"   39D 对齐 (align 真实执行): hand={np.round(aligned[0:3],3)} · "
                f"光模块={np.round(aligned[4:7],3)} · hole={np.round(aligned[36:39],3)}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ YOLO 目标检测真实执行失败: {e}")
        return False


_reg("ss_yolo", ["YOLO", "目标检测"],
     "🎯 YOLO 目标检测 — 真实执行: YOLO detect_3d + align 替换 39D 段 (源码 yolo_state_aligner.py; 双击=清单, 📥按钮=Excel导出)",
     node_ss_yolo)


def node_ss_aoi(ctx):
    """🔍 外观质量检测 — 真实执行: 目标帧 → quality_check.py AOIQualityChecker 图像处理缺陷检测
    源码: yolo_3d/quality_check.py (AOIQualityChecker.check) — 右键源码与真实执行同源, 断点可进
    🐛 2026-09-02: 原只加载 detection_targets.json 清单 (无实际检测) → 改为真实帧图像处理检测"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        qc_path = os.path.join(_YOLO_DIR, "quality_check.py")
        spec = _ilu.spec_from_file_location("yolo_3d.quality_check", qc_path)
        qc = _ilu.module_from_spec(spec)
        spec.loader.exec_module(qc)
        # 目标帧: 优先用 YOLO 节点缓存帧, 无则同源采样一帧 (与 node_ss_yolo 一致)
        img = _YOLO_CACHE.get("img")
        if img is None:
            aligner = _yolo_ensure_aligner(log)
            _, _, img = _yolo_capture(log, aligner)
        checker = qc.AOIQualityChecker()
        res = checker.check(img)
        _YOLO_CACHE["aoi"] = res
        if log:
            for it in res.get("items", []):
                v = it["value"] if it["value"] is not None else it.get("note", "—")
                log(f"🔍 {it['target_id']} {it['defect']}: {v} (判据 {it['threshold']}) → "
                    f"{'✅' if it['pass'] else '❌'}")
            log(f"🔍 外观质量检测 (真实图像处理): {qc.summarize(res)} (quality_check.py)")
        return bool(res.get("pass"))
    except Exception as e:
        if log:
            log(f"⚠️ 外观质量检测真实执行失败: {e}")
        return False


_reg("ss_aoi", ["外观质量检测"],
     "🔍 外观质量检测 — 真实执行: 目标帧 → quality_check.py 图像处理缺陷检测 (DET-AOI-01~04; 双击=源码, 📥按钮=Excel导出清单)",
     node_ss_aoi)


# 🧮 标定层 (2026-09-02 老倪: Drifting Models 思想 — 引力/斥力二分 + 平衡点; 回路外元层)
_CALIB_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "calibration")


def node_ss_calib(ctx):
    """🧮 标定层 — 引力(快速动作)/斥力(状态预测) 二分超参数 + 平衡点
    源码: src/lerobot/calibration/calibration_layer.py (CalibrationLayer) — 与 datasets/policies 同级别
    回路外元层: 收集/展示标定参数, 不参与引擎推理, 不改变拓扑/流程/架构"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        import numpy as np
        path = os.path.join(_CALIB_DIR, "calibration_layer.py")
        spec = _ilu.spec_from_file_location("lerobot.calibration.calibration_layer", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        layer = m.CalibrationLayer()
        # 当前运行状态: 画布播放中从 module._ss_tr 取当前步 (与 _ss_tick idx 同映射)
        mod = ctx.get("module")
        stage, speed, residual, contact_p = "接近", 0.0, 0.0, 0.0
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is not None and tr.get("x") is not None and len(tr["x"]) > 0:
            idx = int(min(getattr(mod, "_ss_round", 0), len(tr["t"]) - 1))
            stage = str(tr["stage"][idx]).replace("阶段 ", "")
            # 🐛 2026-09-03: tr["u_sat"] 存的是标量范数 (float), 不是向量 —
            #   [:3] 索引 0-d 数组抛 "too many indices" (既有 bug, 被 try 吞)
            _us = tr["u_sat"][idx] if "u_sat" in tr else tr.get("u_sat_vec", [0])[idx]
            speed = float(np.linalg.norm(np.asarray(_us, dtype=float)) )
            residual = float(tr["residual"][idx])
            contact_p = float(tr["contact_p"][idx])
        gap = layer.equilibrium_gap(stage, speed, residual, contact_p)
        _SS_STATE["calib"] = {"layer": layer, "stage": stage, "gap": gap,
                              "attr": layer.attr, "rep": layer.rep, "lat": layer.lat}
        if log:
            log(f"🧮 标定层 (真实): {layer.summarize(stage, speed, residual, contact_p)}")
            log(f"   引力标定 (快速动作): Kp={layer.attr['Kp']} · 当前阶段速度上限 "
                f"{layer.attr['stage_v_cap'].get(stage, '—')} m/s")
            log(f"   斥力标定 (状态预测): K_kalman={layer.rep['K_kalman']} · 残差EMA={layer.rep['res_ema']} · "
                f"接触增益={layer.rep['contact_gain']} · 否决阈值={layer.rep['veto_th']}")
            log(f"   {layer.latent_summary()}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 标定层执行失败: {e}")
        return False


_reg("ss_calib", ["标定层"],
     "🧮 标定层 — 引力(快速动作: Kp+阶段速度上限/下限) vs 斥力(状态预测: K_kalman+残差EMA+接触增益+否决阈值), 平衡偏差=|引力势−斥力势| (Drifting Models 反称场; 源码 calibration_layer.py)",
     node_ss_calib)


def node_ss_lat(ctx):
    """🧮 潜空间 — 世界模型预测流形的标定 (维度/类别/速度场) + 观测有效维实测
    源码: src/lerobot/calibration/calibration_layer.py (LATENT_CALIB)
    地图导航视角: 潜空间=流形地图, 世界模型=导航仪 (沿速度场 prior A·x+B·u 推演);
    本节点 = 地图的几何标定 + 引擎校验: 对引擎轨迹 39D 观测做 PCA → 95% 方差有效维
    (数据流形固有维实测) vs 标定 latent_dim; 潜坐标/速度场向量取引擎真实 latent/prior。
    ⚠️ 维度/类别是引擎结构常数, 本节点只标定+校验, 不写引擎字面量 (改潜维=重构卡尔曼)。"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        import numpy as np
        path = os.path.join(_CALIB_DIR, "calibration_layer.py")
        spec = _ilu.spec_from_file_location("lerobot.calibration.calibration_layer", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        layer = m.CalibrationLayer()
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            if log:
                log("⚠️ 潜空间: 无引擎轨迹 — 先点 ▶ 运行状态空间 (轨迹是数据真源)")
            return False
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        stage = str(tr["stage"][idx]).replace("阶段 ", "")
        # ── 潜坐标 (地图位置) + 速度场 (世界模型一步推演) — 引擎真实量 ──
        lat = np.asarray(tr.get("corrected_vec", tr["latent_vec"])[idx], dtype=float)
        lat_pred = np.asarray(tr["latent_vec"][idx], dtype=float)      # 估计器先验
        prior = np.asarray(tr.get("prior_vec", np.zeros(4))[idx], dtype=float)
        vel = prior - lat_pred                                          # 地图上速度场向量
        # ── 观测流形有效维实测: 全轨迹 39D 视觉观测 PCA (95% 累积方差) ──
        obs_all = np.asarray(tr["obs"], dtype=float)[:, :39]
        X = obs_all - obs_all.mean(axis=0)
        _, S, _ = np.linalg.svd(X, full_matrices=False)
        var = S ** 2 / max(float((S ** 2).sum()), 1e-12)
        cum = np.cumsum(var)
        eff_dim = int(np.searchsorted(cum, 0.95) + 1) if len(cum) else 0
        eff_dim99 = int(np.searchsorted(cum, 0.99) + 1) if len(cum) else 0
        # ── 校验: 标定陈述 vs 引擎实测 ──
        checks = []
        checks.append(f"标定潜维 {layer.lat['latent_dim']}D vs 引擎潜状态实际 {lat.size}D"
                      + (" ✓" if layer.lat["latent_dim"] == lat.size else " ✗ 标定过期"))
        checks.append(f"观测流形 {layer.lat['state_dim']}D → 轨迹有效维 {eff_dim}D@95% / "
                      f"{eff_dim99}D@99% (任务路径低维嵌入: 沿路径推进+夹爪; "
                      f"孔位/姿态常量维无方差)")
        _SS_STATE["latent_calib"] = {"idx": idx, "stage": stage, "latent": lat,
                                     "prior": prior, "vel": vel,
                                     "eff_dim": eff_dim, "eff_dim99": eff_dim99,
                                     "lat": dict(layer.lat)}
        if log:
            log(f"🧮 潜空间 (真实·t={tr['t'][idx]:.2f}s {stage}): 潜坐标 (位置3+预测力1)="
                f"{np.round(lat, 4)}")
            log(f"   速度场 (世界模型一步推演 prior−x̂₋): {np.round(vel, 4)} · "
                f"A={layer.lat['prior_A']:.1f} 恒速线性流形 ({layer.lat['flow_kind']})")
            log(f"   PCA 校验: " + " · ".join(checks))
            log(f"   标定: {layer.latent_summary()}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 潜空间执行失败: {e}")
        return False


_reg("ss_lat", ["潜空间"],
    "🧮 潜空间 — 世界模型预测流形标定: 维度(latent_dim 4D=位置3+预测力1)/类别(manifold_kind flat-linear, flow_kind const-vel)/速度场 prior_A; PCA 实测观测有效维 vs 标定; 潜坐标+速度场取引擎轨迹真实量 (地图导航视角; 源码 calibration_layer.py LATENT_CALIB)",
    node_ss_lat)
_EXTERNAL_LOC["ss_lat"] = (os.path.join(_CALIB_DIR_LOC, "calibration_layer.py"), 58, "LATENT_CALIB")


# 🧮 流形层 (2026-09-03 老倪: 光模块精密插拔 = 高维状态空间的低维流形 —
#   接触流形=插拔安全通道(沿流形推进=测地线, 偏离→引脚弯曲), 性能流形=光耦合
#   对准代价/效率曲面. 回路外几何分析元层, 与标定层同款: 不参与推理/不加安全通道)
_MANIFOLD_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "manifold")


def node_ss_mani(ctx):
    """🧮 流形层 — 接触流形 (插拔通道: 切向进度/法向偏离/V) ‖ 性能流形 (对准代价 V_p/η)
    源码: src/lerobot/manifold/manifold_layer.py (ContactManifold / PerformanceManifold)
    回路外元层: 从引擎轨迹当前帧取真实量 (obs/peg_head/target/v/stage) 实算,
    断点可进; 不参与推理, 不新增安全通道 (唯一三层安全=否决+限幅+Sys0)"""
    log = ctx.get("log")
    try:
        import importlib.util as _ilu
        import numpy as np
        path = os.path.join(_MANIFOLD_DIR, "manifold_layer.py")
        spec = _ilu.spec_from_file_location("lerobot.manifold.manifold_layer", path)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        name = ctx.get("name", "")
        # 当前运行状态: 画布播放中从 module._ss_tr 取当前步 (与 node_ss_calib 同映射)
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            if log:
                log("⚠️ 流形层: 无引擎轨迹 — 先点 ▶ 运行状态空间 (轨迹是数据真源)")
            return False
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        stage = str(tr["stage"][idx]).replace("阶段 ", "")
        hand = np.asarray(tr["x"][idx], dtype=float)
        peg_head = np.asarray(tr["peg_head"][idx], dtype=float)
        target = np.asarray(tr["target"][idx], dtype=float)
        v = np.asarray(tr["v_vec"][idx], dtype=float) if tr.get("v_vec") else np.zeros(3)
        _SS_STATE["mani_frame"] = {"idx": idx, "stage": stage}
        if "接触" in name:
            cm = m.ContactManifold()
            r = cm.decompose(hand, peg_head, target, v, stage)
            _SS_STATE["contact_mani"] = r
            if log:
                log(f"🧮 接触流形 (真实·t={tr['t'][idx]:.2f}s {stage}): {cm.summarize(r)}")
                if r["axis"] is not None:
                    log(f"   通道轴 â={np.round(r['axis'],3)} · 切向进度 "
                        f"‖e∥‖={r['progress']:.4f}m · 法向偏离 ‖e⊥‖={r['risk']:.4f}m "
                        f"(阈 {r['risk_th']}m) · V̇={r['Vdot']:.3e} (负=沿测地线收敛)")
                else:
                    log(f"   自由空间 (转移段无接触约束) · ‖e‖={r['progress']:.4f}m · "
                        f"V̇={r['Vdot']:.3e}")
            return True
        if "性能" in name:
            pm = m.PerformanceManifold()
            r = pm.evaluate(peg_head, stage=stage)
            _SS_STATE["perf_mani"] = r
            if log:
                log(f"🧮 性能流形 (真实·t={tr['t'][idx]:.2f}s {stage}): {pm.summarize(r)}")
                log(f"   修正方向 ∇V_p={np.round(r['grad'],4)} (最优对准 = 沿 −∇ 下山到 δ→0)")
            return True
        if log:
            log("⚠️ 流形层: 节点名未识别接触/性能分派")
        return False
    except Exception as e:
        if log:
            log(f"⚠️ 流形层执行失败: {e}")
        return False


_reg("ss_mani_c", ["接触流形"],
    "🧮 接触流形 — 插拔安全通道: 误差 e 沿通道轴分解 → 切向 e∥(测地线进度)/法向 e⊥(离流形漂移, 弯曲风险), V=½‖e‖², V̇=−e·v (源码 manifold_layer.py ContactManifold)",
    node_ss_mani)
_reg("ss_mani_p", ["性能流形"],
    "🧮 性能流形 — 光耦合对准代价: δ=光模块头−孔底 → V_p=½δᵀWδ, 估计耦合效率 η=exp(−V_p/σ²), ∇V_p 最优对准方向 (高斯近似; 源码 manifold_layer.py PerformanceManifold)",
    node_ss_mani)

# 右键源码映射: 两 key 各挂独立符号 (防"两节点显示同一段"坑)
_EXTERNAL_LOC["ss_mani_c"] = (os.path.join(_MANIFOLD_DIR, "manifold_layer.py"), 65, "class ContactManifold")
_EXTERNAL_LOC["ss_mani_p"] = (os.path.join(_MANIFOLD_DIR, "manifold_layer.py"), 138, "class PerformanceManifold")


# 🧩 验证层 (2026-09-03 老倪: 状态空间系统 feature list + test cases 汇总执行 —
#   回路外元层, 与标定层/流形导航层同范式; 真源 src/lerobot/verification/verification_layer.py)
_VERIF_DIR = os.path.join(_REPO_ROOT, "src", "lerobot", "verification")


def _verif_mod():
    """懒加载验证层真源模块 (importlib 直载, 同标定/流形策略)"""
    import importlib.util as _ilu
    path = os.path.join(_VERIF_DIR, "verification_layer.py")
    spec = _ilu.spec_from_file_location("lerobot.verification.verification_layer", path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def node_ss_feature(ctx):
    """🧩 Feature 功能清单 — 汇总状态空间系统全部 feature (自动/手动标注)
    源码: src/lerobot/verification/verification_layer.py (FEATURES 注册表)
    真实执行: 引擎跑一次 + 逐 feature 打印 (含 GUI 手动项提示)"""
    log = ctx.get("log")
    try:
        mod = _verif_mod()
        v = mod.VerificationLayer()
        v.list_features()
        # 引擎快跑一次 (验证层数据真源预热, 断点可进 StateSpaceSim)
        _ = v.engine()
        if log:
            log("🧩 Feature 清单已汇总 (见上方) · 自动项可点「🧪 Test 用例执行」逐个跑")
        _SS_STATE["verif"] = {"features": mod.FEATURES}
        return True
    except Exception as e:
        if log:
            log(f"⚠️ Feature 清单执行失败: {e}")
        return False


def node_ss_test(ctx):
    """🧪 Test 用例执行 — 跑验证层全部自动化 test (PASS/FAIL + 数值证据)
    源码: src/lerobot/verification/verification_layer.py (t_F_* 断言)
    单跑: ZMAX_VERIF_ONLY=F-A01 环境变量; 跳过慢 YOLO: ZMAX_VERIF_SKIP_SLOW=1"""
    log = ctx.get("log")
    try:
        v = _verif_mod().VerificationLayer()
        only = os.environ.get("ZMAX_VERIF_ONLY")
        skip_slow = os.environ.get("ZMAX_VERIF_SKIP_SLOW") == "1"
        if only:
            ok, _d = v.run(only)
            return bool(ok)
        ok = v.run_all(skip_slow=skip_slow)
        return ok
    except Exception as e:
        if log:
            log(f"⚠️ Test 用例执行失败: {e}")
        return False


_reg("ss_feature", ["Feature"],
    "🧩 Feature 功能清单 — 状态空间系统全部 feature 汇总 (引擎/六层/感知链/规划/元层/画布, 含 GUI 手动项; 源码 verification_layer.py FEATURES)",
    node_ss_feature)
_reg("ss_test", ["Test"],
    "🧪 Test 用例执行 — 验证层自动化 test 套件全跑 (F-A01~F-F04, PASS/FAIL+数值证据; 源码 verification_layer.py t_F_* 断言, 断点可进)",
    node_ss_test)
_EXTERNAL_LOC["ss_feature"] = (os.path.join(_VERIF_DIR, "verification_layer.py"), 47, "FEATURES = [")
_EXTERNAL_LOC["ss_test"] = (os.path.join(_VERIF_DIR, "verification_layer.py"), 97, "class VerificationLayer")
