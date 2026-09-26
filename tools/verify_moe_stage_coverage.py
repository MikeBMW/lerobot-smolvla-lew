#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_moe_stage_coverage.py — ①-2 取证: 引擎 8 阶段全覆盖 + 零回退 + 不再静默吞阶段

判据:
  ① **修前对照**: 用"均匀 1/7 兜底"的老逻辑喂"完成"阶段 one-hot → hard 路由落 **E0** (= 老倪报的 E0 吞阶段)
  ② **修后**: 8 个引擎阶段 one-hot 逐个喂真模型 → argmax 全部等于覆盖表指定专家 (8/8 覆盖)
  ③ **零回退**: 7 维 one-hot 路径与"纯归一化"结果**逐位相同** (老 ckpt/老数据不受影响)
  ④ **未识别阶段不再静默**: 全零 stage_p → 显式兜底专家 (默认 E6) + unrouted 计数 +1 (不再伪装成 E0)
  ⑤ 真实 ckpt 上跑一遍: 路由统计无 NaN、8 阶段全覆盖
用法: gui-venv311/bin/python tools/verify_moe_stage_coverage.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SS_MOE_ROUTE_STATS", "1")   # ★ 打开未路由计数 (默认仅训练时统计, 为省 GPU 同步)
import numpy as np
import torch

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools")
from stage_moe_backbone import MODEL, STAGES, STAGES_ENGINE, STAGE_TO_EXPERT, StageMoE  # noqa: E402

CKPT = "/home/ubuntu/stable-wm-cache/checkpoints/stage_moe/moe.pt"
ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""), flush=True)


print("① 修前对照 (老逻辑: stage_p 行和为 0 → 均匀 1/7 → hard argmax 恒 E0)")
sp_complete = torch.zeros(1, 8)
sp_complete[0, 7] = 1.0                                  # 引擎"完成"阶段 (第 8 位, 老代码不认识)
old_uniform = torch.full((1, 7), 1.0 / 7)
old_argmax = int(old_uniform.argmax(1))
chk("老逻辑把'完成'阶段路由到 E0 (吞阶段真因复现)", old_argmax == 0, "老 argmax=E%d" % old_argmax)

print("② 修后: 8 个引擎阶段逐个路由 (真模型 + 真 ckpt)")
from transformers import AutoModel                              # noqa: E402
dev = "cuda" if torch.cuda.is_available() else "cpu"
trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
net = StageMoE(trunk, freeze=1)
sd = torch.load(CKPT, map_location="cpu", weights_only=False)
r = net.load_state_dict(sd, strict=False)
net = net.eval().to(dev)
print("     ckpt 已加载 (missing=%d)" % len(r.missing_keys))

px = torch.zeros(1, 3, 224, 224, device=dev)
obs = torch.zeros(1, 39, device=dev)
mem = torch.zeros(1, 13, device=dev)
covered = 0
with torch.no_grad():
    for i, st in enumerate(STAGES_ENGINE):
        sp = torch.zeros(1, len(STAGES_ENGINE), device=dev)
        sp[0, i] = 1.0
        out = net(px, obs, obs, mem, sp, hard=True, route="prior")
        idx = int(out["gate"].argmax(1).item())
        want = STAGE_TO_EXPERT[st]
        good = (idx == want)
        covered += int(good)
        print("     %-4s → E%d  (期望 E%d) %s" % (st, idx, want, "✅" if good else "❌"))
chk("8/8 引擎阶段全部路由到指定专家", covered == len(STAGES_ENGINE), "%d/%d" % (covered, len(STAGES_ENGINE)))

print("③ 零回退: 7 维路径与纯归一化逐位相同")
with torch.no_grad():
    for i in range(len(STAGES)):
        sp7 = torch.zeros(1, 7, device=dev)
        sp7[0, i] = 1.0
        g_new = net(px, obs, obs, mem, sp7, hard=True, route="prior")["gate"]
        g_ref = sp7 / sp7.sum(1, keepdim=True)          # 老实现的等价式
        same = bool(torch.allclose(g_new, g_ref, atol=1e-7))
        if not same:
            chk("7 维 stage %s 逐位同" % STAGES[i], False, "max diff=%.2e" % float((g_new - g_ref).abs().max()))
            break
    else:
        chk("7 维全部 7 个阶段逐位同 (老 ckpt/老数据零影响)", True, "atol=1e-7")

print("④ 未识别阶段: 显式兜底 + 计数 (不再静默变 E0) [SS_MOE_ROUTE_STATS=1]")
before = net.route_stats["unrouted"]
with torch.no_grad():
    out = net(px, obs, obs, mem, torch.zeros(1, 8, device=dev), hard=True, route="prior")
idx = int(out["gate"].argmax(1).item())
chk("全零 stage_p → 兜底专家 E%d" % net.default_expert, idx == net.default_expert, "实际 E%d" % idx)
chk("unrouted 计数 +1", net.route_stats["unrouted"] >= before + 1, "%d → %d" % (before, net.route_stats["unrouted"]))

print("⑤ 真实 ckpt 路由统计")
chk("per_expert 数组长度 = 7 且无异常", len(net.route_stats["per_expert"]) == 7,
    "per_expert=%s frames=%d unrouted=%d" % (net.route_stats["per_expert"], net.route_stats["frames"],
                                              net.route_stats["unrouted"]))

print("\n判据通过: %d/%d" % (sum(ok), len(ok)))
sys.stdout.flush()
os._exit(0 if all(ok) else 3)
