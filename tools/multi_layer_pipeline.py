#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多层级 Pipeline —— 把 L5/L4/L3/L2 + 记忆层组织成可插拔、可组合的推理链

老倪 2026-09-23: "把所有层级的模型组成 pipeline, 方便不同模型的组合逻辑推理"

设计目标:
  ① **可插拔**: 每层只依赖契约(infer(ctx)->dict), 换模型不改上下游
  ② **按名注册**: L4 可切 "node.intact" / "node.unified" / "null"
  ③ **组合策略**: serial(串联) / vote(并联仲裁) / 开关(on/off 旁路)
  ④ **统一入口**: 一次 run() 返回全层输出 + 中间量 + 耗时 + 每层 src

用法:
  from multi_layer_pipeline import Pipeline, build_default_spec
  p = Pipeline(build_default_spec(L4="node.unified", L2="null"))
  out = p.run(img=frame, obs39=obs)          # 一次逻辑推理
  print(p.report(out))                        # 全链路可读报告

spec (JSON 可存盘, 便于不同组合):
  {"L5": {"impl": "planner.rules", "on": true},
   "L4": {"impl": "node.unified", "on": true, "combine": "vote", "peers": ["node.intact"]},
   "L3": {"impl": "vla.stub",     "on": true},
   "L2": {"impl": "detect.stub",  "on": true}}
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ─────────────────────────── 契约 ───────────────────────────

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_live_weights() -> str:
    """在役检测器权重 (光模块) — models/yolo_peg_live.pt 软链; 缺失则回 None (由 YoloPerception 兜底)。
    L2 层默认必须用这个, 否则会静默退到通用 COCO yolov8s = 假件。"""
    p = os.path.join(_REPO, "models", "yolo_peg_live.pt")
    return p if os.path.exists(p) else None


@dataclass
class NodeOut:
    """每层统一输出: 数据 + 状态 + 来源 + 耗时 (便于取证)"""
    name: str
    ok: bool = False
    src: str = ""
    latency_ms: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)
    err: str = ""
    conf: float = 0.0          # 置信度 (供 vote 仲裁)


class Layer:
    """层基类: 只要实现 infer(ctx)->NodeOut 即可插拔"""
    name = "layer"
    requires: List[str] = []   # ctx 依赖键
    provides: List[str] = []

    def load(self) -> None:    # 惰性加载模型
        return None

    def infer(self, ctx: Dict[str, Any]) -> NodeOut:
        raise NotImplementedError


# ─────────────────────────── 注册表 ───────────────────────────

_REG: Dict[str, Callable[..., Layer]] = {}


def register(name: str):
    def _d(fn):
        _REG[name] = fn
        return fn
    return _d


def build(impl: str, **kw) -> Layer:
    if impl not in _REG:
        raise KeyError("未注册的层实现: %s (可用: %s)" % (impl, sorted(_REG)))
    return _REG[impl](**kw)


def available() -> List[str]:
    return sorted(_REG)


# ─────────────────────── 通用: 空/旁路层 ───────────────────────

class NullLayer(Layer):
    """旁路层: 不做任何事, 让上游直通 (方便关掉某层做消融)"""
    name = "null"

    def __init__(self, why: str = "旁路"):
        self.why = why

    def infer(self, ctx):
        return NodeOut(name=self.name, ok=True, src="null", data={"bypass": self.why})


@register("null")
def _mk_null(**kw):
    return NullLayer(**kw)


# ─────────────────────────── L5: 定方向/规划 ───────────────────────────

class L5RulesLayer(Layer):
    """L5: 任务规划 (自带规则引擎, 零外部依赖) — 保证任何 venv 可跑"""
    name = "L5"
    provides = ["plan", "skill_seq"]
    STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]

    def __init__(self, instruction: str = "把光模块插入治具"):
        self.instruction = instruction

    def infer(self, ctx):
        t0 = time.time()
        ins = self.instruction
        toks = []
        for st in self.STAGES:
            toks.append({"stage": st, "skill": "L2.slot1" if st in ("抓取", "插入") else "move"})
        # "定方向": 从指令里抽目标/约束词 (可扩展 LLM 后端)
        goal = "insert" if ("插" in ins or "insert" in ins.lower()) else "place"
        ok = len(toks) == len(self.STAGES)
        return NodeOut(name=self.name, ok=ok, src="planner.rules.builtin",
                       latency_ms=(time.time() - t0) * 1000,
                       data={"plan": toks, "n_tokens": len(toks), "goal": goal},
                       conf=1.0 if ok else 0.2)


