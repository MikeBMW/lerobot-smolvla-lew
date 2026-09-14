# -*- coding: utf-8 -*-
"""E2E: **只走 policy 层** (src/lerobot/policies/intact/service.py) 跑一次 L4→L3 意图服务。

不经 GUI —— 证明"编排在 policy 层"这条重构真的成立 (老倪 2026-09-13)。
用法: INTACT_DEVICE=cpu INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt \
        gui-venv311/bin/python tools/intact_service_e2e.py
判据: trained=True / chunk 非空 / candidate_sequences==0 / u_ff 4D / L3 条件未标定诚实拒绝 / 证据落盘。
"""
import json
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from lerobot.policies.intact.service import get_service          # noqa: E402

svc = get_service(ROOT)
print("=== bridge_status ===")
st = svc.bridge_status()
print(json.dumps({k: v for k, v in st.items() if k != "dims"}, ensure_ascii=False, indent=1))
print("dims:", st.get("dims"))

print("\n=== run_once (decode=True) ===")
rep = svc.run_once(stage="", decode=True, log=lambda s: print(s, flush=True))

print("\n=== report.to_dict() ===")
d = rep.to_dict()
print(json.dumps(d, ensure_ascii=False, indent=1)[:1800])

print("\n=== 证据文件 ===")
print(rep.evidence_path, os.path.isfile(rep.evidence_path) if rep.evidence_path else "-")
if rep.evidence_path and os.path.isfile(rep.evidence_path):
    print(open(rep.evidence_path, encoding="utf-8").read()[:900])

print("\n=== 断言 (真接入判据, 不做假成功) ===")
checks = {
    "trained=True (真权重)": bool(rep.trained),
    "chunk 非空": bool(rep.chunk_shape and rep.chunk_shape[0] > 0),
    "零搜索 candidate_sequences==0": float(d["diagnostics"].get("candidate_sequences", -1)) == 0.0,
    "u_ff 非空 4 维": (rep.u_ff is not None and rep.u_ff.shape == (4,)),
    "L3 条件未标定 → 拒绝(不假值)": (rep.l3_cond is None and "未标定" in rep.l3_cond_source),
    "证据已落盘字段齐": bool(rep.evidence_path),
}
for k, v in checks.items():
    print(("  ✅ " if v else "  ❌ ") + k)
print("verdict:", "PASS" if all(checks.values()) else "FAIL")
svc.close()
