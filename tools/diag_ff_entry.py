#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔎 前馈加速器 FeedforwardAccelerator.forward 到底有没有被调用 (取证, 不改任何源码)。

问题 (老倪 09-16): "选 L4 后, parallel.py 的 FeedforwardAccelerator.forward 怎么没进去?"
只取证不解释:
  ① 装配期引擎是否把**实例**的 forward 换成了 analytic_forward (`__dict__` 覆盖)
  ② 跑 N 步后 n_mlp / n_guard 计数 (域判定分支到底跑没跑)
  ③ 实例层 forward 被引擎调用了几次 (不管它现在指向谁)
  ④ 域判定逐帧真值: d_guard 与归一化 max|xn| → 看是 (a) 距离 还是 (b) 逐通道 σ 挡的
用法:
  /home/ubuntu/lerobot-venv/bin/python tools/diag_ff_entry.py 32              # = GUI 默认
  SS_USE_MLP=1 /home/ubuntu/lerobot-venv/bin/python tools/diag_ff_entry.py 32
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "tools", "gui")]

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 32
CNT = {"inst_forward": 0, "real_body": 0, "guard_rows": []}


def main() -> int:
    from state_space_sim_real import RealStateSpaceSim
    print(f"SS_USE_MLP = {os.environ.get('SS_USE_MLP')!r}")
    sim = RealStateSpaceSim(seed=int(os.environ.get("SS_PROBE_SEED", "0")), vision=False,
                            mode="insert", log=lambda *a: None)
    acc, cls = sim.accel, type(sim.accel)
    D_GUARD = float(getattr(sim.parallel, "D_GUARD", 0.25))
    SIGMA = float(getattr(sim.parallel, "DOMAIN_SIGMA", 4.0))
    _inst_has = "forward" in acc.__dict__
    print(f"accel.loaded = {acc.loaded} · accel._ff is None = {acc._ff is None} "
          f"· n_mlp={acc.n_mlp} n_guard={acc.n_guard}")
    print(f"① 实例 __dict__ 覆盖 forward = {_inst_has}")
    print(f"   acc.forward 实际指向 = {getattr(acc.forward, '__name__', acc.forward)} "
          f"(func={getattr(getattr(acc.forward, '__func__', acc.forward), '__name__', '?')})")
    print(f"   类真身 = {cls.forward.__name__} (parallel.py L{cls.forward.__code__.co_firstlineno}) "
          f"· analytic = {cls.analytic_forward.__name__} (L{cls.analytic_forward.__code__.co_firstlineno})")
    print(f"   域参数: D_GUARD={D_GUARD} · DOMAIN_SIGMA={SIGMA}")

    _orig_fwd = cls.forward

    def _body(self, obs):                       # 只包**真身**, 不改一行逻辑
        CNT["real_body"] += 1
        o = np.asarray(obs, float)
        tg = o[36:39] if o.shape[-1] >= 39 else o[0:3]
        d = float(np.linalg.norm(o[0:3] - tg))
        xn_max = None
        if getattr(self._ff, "sm", None) is not None:
            _ss = self._ff.ss
            xn = (o[:39].astype("float32") - self._ff.sm) / np.where(_ss > 1e-4, _ss, 1.0)
            xn_max = float(np.max(np.abs(xn)))
        CNT["guard_rows"].append((d, xn_max))
        return _orig_fwd(self, obs)

    cls.forward = _body
    if _inst_has:                               # 实例已覆盖 → 类包装永远进不去 (这本身是证据)
        _cur = acc.forward

        def _count(obs, _f=_cur):
            CNT["inst_forward"] += 1
            return _f(obs)
        acc.forward = _count

    tr = sim.run(max_steps=STEPS)
    print("── 结果 ──")
    print(f"步数 = {len(tr.get('stage', []))}")
    print(f"② 引擎每帧调用的 acc.forward 次数 = {CNT['inst_forward']}")
    print(f"③ 你那段真身 (def forward) 进入次数 = {CNT['real_body']}")
    print(f"④ accel 自身计数: n_mlp={acc.n_mlp} · n_guard={acc.n_guard}")
    if CNT["guard_rows"]:
        d = np.asarray([r[0] for r in CNT["guard_rows"]], float)
        x = np.asarray([r[1] if r[1] is not None else np.nan for r in CNT["guard_rows"]], float)
        print(f"⑤ 域判定真值: d_guard min/mean/max = {d.min():.4f}/{d.mean():.4f}/{d.max():.4f} "
              f"(门 = {D_GUARD}) · 超门帧数 = {int((d > D_GUARD).sum())}/{len(d)}")
        if not np.all(np.isnan(x)):
            print(f"   归一化 max|xn| mean/max = {np.nanmean(x):.3f}/{np.nanmax(x):.3f} "
                  f"(门 = {SIGMA}) · 超门帧数 = {int((x > SIGMA).sum())}/{len(x)}")
    _st: dict = {}
    for s in tr.get("stage", []):
        _st[str(s)] = _st.get(str(s), 0) + 1
    print(f"⑥ 阶段分布: {_st}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