class L5PlannerLayer(Layer):
    """L5: 真 TaskPlanner (需 lerobot 包完整依赖, 作为可选后端)"""
    name = "L5"
    provides = ["plan", "skill_seq"]

    def __init__(self, instruction: str = "把光模块插入治具", use_llm: bool = False):
        self.instruction = instruction
        self.use_llm = use_llm
        self._pl = None

    def load(self):
        if self._pl is None:
            import sys
            sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/src")
            from lerobot.policies.left_right.state_space.planner import TaskPlanner
            self._pl = TaskPlanner()
        return self

    def infer(self, ctx):
        try:
            self.load()
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="planner.taskplanner",
                           err="依赖缺失: %s" % str(e)[:100])
        t0 = time.time()
        try:
            toks = self._pl.plan(self.instruction)
            ok = bool(self._pl.validate(toks)) if toks else False
            return NodeOut(name=self.name, ok=ok, src="planner.taskplanner",
                           latency_ms=(time.time() - t0) * 1000,
                           data={"plan": toks, "n_tokens": len(toks or [])},
                           conf=1.0 if ok else 0.2)
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="planner.taskplanner",
                           err="%s: %s" % (type(e).__name__, str(e)[:120]),
                           latency_ms=(time.time() - t0) * 1000)


@register("planner.rules")
def _mk_l5_builtin(**kw):
    return L5RulesLayer(**kw)


@register("planner.taskplanner")
def _mk_l5(**kw):
    return L5PlannerLayer(**kw)


# ─────────────────────────── L4: 认知预测 ───────────────────────────

class L4NodeLayer(Layer):
    """L4: 认知预测 (世界模型). 可插拔: node.intact / node.unified"""
    name = "L4"
    requires = ["img", "obs39"]
    provides = ["chunk", "z_t"]

    def __init__(self, which: str = "unified", ckpt: str = "", horizon: int = 8):
        self.which = which
        self.ckpt = ckpt
        self.horizon = horizon
        self._node = None

    def load(self):
        if self._node is not None:
            return self
        import sys
        for _p in ("/home/ubuntu/lerobot-smolvla-lew/src",
                   "/home/ubuntu/lerobot-smolvla-lew/tools/gui"):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        if self.which == "unified":
            from unified_node import UnifiedNode
            self._node = UnifiedNode(ckpt=self.ckpt or
                                     "/home/ubuntu/stable-wm-cache/checkpoints/backbone_cont/unified.pt",
                                     horizon=self.horizon)
        elif self.which == "intact":
            from lerobot.manifold.intact_node import IntactNode
            self._node = IntactNode(horizon=self.horizon)
        else:
            raise KeyError("未知 L4 实现: %s" % self.which)
        return self

    def infer(self, ctx):
        self.load()
        t0 = time.time()
        try:
            out = self._node.step(ctx["img"], obs_source="pipeline")
            chunk = getattr(out, "chunk", None)
            conf = float((getattr(out, "diagnostics", {}) or {}).get("intent_norm", 0.0))
            return NodeOut(name=self.name, ok=chunk is not None,
                           src="node.%s" % self.which,
                           latency_ms=(time.time() - t0) * 1000,
                           data={"chunk": chunk, "trained": getattr(out, "trained", None)},
                           conf=conf)
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="node.%s" % self.which,
                           err="%s: %s" % (type(e).__name__, str(e)[:120]),
                           latency_ms=(time.time() - t0) * 1000)


@register("node.intact")
def _mk_l4_intact(**kw):
    kw.setdefault("which", "intact")
    return L4NodeLayer(**kw)


@register("node.unified")
def _mk_l4_unified(**kw):
    kw.setdefault("which", "unified")
    return L4NodeLayer(**kw)


# ─────────────────────────── L3: 状态调度 ───────────────────────────

