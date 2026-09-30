#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_scene_state.py — 把"当前场景理解"同步进全系统 (单一真源)

老倪 2026-09-19: 「你把你看到的, 理解的场景, 同步到全系统, 并由 L4 功能负责安全, L3 功能负责流程,
L2 功能负责操作」

产出 (一次写三处, 全部读真实来源, 不造数):
  ① data/scene_state.json        单一真源: 帧(来源/帧龄) + 几何(YOLO 框/TCP/阶段) + VLM 判读 + 层责任
  ② data/shared_memory.json meta.context   总装上下文 (任务规划器/异常推理器节点实时读它)
  ③ data/macro_memory.json  scene          顶层宏观记忆的"当前场景"段 (追加式, 不碰其它键)

层责任划分 (系统级约定, 与画布/引擎一致):
  L4 = 安全:  否决权 + 限幅 + 恢复预算 (谁都不许绕过; 动作最后一道闸门)
  L3 = 流程:  阶段序列/技能序列编排 + 长程规划 (决定"下一步做什么")
  L2 = 操作:  单步原子动作/解析控制 + 前馈 (决定"这一步怎么做")
用法: gui-venv311/bin/python tools/sync_scene_state.py [--vlm]   (--vlm 时同时跑一次 DeepSeek 判读)
"""
from __future__ import annotations

import argparse
import json
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME_CANDS = [os.path.expanduser("~/zmax_ss_remote/cam_rs.png"),
               os.path.expanduser("~/zmax_ss_remote/cam_fp.png")]
SCENE = os.path.join(REPO, "data", "scene_state.json")
SHARED = os.path.join(REPO, "data", "shared_memory.json")
MACRO = os.path.join(REPO, "data", "macro_memory.json")


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return {} if default is None else default


def _atomic(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def collect(vlm=False):
    """几何 + 视觉两路真数据"""
    out = {"ts": time.strftime("%F %T"), "epoch": time.time()}
    # ① 帧
    fp = next((f for f in FRAME_CANDS if os.path.exists(f)), None)
    if fp:
        age = time.time() - os.path.getmtime(fp)
        out["frame"] = {"path": os.path.basename(fp), "age_s": round(age, 2),
                        "fresh": bool(0 <= age <= 10),
                        "clock_ok": bool(age >= 0)}
    # ② 几何 (YOLO 框 + 编码器 TCP, 与 2D→3D 同一链)
    try:
        import sys
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import box3d_live_box as LB                                             # noqa: PLC0415
        line, info = LB.newest_state_line()
        if line is not None:
            out["pose"] = {"tcp": [round(float(v), 5) for v in line["tcp"]],
                           "pose_age_s": round(float(info), 2)}
            if fp:
                box, conf, cls, shp = LB.detect(fp, 0.4, 640)
                if box:
                    out["det"] = {"cls": cls, "conf": round(float(conf), 3),
                                  "box": [round(float(v), 1) for v in box],
                                  "center_px": [round((box[0] + box[2]) / 2, 1),
                                                round((box[1] + box[3]) / 2, 1)]}
                    sv = LB.ensure_solver(log=False)
                    if sv is not None:
                        try:
                            b3 = sv.predict_box3d(box, tcp=line["tcp"], quat=line["tcp_quat"])
                            out["box3d"] = {"mode": b3.get("mode"), "center": b3.get("center"),
                                            "sigma_mm": b3.get("sigma_mm"), "iou": b3.get("iou"),
                                            "note": b3.get("gaps") or b3.get("note")}
                        except Exception as e:                                  # noqa: BLE001
                            out["box3d"] = {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:                                                     # noqa: BLE001
        out["geom_error"] = f"{type(e).__name__}: {e}"
    # ③ 视觉 (最近一次判读; --vlm 时现场再判一次)
    if vlm and fp:
        try:
            import sys
            sys.path.insert(0, os.path.join(REPO, "src"))
            from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM  # noqa: PLC0415
            r = SceneVLM.get().describe(fp, {"stage": "现场", "instruction": "光模块插拔"})
            out["vlm"] = {"ok": bool(r.get("ok")), "src": r.get("src"),
                          "latency_ms": r.get("latency_ms"), "json": r.get("json"),
                          "why": r.get("why")}
        except Exception as e:                                                 # noqa: BLE001
            out["vlm"] = {"ok": False, "why": f"{type(e).__name__}: {e}"}
    else:
        try:
            last = None
            p = os.path.expanduser("~/zmax_data/vlm_calls.jsonl")
            if os.path.exists(p):
                for ln in open(p, encoding="utf-8"):
                    if ln.strip():
                        last = json.loads(ln)
            if last:
                out["vlm"] = {"ok": bool(last.get("ok")), "src": last.get("src"),
                              "latency_ms": last.get("latency_ms"), "json": last.get("json"),
                              "ts": last.get("ts"), "cached": True}
        except Exception:                                                      # noqa: BLE001
            pass
    # ④ 层责任 (系统级约定; 每条都指向真实实现)
    out["layer_duty"] = {
        "L4_安全": {"职责": "否决权/限幅/恢复预算 — 最后一道闸门, 上层不可绕过",
                    "实现": "tools/gui/state_space_sim_real.py (安全边界+否决) · "
                            "src/lerobot/policies/left_right/state_space/safety.py",
                    "状态": "在役 (限幅 + 否决计数)"},
        "L3_流程": {"职责": "阶段序列/技能序列编排 + 长程规划 (下一步做什么)",
                    "实现": "state_space/skills/atomic_skills.py + planner.py(TaskPlanner)",
                    "状态": "在役 (13 阶段状态机 + 242 原子技能)"},
        "L2_操作": {"职责": "单步原子动作/解析控制 + 前馈加速 (这一步怎么做)",
                    "实现": "state_space/parallel.py + execution.py",
                    "状态": "在役 (解析控制 + 前馈 MLP 快通道)"},
        "人机在环红线": "任何机械臂动作须操作员确认; operation_state=drag 时一律不下发",
    }
    return out


def sync(vlm=False):
    st = collect(vlm=vlm)
    _atomic(SCENE, st)
    # 总装上下文 (任务规划器/异常推理器节点读 meta.context)
    sh = _load(SHARED)
    j = (st.get("vlm") or {}).get("json") or {}
    det = st.get("det") or {}
    ctx = (f"场景 {st.get('ts')}: 帧{st.get('frame', {}).get('path')}"
           f"(龄{st.get('frame', {}).get('age_s')}s) | YOLO {det.get('cls')} conf{det.get('conf')} "
           f"@{det.get('center_px')} | TCP {st.get('pose', {}).get('tcp')} | "
           f"3D {st.get('box3d', {}).get('mode')} | 视觉: " +
           (f"{j.get('目标是什么', '')}·{'在夹爪上吗' if '在夹爪上吗' in j else '在夹爪里'}="
            f"{j.get('在夹爪上吗', j.get('目标是否在夹爪里', '?'))}·质量{len([k for k, v in (j.get('画面质量') or {}).items() if v])}项异常"
            if j else "未判读"))
    sh.setdefault("meta", {})["context"] = ctx
    sh["meta"]["scene_synced_at"] = st["ts"]
    _atomic(SHARED, sh)
    # 顶层宏观记忆: 追加式写 scene 段 (不碰 engineering/knowledge/...)
    mc = _load(MACRO)
    mc.setdefault("version", 1)
    mc["scene"] = {"ts": st["ts"], "frame": st.get("frame"), "det": st.get("det"),
                   "pose": st.get("pose"), "box3d": st.get("box3d"),
                   "vlm": {"ok": (st.get("vlm") or {}).get("ok"),
                            "src": (st.get("vlm") or {}).get("src"),
                            "json": (st.get("vlm") or {}).get("json")},
                   "layer_duty": st["layer_duty"]}
    mc.setdefault("meta", {})["updated"] = st["ts"]
    _atomic(MACRO, mc)
    # 回读校验
    back = _load(SCENE)
    ok = back.get("ts") == st["ts"]
    return {"ok": ok, "scene": SCENE, "shared_context": ctx[:160],
            "macro_keys": sorted(_load(MACRO).keys())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vlm", action="store_true", help="现场再跑一次 DeepSeek 判读 (慢, 冷启 60~134s)")
    a = ap.parse_args()
    r = sync(vlm=a.vlm)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print("\n层责任 (系统级约定):")
    st = _load(SCENE)
    for k, v in (st.get("layer_duty") or {}).items():
        print(f"  {k}: {v if isinstance(v, str) else v.get('职责')}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
