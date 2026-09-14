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
    for name, ln, why in [("action_head.py", 307, "👈 老倪断点: return (loss*valid_mask)..."),
                          ("action_head.py", 280, "def forward( (loss 分支函数入口)"),
                          ("action_head.py", 310, "def predict_action( (推理入口)"),
                          ("action_head.py", 176, "DiT.forward 主体"),
                          ("modeling_smolvla_lew.py", 234, "def forward( (训练 loss 分支)"),
                          ("modeling_smolvla_lew.py", 319, "action_loss = self.action_model(...) (唯一调用 loss 的地方)"),
                          ("modeling_smolvla_lew.py", 508, "def select_action( (推理)"),
                          ("intact/decoder.py", 126, "IntactIntentDecoder.decode 主体")]:
        print(f"   {line_hits(name, ln):>6}  {name}:{ln}  {why}")
    print("\n   已执行到的 action_head.py 行 (全量):")
    hits = sorted(LC.get("action_head.py", {}).items())
    print("     ", ", ".join(f"{ln}({c})" for ln, c in hits) or "(无)")
    r = lambda a, b: sum(c for ln, c in hits if a <= ln <= b)                        # noqa: E731
    print(f"\n   区间命中: 307={line_hits('action_head.py', 307)} · "
          f"predict_action 主体(311-345)={r(311, 345)} · forward 主体(281-307)={r(281, 307)} · "
          f"DiT.forward 主体(176-190)={r(176, 190)}")
    if extra:
        print("\n③ 引擎侧计数:", extra)


def build_intact_node():
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    rt = IntactRuntime(task="pusht", device="cpu")
    nd = IntactNode(horizon=8, runtime=rt)
    gf = os.path.join(ROOT, "reports", "intact_goal_frame.npy")
    stf = os.path.join(ROOT, "reports", "zmax_action_stats.json")
    print(f"INTACT runtime: trained={getattr(rt, 'trained', None)} · reason={getattr(rt, 'reason', '')}")
    if os.path.isfile(gf) and os.path.isfile(stf):
        nd.set_goal(np.load(gf))
    else:
        print(f"缺目标帧/统计 ({os.path.isfile(gf)}/{os.path.isfile(stf)})")
    return nd, stf


def run_engine(scen: str) -> dict:
    from state_space_sim_real import RealStateSpaceSim
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *a: None)
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
    elif scen == "L3":          # 正对照: L3 模型真执行
        os.environ["SS_L3"] = "1"
        os.environ["SS_L3_EVERY"] = "4"
    t0 = time.time()
    tr = sim.run(max_steps=STEPS)
    dt = time.time() - t0
    extra = {"steps": len(tr.get("stage", [])), "dt": dt}
    for attr in ("_intact_stats", "_l4_stats", "_intact_drive"):
        v = getattr(sim, attr, None)
        if isinstance(v, dict):
            keep = {k: (round(float(np.mean(x)), 4) if isinstance(x, list) and x else x)
                    for k, x in v.items() if k != "rec"}
            if attr == "_intact_drive":
                keep = {"keys": list(v.keys())}
            extra[attr] = keep
    extra["l3_calls"] = getattr(sim, "_l3_calls", 0)
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
        n_after_fwd = line_hits("action_head.py", 307)
        try:
            out = head.predict_action(cond, state=torch.randn(2, 1, 8))
            ok_pred = tuple(np.shape(out))
        except Exception as e:                                                   # noqa: BLE001
            ok_pred = f"{type(e).__name__}: {e}"
        n_after_pred = line_hits("action_head.py", 307)
    finally:
        sys.settrace(None)
    print("微对照 (微型 DiT-test 头, 本进程内直接调):")
    print(f"   forward()       → loss={float(loss):.4f} · 行 307 命中 {n_after_fwd} 次  ← 训练分支")
    print(f"   predict_action()→ 输出 {ok_pred} · 行 307 累计 {n_after_pred} 次  ← 推理分支 (增量 {n_after_pred - n_after_fwd})")
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