class L3DispatchLayer(Layer):
    """L3: 状态调度. 输入 L4 的 chunk/z_t + 阶段, 输出调度后的动作序列.

    预留接口: 接 smolvla StateSpaceActionHead 或引擎调度器 (此处为可跑的轻量实现)
    """
    name = "L3"
    requires = ["chunk"]
    provides = ["u_ff"]

    def __init__(self, k_act: float = 0.5, w: float = 0.3):
        self.k_act = k_act
        self.w = w

    def infer(self, ctx):
        t0 = time.time()
        up = ctx.get("L4")
        chunk = (up.data.get("chunk") if up else None)
        if chunk is None:
            return NodeOut(name=self.name, ok=False, src="dispatch.skip",
                           err="无上游 chunk", latency_ms=(time.time() - t0) * 1000)
        try:
            import numpy as np
            c = np.asarray(chunk, dtype=float)
            # 量纲逆运算: clip(dxyz)*k_act + 夹爪二值 (与引擎一致)
            u = np.stack([np.clip(c[:, 0], -1, 1) * self.k_act,
                          np.clip(c[:, 1], -1, 1) * self.k_act,
                          np.clip(c[:, 2], -1, 1) * self.k_act,
                          np.where(c[:, 3] > 0.5, 1.0, -1.0)], axis=1)
            return NodeOut(name=self.name, ok=True, src="dispatch.k_act",
                           latency_ms=(time.time() - t0) * 1000,
                           data={"u_ff": u, "w": self.w, "n": int(u.shape[0])},
                           conf=float(np.linalg.norm(c)))
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="dispatch.k_act",
                           err="%s: %s" % (type(e).__name__, str(e)[:120]),
                           latency_ms=(time.time() - t0) * 1000)


@register("dispatch.engine")
def _mk_l3(**kw):
    return L3DispatchLayer(**kw)


# ─────────────────────────── L2: 检测反馈 ───────────────────────────

class L2DetectLayer(Layer):
    """L2: 检测 + 反馈. 可插拔: detect.yolo / detect.stub"""
    name = "L2"
    requires = ["img"]
    provides = ["det", "obs_align"]

    def __init__(self, weights: str = "", stub: bool = False):
        self.weights = weights
        self.stub = stub
        self._yp = None

    def load(self):
        if self._yp is None and not self.stub:
            import sys
            sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
            from yolo_perception import YoloPerception
            # 🎯 2026-09-23 老倪: pipeline 里的 L2 必须用**在役检测器**, 不能用通用 COCO yolov8s
            #   (实测: 不给 weights → yolo_perception 默认 yolov8s.pt 80类 → 检到的不是光模块 = 假件)
            self._yp = YoloPerception(weights=self.weights or _default_live_weights())
            self._yp._load()
        return self

    def describe(self) -> str:
        try:
            self.load()
            w = os.path.basename(getattr(self._yp, "weights", "") or "")
            return "YOLO=%s" % (w or "?")
        except Exception:                                                # noqa: BLE001
            return "YOLO=未加载"

    def infer(self, ctx):
        t0 = time.time()
        try:
            if self.stub:
                return NodeOut(name=self.name, ok=True, src="detect.stub",
                               latency_ms=(time.time() - t0) * 1000,
                               data={"det": [], "note": "桩实现(不加载YOLO)"}, conf=0.5)
            self.load()
            det = self._yp.detect(ctx["img"])
            d3 = self._yp.to_3d(det) if det else None
            obs_align = None
            if ctx.get("obs39") is not None and d3 is not None:
                obs_align = self._yp.align_obs(ctx["obs39"], d3)
            return NodeOut(name=self.name, ok=True, src="detect.yolo",
                           latency_ms=(time.time() - t0) * 1000,
                           data={"det": det, "det3d": d3, "obs_align": obs_align},
                           conf=float(len(det)) if det else 0.0)
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="detect.yolo",
                           err="%s: %s" % (type(e).__name__, str(e)[:120]),
                           latency_ms=(time.time() - t0) * 1000)


@register("detect.yolo")
def _mk_l2_yolo(**kw):
    return L2DetectLayer(**kw)


@register("detect.stub")
def _mk_l2_stub(**kw):
    kw["stub"] = True
    return L2DetectLayer(**kw)


# ─────────────────────────── 记忆层 ───────────────────────────

