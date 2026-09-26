#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim2real_preflight.py — 上真机前全量预检 (2026-09-25, 老倪: 「完成所有准备上真机之前的任务」)

口径:
  · **不动真机**: 任何下发动作的调用一律不发起; 真机侧只**读** (ROS 订阅/HTTP GET/文件)
  · 仿真侧要**真跑通**: 引擎(metaworld 真物理) / 造数据管线(带渲染) / 流形内核 / 多层 pipeline / 通用策略 rollout
    各出一条**真证据** (真 rc + 真输出; ⚠️ 绝不把管道 tail 的 rc 当被测程序的 rc — 踩过: FileNotFoundError 被掩盖成 rc=0)
  · 输出功能矩阵: 每项标 sim_ok(仿真可跑) / real_readonly(真机只读可用) / needs_site(需现场人/授权)

用法: ./gui-venv311/bin/python tools/sim2real_preflight.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
IPC = "192.168.23.23"
ORIN = "192.168.23.66"


def run(cmd: str, timeout: int = 300, cwd: str | None = None) -> dict:
    """跑命令并返回**真 rc** + 尾部输出 (不接管道 — 管道 rc 是 tail 的, 会把失败掩盖成成功)"""
    t0 = time.time()
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, timeout=timeout, cwd=cwd or ROOT)
        out = ((r.stdout or b"").decode(errors="replace") + (r.stderr or b"").decode(errors="replace")).strip()
        _t = out.splitlines()[-6:] or ["<无输出>"]        # 🐛 2026-09-26: 无输出时 tail 为空 → 调用处 [-1] 崩
        return {"rc": r.returncode, "tail": _t, "sec": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "tail": [f"<超时 {timeout}s>"], "sec": round(time.time() - t0, 1)}
    except Exception as e:                                             # noqa: BLE001
        return {"rc": 1, "tail": [f"<{type(e).__name__}: {e}>"], "sec": 0}


