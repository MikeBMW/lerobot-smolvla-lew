#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L4 运行时调用链取证 — SmolVLALewActionHead 的 loss 行到底有没有被调用

老倪: 「运行 L4 的时候, 这个断点 return (loss*valid_mask).sum()/num_valid.clamp_min(1)
      没有进来, 查」

本脚本给**运行期证据** (不是读代码猜):
  ① 函数级计数: SmolVLALewActionHead.__init__/forward/predict_action、SmolVLALewPolicy.*、
     DiT.forward、StateSpaceActionHead.*、IntactNode.step / IntactIntentDecoder.decode
  ② 行级计数: 对 action_head.py / modeling_smolvla_lew.py / intact/decoder.py / intact runtime
     逐行计数 → 直接看 action_head.py:307 (loss 行) 执行了几次

用法 (务必带 CUDA_VISIBLE_DEVICES= 避免和正在跑的训练抢显存):
  CUDA_VISIBLE_DEVICES= python3 tools/probe_l4_callchain.py L4    [steps]  # 复刻 GUI「运行+L4」(INTACT 直驱)
  CUDA_VISIBLE_DEVICES= python3 tools/probe_l4_callchain.py L4dec [steps]  # L4 → 意图解码器 (SS_L4_INTACT)
  CUDA_VISIBLE_DEVICES= python3 tools/probe_l4_callchain.py L3    [steps]  # 正对照: L3 模型真执行 (SS_L3=1)
  CUDA_VISIBLE_DEVICES= python3 tools/probe_l4_callchain.py micro          # 微型头: forward(loss) vs predict_action
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "tools", "gui")]
os.chdir(ROOT)