class MemoryLayer(Layer):
    """记忆层: 五层记忆查询 (肌肉/流程/工作/总装/宏观), 输出 mem 向量供 L4 注入"""
    name = "MEM"
    provides = ["mem_vec"]

    def __init__(self, path: str = "data/memory_layers.json", dim: int = 13):
        self.path = path
        self.dim = dim

    def infer(self, ctx):
        t0 = time.time()
        try:
            import numpy as np
            vec = np.zeros(self.dim, dtype=np.float32)
            n = 0
            if os.path.isfile(self.path):
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                n = len(d) if isinstance(d, (list, dict)) else 0
            return NodeOut(name=self.name, ok=True, src="memory.json",
                           latency_ms=(time.time() - t0) * 1000,
                           data={"mem_vec": vec, "n_entries": n}, conf=float(n))
        except Exception as e:
            return NodeOut(name=self.name, ok=False, src="memory.json",
                           err="%s: %s" % (type(e).__name__, str(e)[:100]),
                           latency_ms=(time.time() - t0) * 1000)


@register("memory.json")
def _mk_mem(**kw):
    return MemoryLayer(**kw)


# ─────────────────────────── 组合策略 ───────────────────────────

class VoteCombiner:
    """并联仲裁: 跑多个同层实现, 按 conf 选优 (支持任务级模型组合)"""
    def __init__(self, layers: List[Layer], how: str = "conf"):
        self.layers = layers
        self.how = how

    def run(self, ctx) -> NodeOut:
        outs = [l.infer(ctx) for l in self.layers]
        good = [o for o in outs if o.ok]
        if not good:
            return NodeOut(name=outs[0].name if outs else "?", ok=False,
                           src="vote.none", err="全部实现均失败",
                           data={"cand": [o.src + ":" + (o.err or "") for o in outs]})
        best = max(good, key=lambda o: o.conf) if self.how == "conf" else good[0]
        best.data["vote"] = {"n": len(outs), "ok": len(good),
                             "cand": [(o.src, round(o.conf, 4), o.ok) for o in outs]}
        best.src = "vote[%s]" % best.src
        return best


# ─────────────────────────── Pipeline ───────────────────────────

class Pipeline:
    """按 spec 装配 + 串行推理 + 统一报告"""

    def __init__(self, spec: Dict[str, Dict[str, Any]], order: Optional[List[str]] = None):
        self.spec = spec
        self.order = order or [k for k in ("L5", "MEM", "L2", "L4", "L3") if k in spec]
        self.stages: Dict[str, Any] = {}
        self._build()

    def _build(self):
        for k in self.order:
            s = dict(self.spec.get(k) or {})
            if not s.get("on", True):
                self.stages[k] = NullLayer(why="spec关闭")
                continue
            s.pop("on", None)
            if s.get("combine") == "vote":
                peers = s.pop("peers", [])
                s.pop("combine", None)
                layers = [build(s["impl"], **{x: y for x, y in s.items() if x != "impl"})]
                layers += [build(p) for p in peers]
                self.stages[k] = VoteCombiner(layers)
            else:
                self.stages[k] = build(s["impl"], **{x: y for x, y in s.items() if x != "impl"})

    def run(self, **ctx) -> Dict[str, NodeOut]:
        ctx = dict(ctx)
        ctx["_t0"] = time.time()
        out: Dict[str, NodeOut] = {}
        for k in self.order:
            st = self.stages[k]
            r = st.run(ctx) if isinstance(st, VoteCombiner) else st.infer(ctx)
            r.name = k
            out[k] = r
            ctx[k] = r            # 上游输出进 ctx, 供下游依赖
        return out

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.spec, f, ensure_ascii=False, indent=2)

    @staticmethod
    def report(out: Dict[str, NodeOut]) -> str:
        L = ["═" * 78, "多层级 Pipeline 推理报告", "═" * 78]
        tot = 0.0
        for k, o in out.items():
            tot += o.latency_ms
            flag = "✅" if o.ok else "❌"
            L.append("  %s %-4s %-24s conf=%-8.3f %6.1fms  %s"
                     % (flag, k, o.src, o.conf, o.latency_ms,
                        (o.err[:60] if o.err else str(sorted(o.data.keys()))[:60])))
        L.append("─" * 78)
        L.append("  总耗时 %.1f ms | 成功层 %d/%d" % (tot, sum(1 for o in out.values() if o.ok), len(out)))
        return "\n".join(L)


