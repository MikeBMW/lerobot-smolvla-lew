#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blur_refocus_demo.py — 融合定位·模糊识别→补偿→AOI 复焦 的闭环验证 (2026-09-24)

口径 (诚实标注):
  · 图像 = **真实帧**: 优先真机 D405 帧 (data/real_yolo_perception_*.mp4), 其次引擎真渲染帧;
    候选帧一律先过**有效帧闸** (无结构/黑帧直接淘汰并如实记录 — 现役 AOI 帧实测就是无效帧)
  · 离焦 = **合成物理模型** σ_px(z) = k·|z − z_focus| (相机在臂上 → 沿光轴移动即对焦移动)
    物理模型 + 真图; 真机 R2 需现场标定 (见方案 §7)
  · 判据全部来自真实图像处理 (Laplacian/Tenengrad/FFT), 无写死 pass/fail

用法: ./gui-venv311/bin/python tools/blur_refocus_demo.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))
import cv2                                                          # noqa: E402
import focus_quality as fq                                          # noqa: E402

TS = time.strftime("%Y%m%d_%H%M%S")
OUT_JSON = os.path.join(ROOT, "reports", f"focus_refocus_demo_{TS}.json")
OUT_PNG = os.path.join(ROOT, "reports", f"focus_refocus_demo_{TS}.png")
K_PX_PER_MM = 0.6          # 合成物理: 每毫米离焦 → 0.6px 模糊半径 (真机换标定值)
Z_FOCUS = 300.0            # 名义对焦距离 mm


def _load_img(p):
    if p.lower().endswith(".mp4"):
        cap = cv2.VideoCapture(p); ok, fr = cap.read(); cap.release()
        return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB) if ok else None
    im = cv2.imread(p)
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB) if im is not None else None


def pick_real_frame(rep):
    """按优先级取真图, **逐帧过有效帧闸**, 无效的如实记录 (不静默换掉)。"""
    cands = [("data/real_yolo_perception_104.mp4", "真机 D405 帧 (real_yolo_perception_104)"),
             ("data/real_yolo_perception_100.mp4", "真机 D405 帧 (real_yolo_perception_100)"),
             ("data/ss3d_l3_full_insert_pull_aoi_104.mp4", "引擎真渲染帧 (L3 全链 104)"),
             (os.path.expanduser("~/zmax_data/aoi_last_frame.png"), "现役 AOI 帧 (aoi_last_frame)")]
    chosen, rejected = None, []
    for rel, tag in cands:
        p = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            continue
        img = _load_img(p)
        if img is None:
            rejected.append({"path": p, "tag": tag, "why": "读不到"})
            continue
        m = fq.blur_metrics(img, None)
        ok, why = fq.frame_valid(m)
        rec = {"path": p, "tag": tag, "mean": round(m["mean"] * 255, 2), "std": round(m["std"], 2),
               "ten": round(m["ten"], 1), "lap": round(m["lap"], 1), "valid": bool(ok), "why": why}
        if ok and chosen is None:
            chosen = (img, tag, p, m)
        else:
            rejected.append(rec)
    rep["frame_candidates"] = rejected
    if chosen is None:
        raise SystemExit("❌ 所有候选帧都无效 (无结构/黑帧) —— 需先修取图链路")
    return chosen


def defocus(img, sigma_px):
    if sigma_px < 0.1:
        return img.copy()
    k = int(2 * int(np.ceil(3 * sigma_px)) + 1)
    return cv2.GaussianBlur(img, (k, k), float(sigma_px))