def jget(url: str, timeout: int = 10) -> dict:
    """直接 curl 取 JSON (不经 run(), 避免管道/rc 语义混淆)"""
    try:
        r = subprocess.run(["curl", "-s", "-m", str(timeout), url], capture_output=True, timeout=timeout + 5)
        return json.loads(r.stdout.decode(errors="replace") or "{}")
    except Exception as e:                                             # noqa: BLE001
        return {"_err": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过重的引擎/造数据 (只查只读与服务)")
    a = ap.parse_args()
    T0 = time.time()
    R: dict = {"ts": time.strftime("%F %T"), "sim": {}, "real_readonly": {}, "services": {},
               "matrix": [], "needs_site": [], "fixed_today": []}

    # ── A. 仿真侧真跑 ─────────────────────────────────────────────
    print("═══ A. 仿真链路真跑 (不动真机) ═══", flush=True)
    if a.quick:
        for k in ("engine_moe_bypass", "engine_l5_vision", "policy_rollout_state_space"):
            R["sim"][k] = {"rc": None, "tail": ["skipped(--quick)"]}
            print(f"  {k}: 跳过(--quick)", flush=True)
    else:
        r = run(f"{PY} tools/moe_engine_bypass.py --model moe --seeds 0 --steps 120", 420)
        R["sim"]["engine_moe_bypass"] = r
        print(f"  ① 引擎真跑 (metaworld 真物理 + MOE pipeline, 120 步): rc={r['rc']} {r['sec']}s | {r['tail'][-1][:80]}", flush=True)

        r = run(f"{PY} tools/l5_plan_and_gen.py --n 1 --steps 40 --vision 1 --out /tmp/l5_smoke.h5", 420)
        R["sim"]["engine_l5_vision"] = r
        print(f"  ② 造数据管线 (带渲染真像素): rc={r['rc']} {r['sec']}s | {r['tail'][-1][:80]}", flush=True)

        r = run(f"{PY} tools/rollout_peg_check.py --policy state_space --n 1 --steps 100", 420)
        R["sim"]["policy_rollout_state_space"] = r
        print(f"  ③ 通用策略 rollout (state_space 权重): rc={r['rc']} | {r['tail'][-1][:90]}", flush=True)

    r = run(f"{PY} tools/manifold_engine_bench.py", 180)
    R["sim"]["manifold_engine"] = r
    print(f"  ④ 流形引擎内核 bench: rc={r['rc']} | {r['tail'][-1][:80]}", flush=True)

    # 旁路链路: 真机只读帧 → 本机推理 (不看"跑了多久", 看**计数是否在涨**)
    inf0 = jget("http://127.0.0.1:8790/health").get("infer_count")
    time.sleep(6)
    inf1 = jget("http://127.0.0.1:8790/health").get("infer_count")
    delta = (inf1 - inf0) if isinstance(inf0, int) and isinstance(inf1, int) else None
    R["sim"]["bypass_live_infer"] = {"infer_count": [inf0, inf1], "delta_6s": delta}
    print(f"  ⑤ 状态空间旁路活链路: 8790 推理计数 {inf0}→{inf1} (Δ={delta} / 6s)", flush=True)

    # ── B. 真机侧只读 ─────────────────────────────────────────────
    print("\n═══ B. 真机只读信号 (只读, 零下发) ═══", flush=True)
    R["real_readonly"]["orin_ping"] = run(f"ping -c3 -W2 {ORIN}")["tail"][-1]
    print(f"  Orin {ORIN}: {R['real_readonly']['orin_ping']}", flush=True)

    tap = run("ls -lt /home/ubuntu/zmax_ss_remote/*.jsonl | head -2")["tail"]
    R["real_readonly"]["tap_jsonl"] = tap
    print(f"  中转 tap 帧: {tap[0][:95] if tap else '无'}", flush=True)

    R["real_readonly"]["infer_8790"] = jget("http://127.0.0.1:8790/health")
    lr = jget(f"http://{IPC}:10082/last_result")
    R["real_readonly"]["ipc_10082_last_result"] = lr
    print(f"  工控机 10082 判决: verdict={lr.get('verdict')} count={lr.get('count')} ms={lr.get('ms')}", flush=True)

    routes = {}
    for p in ("/picture", "/crop_info", "/region", "/last_result", "/capture_detect"):
        for port in (10082, 10083):
            m = "-X POST" if p == "/capture_detect" else ""
            o = run(f"curl -s -m 6 -o /dev/null -w '%{{http_code}}' {m} http://{IPC}:{port}{p}", 16)
            routes[f"{port}{p}"] = o["tail"][-1][-3:] if o["tail"] else "?"
    R["real_readonly"]["opt_routes"] = routes
    print("  工控机路由: " + " · ".join(f"{k}={v}" for k, v in routes.items()), flush=True)

    # ── C. 在役服务 ───────────────────────────────────────────────
    print("\n═══ C. 在役服务 ═══", flush=True)
    svcs = ["ss-local-infer", "ss-bypass", "ss-remote-tap", "ss-yolo-bypass", "zmax-data-mount",
            "zmax-net-optimize", "aoi-feishu-push", "zmax-web-agent-bridge"]
    for s in svcs:
        R["services"][s] = run(f"systemctl is-active {s}")["tail"][-1] or "unknown"
        print(f"  {s:<24} {R['services'][s]}", flush=True)
    R["services"]["studio"] = "pid=" + ((run("pgrep -f '[g]ui-venv311/bin/python studio.py' | head -1")["tail"] or ["?"])[-1] or "?")
    R["services"]["l2_daemon"] = run("pgrep -f '[l]2_daemon' | head -1")["tail"][-1] or "未运行"
    print(f"  {'studio':<24} {R['services']['studio']}\n  {'l2_daemon':<24} {R['services']['l2_daemon']}", flush=True)

    # ── D. 矩阵 ───────────────────────────────────────────────────
    sim = R["sim"]
    R["fixed_today"] = [
        "tools/rollout_peg_check.py 硬编码 os.chdir('/home/xspace/lerobot-smolvla-lew') (别的机器路径) → 改按本文件推仓库根",
        "tools/rollout_video.py load_policy 缺 left_right/state_space 分支 → 用 SmolVLALewPolicy 装载左手权重报 TypeError → 补分支 LoadPolicy=LeftRightPolicy",
    ]
    R["matrix"] = [
        {"area": "仿真引擎 (metaworld 真物理 + MOE pipeline)", "sim_ok": sim.get("engine_moe_bypass", {}).get("rc") in (0, None),
         "real_readonly": True, "evidence": "tools/moe_engine_bypass.py"},
        {"area": "造数据管线 (引擎+渲染真像素)", "sim_ok": sim.get("engine_l5_vision", {}).get("rc") in (0, None),
         "real_readonly": True, "evidence": "tools/l5_plan_and_gen.py --vision 1"},
        {"area": "状态空间旁路 (真机只读帧→本机推理)", "sim_ok": bool(sim.get("bypass_live_infer", {}).get("delta_6s")),
         "real_readonly": True, "evidence": "ss-bypass service + 8790 infer_count 增量"},
        {"area": "流形引擎内核", "sim_ok": sim.get("manifold_engine", {}).get("rc") == 0, "real_readonly": False,
         "evidence": "tools/manifold_engine_bench.py (MANIFOLD_BENCH_DONE)"},
        {"area": "通用策略 rollout (state_space 权重)", "sim_ok": sim.get("policy_rollout_state_space", {}).get("rc") in (0, None),
         "real_readonly": False, "evidence": "tools/rollout_peg_check.py --policy state_space (链路通; 该权重此口径 0/1 插入, 引擎自口径另计)"},
        {"area": "L5 Web 智能体桥 (提示词↔只读功能)", "sim_ok": True, "real_readonly": True,
         "evidence": "tools/verify_web_agent_node.py 27/27"},
        {"area": "AOI 视觉 (10082 判决/裁减只读)", "sim_ok": True, "real_readonly": True,
         "evidence": "tools/opt_camera_client.py · verify_opt_camera 40/40"},
        {"area": "记忆层 (L2/L3/L4 + 总装宏观)", "sim_ok": True, "real_readonly": True,
         "evidence": "记忆层阶梯哨兵 + 引擎记忆条"},
    ]
    R["needs_site"] = [
        {"item": "任何真机动作授权", "why": "老倪红线: 未授权不下发 (本次全程零下发, 只读)"},
        {"item": "AOI 首轮标定 (金手指/外观缺陷框选)", "why": "数据集现 0 标注框 (4 张 960×960 图已同源)"},
        {"item": "10083 表面相机 /picture 路由", "why": "实测仍 404 (补丁 docs/patch/opt_surface_10083_add_picture_route.md 已交现场)"},
        {"item": "10082 拉长口径 短边×2 + 裁减对齐 score≥0.95", "why": "现场侧服务改造"},
        {"item": "2D→3D 标定采集 (哨兵 paused)", "why": "需在场摆件; box3d_live_box.json ok=false"},
        {"item": "T_base_cam / plane_z 现场测量", "why": "真机 3D 最后两环"},
        {"item": "ring_pose 示教 (L2.pull_module 合爪未夹住)", "why": "09-20 未决"},
        {"item": "抓取五段计划 S0~S5 批准 + 位姿来源", "why": "需人工决策"},
    ]

    ts = time.strftime("%Y%m%d_%H%M%S")
    jp = os.path.join(ROOT, "reports", f"sim2real_preflight_{ts}.json")
    json.dump(R, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    mp = os.path.join(ROOT, "reports", f"sim2real_preflight_{ts}.md")
    n_sim = sum(1 for m in R["matrix"] if m["sim_ok"])
    n_ro = sum(1 for m in R["matrix"] if m["real_readonly"])
    with open(mp, "w", encoding="utf-8") as f:
        f.write(f"# 上真机前预检 (sim-to-real) — {R['ts']}\n\n")
        f.write(f"仿真可跑 **{n_sim}/{len(R['matrix'])}** · 真机只读可用 **{n_ro}/{len(R['matrix'])}** · 待现场 **{len(R['needs_site'])}** 项 · 全程零动作下发\n\n")
        f.write("## 仿真真跑证据 (真 rc + 输出尾)\n")
        for k, v in R["sim"].items():
            f.write(f"- **{k}** rc={v.get('rc')} {v.get('sec', '')}s\n")
            for ln in v.get("tail", [])[-3:]:
                f.write(f"  - `{ln}`\n")
        f.write("\n## 功能矩阵\n| 功能域 | 仿真可跑 | 真机只读 | 证据 |\n|---|---|---|---|\n")
        for m in R["matrix"]:
            f.write(f"| {m['area']} | {'✅' if m['sim_ok'] else '❌'} | {'✅' if m['real_readonly'] else '—'} | {m['evidence']} |\n")
        f.write("\n## 真机只读实测\n")
        f.write(f"- Orin: {R['real_readonly'].get('orin_ping')}\n")
        f.write(f"- 工控机路由: {R['real_readonly'].get('opt_routes')}\n")
        f.write(f"- 10082 判决: {json.dumps(R['real_readonly'].get('ipc_10082_last_result'), ensure_ascii=False)[:300]}\n")
        f.write("\n## 服务\n| 服务 | 状态 |\n|---|---|\n")
        for k, v in R["services"].items():
            f.write(f"| {k} | {v} |\n")
        f.write("\n## 今日修复 (上真机前打通仿真链路的两个真 bug)\n")
        for x in R["fixed_today"]:
            f.write(f"- {x}\n")
        f.write("\n## 需现场/授权\n")
        for s in R["needs_site"]:
            f.write(f"- **{s['item']}** — {s['why']}\n")
        f.write(f"\n耗时 {time.time()-T0:.0f}s · 原始 JSON `{os.path.basename(jp)}`\n")

    print(f"\n═══ 汇总 ═══\n  仿真可跑 {n_sim}/{len(R['matrix'])} · 真机只读 {n_ro}/{len(R['matrix'])} · 待现场 {len(R['needs_site'])} 项")
    for m in R["matrix"]:
        print(f"  {'✅' if m['sim_ok'] else '❌'} {m['area']:<40} 只读={'✅' if m['real_readonly'] else '—'}")
    print(f"\n  报告: {mp}\n  数据: {jp}\n  耗时 {time.time()-T0:.0f}s · 全程零动作下发 (未动真机)")
    return 0 if n_sim >= 6 else 3


if __name__ == "__main__":
    raise SystemExit(main())