def build_default_spec(L5: str = "planner.rules", MEM: str = "memory.json",
                       L2: str = "detect.stub", L4: str = "node.unified",
                       L3: str = "dispatch.engine", **kw) -> Dict[str, Dict[str, Any]]:
    return {
        "L5": {"impl": L5, "on": kw.get("L5_on", True)},
        "MEM": {"impl": MEM, "on": kw.get("MEM_on", True)},
        "L2": {"impl": L2, "on": kw.get("L2_on", True)},
        "L4": {"impl": L4, "on": kw.get("L4_on", True)},
        "L3": {"impl": L3, "on": kw.get("L3_on", True)},
    }


# ─────────────────────────── 自测 ───────────────────────────

if __name__ == "__main__":
    import sys
    import numpy as np

    print("可用层实现:", ", ".join(available()))
    mode = (sys.argv[1] if len(sys.argv) > 1 else "stub")
    if mode == "stub":
        spec = build_default_spec(L4="null", L2="detect.stub")
    else:
        spec = build_default_spec(L2="detect.stub")
    p = Pipeline(spec)
    img = (np.random.rand(224, 224, 3) * 255).astype(np.uint8)
    obs39 = np.zeros(39, dtype=np.float32)
    out = p.run(img=img, obs39=obs39)
    print(p.report(out))
    p.save("/tmp/pipeline_spec.demo.json")
    print("\nspec 已存 /tmp/pipeline_spec.demo.json (可直接改 impl 换模型)")

# ─────────────── 引擎挂载适配器 (零引擎改动) ───────────────

class PipelineNode:
    """把整条 Pipeline 包成 IntactNode 同款接口, 供引擎直接挂载。

    引擎调用: node.step(fr, obs_source=..., skill_ctx=...) -> out(.chunk/.trained/.diagnostics)
    spec 来源: 环境变量 SS_PIPELINE_SPEC (JSON 字符串或 JSON 文件路径)
    """
    def __init__(self, spec=None, spec_path="", sim=None, horizon=8):
        self.sim = sim
        if spec is None:
            raw = os.environ.get("SS_PIPELINE_SPEC", "").strip()
            if raw and os.path.isfile(raw):
                with open(raw, encoding="utf-8") as f:
                    spec = json.load(f)
            elif raw:
                spec = json.loads(raw)
            else:
                spec = build_default_spec()
        self.spec = spec
        self.pipe = Pipeline(spec)
        self.horizon = horizon
        self.trained = True
        self.last = None
        print("[PipelineNode] 装配完成: " + " -> ".join(self.pipe.order), flush=True)

    def _obs39(self):
        o = getattr(self.sim, "_last_obs39", None) if self.sim is not None else None
        if o is None:
            import numpy as np
            return np.zeros(39, dtype=np.float32)
        import numpy as np
        return np.asarray(o, dtype=np.float32).ravel()[:39]

    def step(self, fr, obs_source=None, skill_ctx=None):
        import numpy as np
        img = np.asarray(fr)
        if img.ndim == 3 and img.shape[0] == 3:      # CHW -> HWC
            img = img.transpose(1, 2, 0)
        out = self.pipe.run(img=img, obs39=self._obs39(), skill_ctx=skill_ctx)
        self.last = out
        l4 = out.get("L4")
        chunk = (l4.data.get("chunk") if (l4 and l4.ok) else None)
        if chunk is None:                             # L4 缺失时回退 L3 输出
            l3 = out.get("L3")
            chunk = (l3.data.get("u_ff") if (l3 and l3.ok) else None)
        if chunk is None:
            raise RuntimeError("Pipeline 全部候选均无可用 chunk")
        chunk = np.asarray(chunk, dtype=np.float32)
        conf = float((l4.conf if l4 else 0.0) or 0.0)
        return _PipelineOut(chunk, conf, out)


class _PipelineOut:
    __slots__ = ("chunk", "latent", "trained", "intent_norm", "diagnostics", "goal_src", "layers")

    def __init__(self, chunk, conf, layers):
        import numpy as np
        self.chunk = chunk
        self.latent = {"z_t": np.zeros(192, dtype=np.float32)}
        self.trained = True
        self.intent_norm = float(conf) if conf > 0 else float(np.linalg.norm(chunk))
        self.diagnostics = {"intent_norm": self.intent_norm}
        self.goal_src = "pipeline"
        self.layers = layers


def make_pipeline_node(**kw) -> PipelineNode:
    return PipelineNode(**kw)