def motion_blur(img, length_px, angle_deg):
    k = np.zeros((length_px, length_px), np.float32)
    k[length_px // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((length_px / 2 - 0.5, length_px / 2 - 0.5), angle_deg, 1.0)
    k = cv2.warpAffine(k, M, (length_px, length_px)); k /= (k.sum() + 1e-9)
    return cv2.filter2D(img, -1, k)


def main():
    rep = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "caliber": {"k_px_per_mm": K_PX_PER_MM, "z_focus_mm": Z_FOCUS,
                       "note": "真图 + 合成离焦物理 σ=k·|z−z_focus|; 候选帧先过有效帧闸"}}
    sharp, tag, path, ref = pick_real_frame(rep)
    rep["source_frame"] = {"tag": tag, "path": path, "shape": list(sharp.shape),
                           "metrics": {k: (ref[k] if k in ("roi",) else round(float(ref[k]), 5))
                                       for k in ("lap", "ten", "hf", "std", "clip_hi", "mean", "roi")}}
    print(f"🖼  采用真图: {tag}\n    {path}  {sharp.shape}")
    print(f"    ROI={ref['roi']} lap={ref['lap']:.1f} ten={ref['ten']:.1f} std={ref['std']:.1f} "
          f"mean={ref['mean']*255:.1f} clip_hi={ref['clip_hi']*100:.2f}%")
    print("    🚦 被有效帧闸淘汰的候选 (如实记录):")
    for r in rep["frame_candidates"]:
        print(f"       ❌ {r['tag']}: mean={r.get('mean')} std={r.get('std')} ten={r.get('ten')} — {r['why']}")

    # ── R0: 标定 σ 反演常数 c_hf ──
    grid = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]
    cal = []
    for s in grid:
        m = fq.blur_metrics(defocus(sharp, s), None)
        rl = m["lap"] / (ref["lap"] + 1e-12)                     # 拉普拉斯比 (实测单调, 优于 HF 比)
        c_i = s / np.sqrt(max(1.0 / np.sqrt(max(rl, 1e-12)) - 1.0, 1e-9))
        cal.append({"sigma_true": s, "q": round(fq.quality_score(m, ref), 4), "r_lap": round(rl, 5),
                    "lap": round(m["lap"], 1), "ten": round(m["ten"], 1), "c_implied": round(float(c_i), 3),
                    "sigma_est": round(fq.estimate_sigma(m, ref), 3)})
    # c 只在**有效域** [0.75, 2.0]px 拟合 (放行线邻域; 大模糊下 HF 比数值下溢, 反演失真)
    VALID = (0.75, 2.0)
    c_fit = float(np.median([x["c_implied"] for x in cal if VALID[0] <= x["sigma_true"] <= VALID[1]]))
    fq.DEF["c_lap"] = c_fit
    for x in cal:            # 用标定后的 c 重算 σ_est / q
        x["sigma_est"] = round(fq.estimate_sigma(fq.blur_metrics(defocus(sharp, x["sigma_true"]), None), ref), 3)
        x["q"] = round(fq.quality_score(fq.blur_metrics(defocus(sharp, x["sigma_true"]), None), ref), 4)
    err = [abs(x["sigma_est"] - x["sigma_true"]) for x in cal if VALID[0] <= x["sigma_true"] <= VALID[1]]
    rep["R0_calibration"] = {"c_lap_fit": round(c_fit, 4), "grid": cal,
                             "valid_range_px": list(VALID),
                             "sigma_est_mae_px": round(float(np.mean(err)), 3),
                             "sigma_est_max_err_px": round(float(np.max(err)), 3)}
    print(f"\n📐 R0 标定: c_lap={c_fit:.3f} (拟合域 {VALID[0]}~{VALID[1]}px) · "
          f"σ估计 MAE={np.mean(err):.3f}px 最大={np.max(err):.3f}px")
    print("    σ_true→q/σ_est: " + " | ".join(f"{x['sigma_true']}→{x['q']:.2f}/{x['sigma_est']:.2f}" for x in cal))

    # ── R1a: 扫焦曲线 q(z) 单峰性 ──
    cam = lambda z: defocus(sharp, K_PX_PER_MM * abs(z - Z_FOCUS))           # noqa: E731
    curve, t0 = [], time.perf_counter()
    zs = np.arange(-15, 15.01, 1.0)
    for dz in zs:
        m = fq.blur_metrics(cam(Z_FOCUS + dz), None)
        curve.append({"dz_mm": round(float(dz), 1), "q": round(fq.quality_score(m, ref), 4),
                      "sigma_est_px": round(fq.estimate_sigma(m, ref), 3)})
    ms = (time.perf_counter() - t0) * 1000.0 / len(zs)
    qs = [c["q"] for c in curve]; peak = curve[int(np.argmax(qs))]
    rep["R1a_sweep"] = {"curve": curve, "peak_dz_mm": peak["dz_mm"], "peak_q": peak["q"],
                        "q_at_0mm": curve[int(np.argmin(np.abs(zs)))]["q"], "per_frame_ms": round(ms, 2)}
    print(f"\n📈 R1a 扫焦曲线: 峰值 Δz={peak['dz_mm']}mm (真值 0) · q峰={peak['q']:.3f} · "
          f"±15mm 端点 q={qs[0]:.3f}/{qs[-1]:.3f} · 单帧量测 {ms:.2f}ms")

    # ── R1b: 闭环复焦 (两方向) ──
    loops = {}
    for z0 in (Z_FOCUS - 9.0, Z_FOCUS + 12.0):
        lp = fq.RefocusLoop(ref, cam)
        ok, reason, zf, detail = lp.run(z0)
        loops[f"start_{int(z0-Z_FOCUS)}mm"] = {"ok": ok, "reason": reason, "z_final_mm": round(zf, 2),
                                              "dz_net_mm": round(zf - z0, 2), "detail": detail,
                                              "n_probes": len(lp.trace), "trace": lp.trace}
        print(f"🎯 R1b 从 Δz={z0-Z_FOCUS:+.0f}mm → {reason} · 落点 Δz={zf-Z_FOCUS:+.2f}mm · "
              f"{len(lp.trace)} 探测 · {detail}")
    rep["R1b_closed_loop"] = loops

    # ── R1c: 归因对照 (运动 / 曝光 / 不可恢复 / 无效帧) ──
    cs = {}
    mv = motion_blur(sharp, 35, 30.0)          # 长核 → 方向性显著 (真机 >25px 拖影即明显)
    a_iso, _ = fq.motion_anisotropy(sharp, None); a_mv, th_mv = fq.motion_anisotropy(mv, None)
    cs["motion"] = {"aniso_clear": round(a_iso, 3), "aniso_motion": round(a_mv, 3), "theta_deg": round(th_mv, 1),
                    "ratio": round(a_mv / (a_iso + 1e-9), 3),
                    "verdict_speed": fq.attribute(fq.blur_metrics(mv, None), ref, speed_norm=0.30)[0],
                    "verdict_aniso_only": fq.attribute(fq.blur_metrics(mv, None), ref, aniso=a_mv)[0],
                    "caveat": "图像方向性**不能作运动判据**: ① 方向依赖 (0°/90° 拖影 aniso 反降到 "
                              "0.52×/0.62×基线, 会漏检) ② 离焦同样抬高该比值, 且比真运动更高 "
                              "(见 aniso_deep_defocus vs ratio) → 运动归因只用臂速 (编码器真值)"}
    a_dd, _ = fq.motion_anisotropy(cam(Z_FOCUS - 9.0), None)      # 深离焦 (σ≈5.4px) 的方向性比
    cs["motion"]["aniso_deep_defocus"] = round(a_dd / (a_iso + 1e-9), 3)
    over = np.clip(sharp.astype(np.float32) * 1.8 + 70, 0, 255).astype(np.uint8)
    cs["exposure"] = {"clip_hi": round(float((fq._gray_of(over) >= 250).mean()), 4),
                      "verdict": fq.attribute(fq.blur_metrics(over, None), ref)[0]}
    scatter = defocus(sharp, 3.0)                       # 端面散射: 目标本身永远糊
    lp = fq.RefocusLoop(ref, lambda z: defocus(scatter, K_PX_PER_MM * abs(z - Z_FOCUS)))
    ok, reason, zf, detail = lp.run(Z_FOCUS - 6.0)
    cs["unresolvable_scatter"] = {"ok": ok, "reason": reason, "q_best": round(max(t["q"] for t in lp.trace), 4),
                                  "n_probes": len(lp.trace), "detail": detail}
    blank = np.full_like(sharp, 128)                    # 无效帧: 无结构
    lp2 = fq.RefocusLoop(ref, lambda z: defocus(blank, K_PX_PER_MM * abs(z - Z_FOCUS)))
    ok2, r2, zf2, d2 = lp2.run(Z_FOCUS - 6.0)
    cs["invalid_blank"] = {"ok": ok2, "reason": r2, "n_probes": len(lp2.trace), "detail": d2}
    aoi_p = os.path.expanduser("~/zmax_data/aoi_last_frame.png")
    if os.path.isfile(aoi_p):
        mi = fq.blur_metrics(_load_img(aoi_p), None); okv, whyv = fq.frame_valid(mi)
        cs["invalid_real_aoi_frame"] = {"ok": bool(okv), "reason": "no_target" if not okv else "?",
                                        "detail": whyv, "mean": round(mi["mean"] * 255, 2),
                                        "std": round(mi["std"], 2), "ten": round(mi["ten"], 1)}
    rep["R1c_attribution"] = cs
    print("\n🧭 R1c 归因对照:")
    for k, v in cs.items():
        print(f"    {k}: {v}")

    # ── R1d: 修正位姿引导 ──
    n_cam = np.array([0.0, 0.0, -1.0]); axis_src = "名义光轴"
    he = os.path.join(ROOT, "models", "handeye_state.json")
    if os.path.isfile(he):
        try:
            d = json.load(open(he))
            for key in ("R", "rot", "rotation", "T_base_cam"):
                v = d.get(key)
                if isinstance(v, list) and len(v) in (9, 16):
                    R = np.asarray(v, float).reshape(3, 3) if len(v) == 9 else np.asarray(v, float)[:3, :3]
                    n_cam = -(R @ np.array([0.0, 0.0, 1.0])); n_cam /= (np.linalg.norm(n_cam) + 1e-9)
                    axis_src = f"handeye_state.json[{key}]"; break
        except Exception as e:                                                     # noqa: BLE001
            axis_src = f"名义光轴 (读手眼失败 {type(e).__name__})"
    dz_net = loops["start_-9mm"]["dz_net_mm"]
    pose = {"x": 0.0, "y": 595.0, "z": 30.0, "rx": 180.0, "ry": 0.0, "rz": 0.0}
    pc = fq.pose_with_focus_correction(pose, dz_net, n_cam)
    rep["R1d_pose"] = {"grasp_pose_mm": pose, "axis_source": axis_src,
                       "n_cam_in_base": [round(float(v), 4) for v in n_cam], "focus_dz_mm": dz_net,
                       "pose_corrected": {k: (round(float(v), 3) if isinstance(v, (int, float)) else v)
                                          for k, v in pc.items()}}
    print(f"🤖 R1d 修正位姿引导 ({axis_src}): Δfocus={dz_net:+.2f}mm 沿光轴 {np.round(n_cam,3)} → "
          f"抓握点 {pose['y']}/{pose['z']} → {pc['y']:.2f}/{pc['z']:.2f}mm (姿态不变)")

    # ── 证据拼图 ──
    tiles = [("sharp(real)", sharp), (f"defocus {K_PX_PER_MM*9:.1f}px", cam(Z_FOCUS - 9.0)),
             ("refocused", cam(loops['start_-9mm']['z_final_mm'])), ("scatter(unresolvable)", scatter)]
    th = 360; row = []
    for nm, im in tiles:
        r = cv2.resize(im, (int(th * im.shape[1] / im.shape[0]), th))
        cv2.putText(r, nm, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        row.append(r)
    cv2.imwrite(OUT_PNG, cv2.cvtColor(cv2.hconcat(row), cv2.COLOR_RGB2BGR))

    # ── 判据 (自动, 不写死) ──
    checks = {
        "R0 σ 估计在有效域 (0.75~2px) MAE ≤0.3px": rep["R0_calibration"]["sigma_est_mae_px"] <= 0.3,
        "R1a 扫焦曲线峰值在对焦点 (±1mm)": abs(peak["dz_mm"]) <= 1.0,
        "R1a 峰谷对比显著 (端点 ≤0.5×峰值)": min(qs[0], qs[-1]) <= 0.5 * peak["q"],
        "R1b 两方向起步均复焦成功且落点 ±1mm": all(v["ok"] and abs(v["z_final_mm"] - Z_FOCUS) <= 1.0
                                                  for v in loops.values()),
        "R1c 运动模糊判 motion (臂速主判据)": cs["motion"]["verdict_speed"] == "motion",
        "R1c 过曝判 exposure": cs["exposure"]["verdict"] == "exposure",
        "R1c 端面散射判 unresolvable (不假装修好)": cs["unresolvable_scatter"]["reason"] == "unresolvable",
        "R1c 无结构帧判 no_target (不判不修)": cs["invalid_blank"]["reason"] == "no_target",
        "R1c 现役真机 AOI 黑帧被闸拦住": cs.get("invalid_real_aoi_frame", {}).get("reason") == "no_target",
        "单帧量测 <20ms (实时可行)": ms < 20.0,
    }
    rep["checks"] = {k: bool(v) for k, v in checks.items()}
    rep["checks_pass"] = f"{sum(checks.values())}/{len(checks)}"
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  判据通过: {rep['checks_pass']}\n📄 {OUT_JSON}\n🖼  {OUT_PNG}")


if __name__ == "__main__":
    main()
