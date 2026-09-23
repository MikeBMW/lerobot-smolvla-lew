import os, sys, time
import numpy as np
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/src")
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
from state_space_sim_real import RealStateSpaceSim
from multi_layer_pipeline import PipelineNode, build_default_spec

# spec: L4 并联仲裁 (unified vs intact), L2 桩(避免真机相机依赖)
spec = build_default_spec(L2="detect.stub", L4="node.unified")
spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
print("spec:", spec)

sim = RealStateSpaceSim(seed=104, vision=False, log=lambda *a: None)
node = PipelineNode(spec=spec, sim=sim, horizon=8)
sim.attach_intact(node, None)
tr = sim.run(max_steps=1200)
s = sim._l4_stats
print()
print("=" * 70)
print("PipelineNode 闭环实测 (seed 104):")
print("  calls=%s reuse=%s refused=%s src=%s **w=%s**" % (s["calls"], s["reuse"], s["refused"], s["src"], s["w"]))
print("  步数=%d done=%s 阶段=%s" % (len(tr["t"]), bool(tr["done"][-1]), sim.sched.stage()))
if node.last:
    print("  Pipeline 各层:")
    for k, o in node.last.items():
        print("    %s %-4s %-24s conf=%.3f %6.1fms ok=%s" % ("OK " if o.ok else "ERR", k, o.src, o.conf, o.latency_ms, o.ok))
print("=" * 70)
