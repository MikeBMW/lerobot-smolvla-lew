# -*- coding: utf-8 -*-
"""节点源码定位 / 编辑 / 恢复 (sourceview) —— 控制台「查看逻辑 / 改逻辑 / 恢复默认」的后端。

搬运自 tools/gui/node_logic.py (2026-09-28), 行为逐字保留; 路径口径改成包内唯一真源:
  · 逻辑默认位置 = 该 key 注册函数所在的**真实文件** (`fn.__code__.co_filename`, 现在在 nodes/ 下)
  · 外部符号覆盖 = `_EXTERNAL_LOC` (在 nodes/library.py 里维护, 这里通过注册表命名空间读)
  · 用户修改 = `_SOURCE_CACHE` 原地替换 (热生效), 「恢复默认」读回真实文件
"""
import importlib
import inspect
import os

from . import paths as _paths
from .registry import NODE_LOGIC, NODE_ORDER, _SOURCE_CACHE, logic_globals as _logic_globals, home_file as _home_file


def _ext_loc():
    """外部源码位置映射 (真源在 nodes/library.py 的 _EXTERNAL_LOC)"""
    return _logic_globals().get("_EXTERNAL_LOC", {}) or {}


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
    ext = _ext_loc().get(key)
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
        path = _home_file(key)
        line = None
    return path, line, modified


def get_node_external_symbol(key):
    """外部源码映射的真实符号名 (VSCode 定位显示用) — 无映射返回 None"""
    ext = _ext_loc().get(key)
    return ext[2] if ext else None


def _probe_data_root():
    """🆕 2026-08-30 老倪: 探测本机训练数据仓库 — 返回 '路径 · 帧数/集数 · 特征' 或 None
    优先级与 _ensure_training_data 一致: Orin真实(closed_loop) → metaworld_peg_long → metaworld_peg → ss_insert_lerobot"""
    import json as _j, os as _os
    root = _paths.REPO_ROOT
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
    ext = _ext_loc().get(key)
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
        exec(compile(new_code, f"<node:{key}>", "exec"), _logic_globals(), ns)
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
        with open(_home_file(key) or _paths.LOGIC_FILE, encoding="utf-8") as f:
            code = f.read()
        ns = {"__file__": _home_file(key) or _paths.LOGIC_FILE, "__name__": __name__}
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
