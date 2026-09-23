import sys, time
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import numpy as np
from multi_layer_pipeline import Pipeline, build_default_spec, available

print("可用层实现:", ", ".join(available()))
img = (np.random.rand(224, 224, 3) * 255).astype(np.uint8)
obs39 = np.zeros(39, dtype=np.float32)

# 组合1: 真实统一主干 (L4=node.unified) + 桩L2
print("\n" + "=" * 78)
print("组合1: L5(rules) -> MEM -> L2(stub) -> **L4(node.unified)** -> L3")
print("=" * 78)
p1 = Pipeline(build_default_spec(L2="detect.stub", L4="node.unified"))
t0 = time.time()
o1 = p1.run(img=img, obs39=obs39)
print(p1.report(o1))
print("  实耗 %.1f ms" % ((time.time() - t0) * 1000))

# 组合2: L4 并联仲裁 (unified vs intact, 按置信度选优)
print("\n" + "=" * 78)
print("组合2: L4 = **vote[node.unified, node.intact]** (并联仲裁, 按 intent_norm 选优)")
print("=" * 78)
spec2 = build_default_spec(L2="detect.stub", L4="node.unified")
spec2["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
p2 = Pipeline(spec2)
o2 = p2.run(img=img, obs39=obs39)
print(p2.report(o2))
v = o2["L4"].data.get("vote")
if v:
    print("  仲裁明细: n=%d ok=%d" % (v["n"], v["ok"]))
    for s, c, ok in v["cand"]:
        print("    %-28s conf=%.4f ok=%s" % (s, c, ok))

# 组合3: 消融 (关掉 L4/L5 看 L3 是否退化)
print("\n" + "=" * 78)
print("组合3: **消融** L4 关闭 (off) -> L3 应无输入")
print("=" * 78)
p3 = Pipeline(build_default_spec(L2="detect.stub", L4="node.unified", L4_on=False))
print(p3.report(p3.run(img=img, obs39=obs39)))