os.environ["CUDA_VISIBLE_DEVICES"] = ""          # 🔒 训练在跑 → 探针零 GPU
os.environ["MUJOCO_GL"] = "egl"
os.environ.setdefault("DISPLAY", ":0")
os.environ.update({"SS_MUSCLE": "0", "SS_MOTOR_HUB": "0", "SS_INTENT": "0",
                   "SS_TDEC": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"})
os.environ.update({"STABLEWM_HOME": "/home/ubuntu/stable-wm-cache",
                   "LOCAL_DATASET_DIR": "/home/ubuntu/stable-wm-cache",
                   "INTACT_REPO": "/home/ubuntu/INTACT-JEPA",
                   "INTACT_POLICY": "intact_l4_current", "INTACT_DEVICE": "cpu",
                   "INTACT_RUNTIME": "root"})

SCEN = sys.argv[1] if len(sys.argv) > 1 else "L4"

# 🎲 2026-09-15: 全局种子 —— L3/L4 档的推理含随机噪声采样 (policy sample noise),
#   不播种则同一场景两次跑 hash 都不同 (实测: 同一配置两臂 hash 不同) → 零回退比对失效。
#   这里统一播种, 让**臂间比较**有意义 (两臂同 seed, 差异只可能来自被改动的代码路径)。
_PROBE_SEED = int(os.environ.get("SS_PROBE_SEED", "0"))
np.random.seed(_PROBE_SEED)
try:
    import torch as _torch_seed
    _torch_seed.manual_seed(_PROBE_SEED)
    if os.environ.get("SS_PROBE_THREADS") == "1":
        # 🎯 L3 大模型 CPU bf16 的归约顺序受线程数影响 → FP 级非确定 → 逐位 hash 不可比。
        #   单线程化后同配置两臂应逐位一致 (零回退比对的仪器前提)。
        _torch_seed.set_num_threads(1)
except Exception:
    pass
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 60

for _k in ("SS_L3", "SS_L4_INTACT", "SS_INTACT", "SS_INTACT_SHADOW"):
    os.environ.pop(_k, None)

CALLS: dict[str, int] = {}
ERR: list[str] = []


def patch(modname: str, cls: str, meth: str, tag: str) -> None:
    """给 类.方法 裹一层计数器 (函数级证据)。"""
    try:
        m = importlib.import_module(modname)
        k = getattr(m, cls)
        f = getattr(k, meth)
        if getattr(f, "_probe_wrapped", False):
            return
        if meth == "__init__":
            def w(self, *a, **kw):
                CALLS[tag] = CALLS.get(tag, 0) + 1
                return f(self, *a, **kw)
        else:
            def w(self, *a, **kw):
                CALLS[tag] = CALLS.get(tag, 0) + 1
                return f(self, *a, **kw)
        w._probe_wrapped = True
        setattr(k, meth, w)
    except Exception as e:                                                       # noqa: BLE001
        ERR.append(f"{tag}: {type(e).__name__}: {e}")


def patch_func(modname: str, funcname: str, tag: str) -> None:
    """给模块级函数裹计数器。"""
    try:
        m = importlib.import_module(modname)
        f = getattr(m, funcname)
        if getattr(f, "_probe_wrapped", False):
            return
        def w(*a, **kw):
            CALLS[tag] = CALLS.get(tag, 0) + 1
            return f(*a, **kw)
        w._probe_wrapped = True
        setattr(m, funcname, w)
    except Exception as e:                                                       # noqa: BLE001
        ERR.append(f"{tag}: {type(e).__name__}: {e}")


# ── ① 函数级: smolvla_lew 动作头 + 策略 + 状态空间头 ──────────────────────────
_LEW = "lerobot.policies.smolvla_lew."
patch(_LEW + "action_head", "SmolVLALewActionHead", "__init__", "SmolVLALewActionHead.__init__ ⚠️类被实例化")
patch(_LEW + "action_head", "SmolVLALewActionHead", "forward", "SmolVLALewActionHead.forward  ← loss 行所在")
patch(_LEW + "action_head", "SmolVLALewActionHead", "predict_action", "SmolVLALewActionHead.predict_action (推理)")
patch(_LEW + "action_head", "DiT", "forward", "DiT.forward (DiT 主干)")
patch(_LEW + "modeling_smolvla_lew", "SmolVLALewPolicy", "__init__", "SmolVLALewPolicy.__init__ ⚠️策略被实例化")
patch(_LEW + "modeling_smolvla_lew", "SmolVLALewPolicy", "forward", "SmolVLALewPolicy.forward (训练)")
patch(_LEW + "modeling_smolvla_lew", "SmolVLALewPolicy", "predict_action_chunk", "SmolVLALewPolicy.predict_action_chunk")
patch(_LEW + "modeling_smolvla_lew", "SmolVLALewPolicy", "select_action", "SmolVLALewPolicy.select_action")
patch(_LEW + "state_space_action_head", "StateSpaceActionHead", "forward", "StateSpaceActionHead.forward")
# ── ② 函数级: INTACT (L4 真链路) ─────────────────────────────────────────────
patch("lerobot.policies.intact.decoder", "IntactIntentDecoder", "__init__", "IntactIntentDecoder.__init__")
patch("lerobot.policies.intact.decoder", "IntactIntentDecoder", "decode", "IntactIntentDecoder.decode")
patch("lerobot.manifold.intact_node", "IntactNode", "step", "IntactNode.step (INTACT 真推理)")
patch("lerobot.manifold.intact_node", "IntactRuntime", "__init__", "IntactRuntime.__init__ (跨venv桥)")
patch("lerobot.manifold.intact_node", "IntactNode", "set_goal", "IntactNode.set_goal (目标帧注入)")
patch("lerobot.policies.intact.service", "IntactIntentService", "run_once", "IntactIntentService.run_once (L4 编排) ← 父进程断点")
patch_func("lerobot.policies.intact.skill_ctx", "build_skill_ctx", "build_skill_ctx (L2 上下文) ← 父进程断点")

# ── 行级计数器 ───────────────────────────────────────────────────────────────
TRACE_FILES = {
    os.path.join("smolvla_lew", "action_head.py"): "action_head.py",
    os.path.join("smolvla_lew", "modeling_smolvla_lew.py"): "modeling_smolvla_lew.py",
    os.path.join("policies", "intact", "decoder.py"): "intact/decoder.py",
    os.path.join("policies", "intact", "runtime", "node.py"): "intact/runtime/node.py",
}
LC: dict[str, dict[int, int]] = {}


def _ltrace(frame, event, arg):
    if event == "line":
        fn = frame.f_code.co_filename
        for suf, name in TRACE_FILES.items():
            if fn.endswith(suf):
                LC.setdefault(name, {})
                LC[name][frame.f_lineno] = LC[name].get(frame.f_lineno, 0) + 1
                break
    return _ltrace


def _gtrace(frame, event, arg):
    fn = frame.f_code.co_filename
    for suf in TRACE_FILES:
        if fn.endswith(suf):
            return _ltrace
    return None


def _find_line(rel_path: str, needle: str, default: int, after: str | None = None) -> int:
    """按源码内容定位行号 (改文件后行号会漂移 → 证据不能写死行号)。
    after: 只在首次出现 after 之后查找 (用于区分同名方法, 如 TimestepEncoder.forward vs
           SmolVLALewActionHead.forward)。"""
    try:
        p = os.path.join(ROOT, rel_path)
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
        start = 0
        if after:
            for i, ln in enumerate(lines):
                if after in ln:
                    start = i
                    break
            else:                       # 没找到锚点 → 退回全文查找
                start = 0
        for i in range(start, len(lines)):
            if needle in lines[i]:
                return i + 1
    except Exception:
        pass
    return default


ACTION_HEAD = os.path.join("src", "lerobot", "policies", "smolvla_lew", "action_head.py")
MODELING = os.path.join("src", "lerobot", "policies", "smolvla_lew", "modeling_smolvla_lew.py")
LOSS_LINE = _find_line(ACTION_HEAD, "return (loss * valid_mask).sum()", 351)
PRED_LINE = _find_line(ACTION_HEAD, "def predict_action(", 354)
# 🐛 2026-09-15 修: 原 FWD_LINE 取全文第一个 "def forward(" = TimestepEncoder.forward(53),
#   报告里却标成"loss 分支函数入口" → 误导。现锚在 class SmolVLALewActionHead 之后取。
HEAD_FWD_LINE = _find_line(ACTION_HEAD, "def forward(", 322, after="class SmolVLALewActionHead")
FWD_LINE = HEAD_FWD_LINE
# 同理: modeling 侧关键行也动态定位 (行号漂移不再误导)
MODEL_FWD_LINE = _find_line(MODELING, "def forward(self, examples", 234)
MODEL_LOSS_CALL_LINE = _find_line(MODELING, "action_loss = self.action_model(", 319)
MODEL_SELECT_LINE = _find_line(MODELING, "def select_action(", 512)
DIT_LINE = _find_line(ACTION_HEAD, "tem2 = self.timestep_encoder", 176) if False else 0


def line_hits(name: str, lineno: int) -> int:
    return LC.get(name, {}).get(lineno, 0)


def report(scen: str, extra: dict) -> None:
    print("\n" + "=" * 78)
    print(f"场景 {scen} · 步数 {extra.get('steps', '-')} · 用时 {extra.get('dt', 0):.1f}s")
    print("=" * 78)
    print("① 函数级调用计数 (0 = 该函数在本次运行里一次都没进):")
    for k in sorted(CALLS):
        print(f"   {CALLS[k]:>6}  {k}")
    if not CALLS:
        print("   (无)")
    if ERR:
        print("   打桩失败:", ERR)
    print("\n② 行级计数 (关键行):")
    for name, ln, why in [("action_head.py", LOSS_LINE, "👈 老倪断点: return (loss*valid_mask)... (行号自动定位)"),
                          ("action_head.py", FWD_LINE, "def forward( (SmolVLALewActionHead, 锚定类内非全文件首个)"),
                          ("action_head.py", PRED_LINE, "def predict_action( (推理入口)"),
                          ("modeling_smolvla_lew.py", MODEL_FWD_LINE, "def forward( (训练 loss 分支)"),
                          ("modeling_smolvla_lew.py", MODEL_LOSS_CALL_LINE, "action_loss = self.action_model(...) (唯一调用 loss 的地方)"),
                          ("modeling_smolvla_lew.py", MODEL_SELECT_LINE, "def select_action( (推理)"),
                          ("intact/decoder.py", 126, "IntactIntentDecoder.decode 主体")]:
        print(f"   {line_hits(name, ln):>6}  {name}:{ln}  {why}")
    print("\n   已执行到的 action_head.py 行 (全量):")
    hits = sorted(LC.get("action_head.py", {}).items())
    print("     ", ", ".join(f"{ln}({c})" for ln, c in hits) or "(无)")
    r = lambda a, b: sum(c for ln, c in hits if a <= ln <= b)                        # noqa: E731
    print(f"\n   区间命中: loss 行({LOSS_LINE})={line_hits('action_head.py', LOSS_LINE)} · "
          f"predict_action 主体({PRED_LINE+1}-{PRED_LINE+35})={r(PRED_LINE+1, PRED_LINE+35)} · "
          f"forward 主体({FWD_LINE+1}-{LOSS_LINE-1})={r(FWD_LINE+1, LOSS_LINE-1)}")
    if extra:
        print("\n③ 引擎侧计数:", {k: v for k, v in extra.items()
                                if k not in ("engine_warn", "engine_logs_n", "il_summary")})
        if extra.get("il_summary"):
            print("\n③b 🧬 直连线取证 (INTACT 意图解码器 → 流形专家预测器):")
            _il = extra["il_summary"]
            for _k in ("enabled", "frames", "ran", "applied", "w_zero", "refused", "ready",
                       "ready_src", "src_last", "w_last", "err", "intent_gain_mean",
                       "manifold_last", "clip_max", "stack", "by_stage"):
                if _k in _il:
                    print(f"     {_k}: {_il[_k]}")
        if extra.get("fiber_summary"):
            print("\n③c 🧬 纤维丛联络层 (潜空间丛 Z → 接触丛 C 主力 / 性能丛 P 次要):")
            _fs = extra["fiber_summary"]
            for _k in ("enabled", "frames", "ran", "no_latent", "ready", "map_src", "err",
                       "src_last", "h_norm_mean", "kappa_tor_mean", "kappa_curv_mean",
                       "cos_geo_mean", "phi_last", "omega_last", "contact_true_last",
                       "sample_n", "w_perf", "perf_note"):
                if _k in _fs:
                    print(f"     {_k}: {_fs[_k]}")
            if extra.get("fiber_dump"):
                print(f"     dump: {extra['fiber_dump']}")
        _warn = extra.get("engine_warn") or []
        print(f"\n④ 引擎日志告警回放 (累计 {extra.get('engine_logs_n', 0)} 行, 关键 {len(_warn)} 行):")
        for _l in _warn:
            print("   ", _l)
        if not _warn:
            print("    (无告警行 — 若期望 L3/INTACT 有动作却 0 次, 说明是门控没放行, 不是静默异常)")


def build_intact_node():
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    import intact_direct_rollout as _idr
    rt = IntactRuntime(task="pusht", device="cpu")
    nd = IntactNode(horizon=8, runtime=rt)
    gf = os.path.join(ROOT, "reports", "intact_goal_frame.npy")
    # 🎯 2026-09-22: 反归一化统计按 ckpt 训练集自动同源 (原来写死 zmax_action_stats.json → 与 v6 权重不同源)
    stf, _why = _idr.resolve_stats()
    print(f"统计同源解析: {_why}")
    print(f"INTACT runtime: trained={getattr(rt, 'trained', None)} · reason={getattr(rt, 'reason', '')}")
    if os.path.isfile(gf) and os.path.isfile(stf):
        nd.set_goal(np.load(gf))
    else:
        print(f"缺目标帧/统计 ({os.path.isfile(gf)}/{os.path.isfile(stf)})")
    return nd, stf


def run_engine(scen: str) -> dict:
    from state_space_sim_real import RealStateSpaceSim
    # 🐛 2026-09-15 修 (探针诚实性): 原来 log=lambda *a: None 把引擎告警**全部吞掉**,
    #   曾导致 L3 正对照「熔断原因被静默」→ 只看到 l3_calls=0 无从归因。现改为收集后回放。
    _LOGS: list[str] = []
    sim = RealStateSpaceSim(seed=int(os.environ.get("SS_PROBE_SEED", "0")), vision=False, mode="insert",
                            log=lambda *a: _LOGS.append(" ".join(str(x) for x in a)))
    if scen == "L4":            # 复刻 GUI: SS_INTACT=1 + 直驱装配 (install_direct_act)
        os.environ["SS_INTACT"] = "1"
        os.environ["SS_INTACT_SHADOW"] = "1"        # 标定缺失也真推理真记录 (否则未标定直接 return)
        os.environ["SS_INTACT_EVERY"] = "1"
        nd, stf = build_intact_node()
        import intact_direct_rollout as idr
        am, asd, _m = idr.load_stats(stf)
        rec, stt = idr.install_direct_act(sim, nd, am, asd, infer_every=1)
        sim.attach_intact(nd, None)
        sim._intact_drive = {"node": nd, "rec": rec, "state": stt}
    elif scen == "L4dec":       # L4 → 意图解码器 (引擎 u_ff 槽位)
        os.environ["SS_L4_INTACT"] = "1"
        nd, _ = build_intact_node()
        sim.attach_intact(nd, None)
    elif scen == "L4line":      # 🧬 L4 → 意图解码器 → 流形专家预测器 直连线 (真数据传输取证)
        os.environ["SS_L4_INTACT"] = "1"
        os.environ.setdefault("SS_L4_INTENT_LINE", "1")
        nd, _ = build_intact_node()
        sim.attach_intact(nd, None)
    elif scen == "L4audit":     # 🧾 L4 区**每条线**的数据流审计 (老倪: 每条 L4 线条都要有实际数据)
        os.environ["SS_L4_INTACT"] = "1"
        os.environ.setdefault("SS_L4_INTENT_LINE", "1")
        os.environ.setdefault("SS_L4_FIBER", "1")
        os.environ.setdefault("SS_L4_DIT", "1")
        nd, _ = build_intact_node()
        sim.attach_intact(nd, None)
    elif scen == "L3":          # 正对照: L3 模型真执行
        os.environ["SS_L3"] = "1"
        # 2026-09-15 修: 原来写死 every=4, 而探针常只跑 2-3 步 → 推理一次都不触发,
        # 正对照会假阴 (l3_calls=0)。现允许外部覆盖, 默认每步都推理。
        os.environ["SS_L3_EVERY"] = os.environ.get("SS_L3_EVERY", "1")
    t0 = time.time()
    tr = sim.run(max_steps=STEPS)
    dt = time.time() - t0
    extra = {"steps": len(tr.get("stage", [])), "dt": dt}
    for attr in ("_intact_stats", "_l4_stats", "_intact_drive", "_l4_dit"):
        v = getattr(sim, attr, None)
        if isinstance(v, dict):
            keep = {k: (round(float(np.mean(x)), 4) if isinstance(x, list) and x else x)
                    for k, x in v.items() if k != "rec"}
            if attr == "_intact_drive":
                keep = {"keys": list(v.keys())}
            extra[attr] = keep
    _drv = getattr(sim, "_intact_drive", None) or {}
    if isinstance(_drv, dict):
        extra["dit_state"] = (_drv.get("state") or {}).get("dit")
    extra["l3_calls"] = getattr(sim, "_l3_calls", 0)
    # 🧬 直连线取证 (L4 意图解码器 → 流形专家预测器): 只有这条线才拿得到 m_int 的下游计数
    try:
        if hasattr(sim, "l4_intent_line_summary"):
            extra["il_summary"] = sim.l4_intent_line_summary()
    except Exception as _e:                                                      # noqa: BLE001
        extra["il_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🛡 2026-09-16 质量闸取证 (逐阶段"上层是否优于 L2"; 未过闸 → K 强制 0)
    try:
        if hasattr(sim, "quality_summary"):
            extra["quality_summary"] = sim.quality_summary()
    except Exception as _e:                                                      # noqa: BLE001
        extra["quality_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🧭 2026-09-16 李群意图层取证 (SU(2)/SE(3): 意图 Δz → ω/ξ → DiT token + 导航方向)
    try:
        if hasattr(sim, "lie_summary"):
            extra["lie_summary"] = sim.lie_summary()
    except Exception as _e:                                                      # noqa: BLE001
        extra["lie_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🎚 2026-09-16 自适应增益层取证 (卡尔曼式: 熟场景→L2 / 泛化受扰→抬 L4 导航 + L3 流程)
    try:
        if hasattr(sim, "gain_summary"):
            extra["gain_summary"] = sim.gain_summary()
    except Exception as _e:                                                      # noqa: BLE001
        extra["gain_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🧬 纤维丛联络层取证 (潜空间丛 → 接触丛; 2026-09-15 老倪)
    try:
        if hasattr(sim, "fiber_line_summary"):
            extra["fiber_summary"] = sim.fiber_line_summary()
        if os.environ.get("SS_L4_FIBER_DATA") and hasattr(sim, "dump_fiber_data"):
            extra["fiber_dump"] = sim.dump_fiber_data(os.environ["SS_L4_FIBER_DATA"])
    except Exception as _e:                                                      # noqa: BLE001
        extra["fiber_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🎯 Step ① 对齐采数 + 取证 (u_l2/u_int 成对; 收口闸通过率)
    try:
        if os.environ.get("SS_L4_ALIGN_DATA") and hasattr(sim, "dump_align_data"):
            extra["align_dump"] = sim.dump_align_data(os.environ["SS_L4_ALIGN_DATA"])
        if hasattr(sim, "align_summary"):
            extra["align_summary"] = sim.align_summary()
    except Exception as _e:                                                      # noqa: BLE001
        extra["align_summary"] = {"err": f"{type(_e).__name__}: {_e}"}
    # 🧾 L4 区每条线的数据流审计: 逐帧列统计 + 各层 summary → json (audit_l4_edges.py 消费)
    try:
        _cols = ("u_ff_vec", "u_exec_vec", "u_fuse_vec", "l4_u_ff_vec", "l4_cond_vec",
                 "mani_pred", "mani_progress", "mani_risk", "mani_V", "mani_eta",
                 "mani_dperp", "z7_vec", "latent_vec",
                 "fiber_h_norm", "fiber_kappa_tor", "fiber_kappa_curv", "fiber_cos_geo",
                 "fiber_contact_true", "fiber_perf_true", "fiber_z7_hat", "fiber_cond_norm",
                 "l4_cos", "l4_mag_ratio", "l4_gate", "l4_cos_pre_align")
        _tr = locals().get("tr")
        _cstats = {}
        if _tr is not None:
            for _k in _cols:
                _v = _tr.get(_k)
                if _v is None:
                    continue
                _arr = [x for x in _v if x is not None]
                _nz = sum(1 for x in _arr if np.any(np.asarray(x, float) != 0.0))
                _cstats[_k] = {"n": len(_v), "n_nonnull": len(_arr), "n_nonzero": _nz,
                               "dim": (int(np.asarray(_arr[-1]).size) if _arr else 0),
                               "last_norm": (float(np.linalg.norm(np.asarray(_arr[-1], float)))
                                             if _arr else 0.0)}
            # 🧾 零回退仪器: 对执行相关列取逐位 hash (同 seed 两臂对比)
            try:
                import hashlib as _hl
                h = _hl.sha256()
                for _k in ("x", "peg", "u_ff_vec", "u_exec_vec", "u_fuse_vec", "stage",
                           "done", "dist", "grasped"):
                    _v = _tr.get(_k)
                    if _v is None:
                        continue
                    _num = []
                    for x in _v:
                        if x is None:
                            _num.append(0.0)
                        elif isinstance(x, (str, bytes)):
                            _num.append(float(sum(bytearray(str(x).encode("utf-8")))))  # 字符串→稳定数值
                        elif isinstance(x, bool):
                            _num.append(float(x))
                        elif hasattr(x, "__len__"):
                            _num.append(float(np.mean(np.asarray(x, dtype=np.float64))))
                        else:
                            _num.append(float(x))
                    h.update(np.asarray(_num, dtype=np.float64).tobytes())
                extra["trace_hash"] = h.hexdigest()[:32]
            except Exception as _he:                                              # noqa: BLE001
                extra["trace_hash"] = f"hash失败 {type(_he).__name__}: {_he}"
        extra["trace_cols"] = _cstats
        # 🧾 A/B 需要的任务级终态 + 李雅普诺夫 V 轨迹统计 (同口径两臂比较用)
        try:
            _f = {}
            if _tr is not None:
                _done = [bool(x) for x in (_tr.get("done") or [])]
                _dist = [float(x) for x in (_tr.get("dist") or []) if x is not None]
                _V = [float(x) for x in (_tr.get("mani_V") or []) if x is not None]
                _stg = [str(x) for x in (_tr.get("stage") or [])]
                _f = {"steps": len(_tr.get("stage") or []),
                      "done_any": bool(any(_done)), "done_last": bool(_done[-1]) if _done else None,
                      "dist_min": (min(_dist) if _dist else None),
                      "dist_last": (_dist[-1] if _dist else None),
                      "V_first": (_V[0] if _V else None), "V_last": (_V[-1] if _V else None),
                      "V_min": (min(_V) if _V else None), "V_max": (max(_V) if _V else None),
                      "V_n": len(_V),
                      "stage_counts": {k: _stg.count(k) for k in sorted(set(_stg))}}
            extra["final"] = _f
        except Exception as _fe:                                                  # noqa: BLE001
            extra["final"] = {"err": f"{type(_fe).__name__}: {_fe}"}
        extra["summaries"] = {
            "intact_attach": sim._intact_stats if hasattr(sim, "_intact_stats") else {},
            "l4": sim._l4_stats,
            "il": (sim.l4_intent_line_summary() if hasattr(sim, "l4_intent_line_summary") else {}),
            "fiber": extra.get("fiber_summary", {}),
            "l4_dit": (sim._l4_dit_stats_init() if hasattr(sim, "_l4_dit_stats_init") else {}),
        }
        if os.environ.get("SS_L4_AUDIT_JSON"):
            _dst = os.environ["SS_L4_AUDIT_JSON"]
            os.makedirs(os.path.dirname(_dst), exist_ok=True)
            with open(_dst, "w", encoding="utf-8") as _f:
                json.dump({"scen": scen, "steps": extra.get("steps"),
                           "trace_hash": extra.get("trace_hash"),
                           "final": extra.get("final"),
                           "env": {k: os.environ.get(k) for k in
                                   ("SS_L4_INTACT", "SS_L4_INTENT_LINE", "SS_L4_FIBER",
                                    "SS_L4_DIT", "SS_L3", "SS_INTACT")},
                           "align": extra.get("align_summary"),
                           "trace_cols": _cstats, "summaries": extra["summaries"]},
                          _f, ensure_ascii=False, indent=1, default=str)
            extra["audit_json"] = _dst
    except Exception as _e:                                                      # noqa: BLE001
        extra["audit_err"] = f"{type(_e).__name__}: {_e}"
    # 回放引擎告警/失败行 (静默=无告警; 有则原样打印, 便于归因)
    extra["engine_warn"] = [l for l in _LOGS
                            if any(k in l for k in ("⚠", "失败", "熔断", "L3", "error", "Error"))][:25]
    extra["engine_logs_n"] = len(_LOGS)
    return extra


def micro() -> None:
    """微型头对照: forward() 会命中 loss 行; predict_action() 不会 (证明打桩有效)。"""
    import torch
    from lerobot.policies.smolvla_lew.action_head import SmolVLALewActionHead
    from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
    cfg = SmolVLALewConfig(action_model_type="DiT-test", chunk_size=4, n_action_steps=4,
                           action_dim=4, state_dim=8, action_hidden_size=16,
                           num_inference_timesteps=2)
    head = SmolVLALewActionHead(cfg, cross_attention_dim=16).eval()
    cond = torch.randn(2, 5, 16)
    act = torch.randn(2, 4, 4)
    sys.settrace(_gtrace)
    try:
        with torch.no_grad():
            loss = head.forward(cond, act, state=torch.randn(2, 1, 8))
        n_after_fwd = line_hits("action_head.py", LOSS_LINE)
        try:
            out = head.predict_action(cond, state=torch.randn(2, 1, 8))
            ok_pred = tuple(np.shape(out))
        except Exception as e:                                                   # noqa: BLE001
            ok_pred = f"{type(e).__name__}: {e}"
        n_after_pred = line_hits("action_head.py", LOSS_LINE)
    finally:
        sys.settrace(None)
    print(f"微对照 (微型 DiT-test 头, 本进程内直接调) · forward@{FWD_LINE} / "
          f"predict_action@{PRED_LINE} / loss 行@{LOSS_LINE} (按源码动态定位, 不写死行号):")
    print(f"   forward()       → loss={float(loss):.4f} · 行 {LOSS_LINE}(loss) 命中 {n_after_fwd} 次  ← 训练分支")
    print(f"   predict_action()→ 输出 {ok_pred} · 行 {LOSS_LINE}(loss) 累计 {n_after_pred} 次  ← 推理分支 (增量 {n_after_pred - n_after_fwd})")
    print(f"   已执行行: {', '.join(f'{ln}({c})' for ln, c in sorted(LC.get('action_head.py', {}).items()))}")


if __name__ == "__main__":
    print(f"探针场景={SCEN} 步数={STEPS} CUDA_VISIBLE_DEVICES='{os.environ['CUDA_VISIBLE_DEVICES']}' "
          f"(空 = 不动 GPU)")
    if SCEN == "micro":
        micro()
    else:
        sys.settrace(_gtrace)
        try:
            extra = run_engine(SCEN)
        finally:
            sys.settrace(None)
        report(SCEN, extra)
