#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(可复用) sim→real YOLO 同口径评测器 — 真机 D405 帧 + 仿真 hold-out 双侧对照。

口径铁律 (每次都必须一样, 否则对照无效):
  · 同一帧集 (真机 20 帧去重集 / 仿真 hold-out) · 同一 imgsz=480 · 同一 conf · 同一 BGR 转换
  · 朝向枚举: 真机朝向未知 → 4 种 rot90 全跑, 取最佳 (同时打印 4 朝向明细)
  · 退化帧 (纯黑/纯色, std<5) 单独剔除并计数, 不混进分母
  · 逐臂独立进程调用, 互不共享模型状态

用法:
  python tools/eval_sim2real_yolo.py --weights A.pt B.pt --tag peg_v1 dr \
      --real-dir ~/zmax_data/real_cam/orin_d405_eval --sim-dir data/yolo_peg_holdout/images \
      --conf 0.25 --out reports/sim2real_20260917/eval_arms.json --vis /home/ubuntu/zmax_data/real_cam/eval_vis
"""
import argparse, glob, hashlib, json, os
import cv2
import numpy as np


def load_frames(d):
    out = []
    for p in sorted(glob.glob(os.path.join(os.path.expanduser(d), "*.jpg")) +
                    glob.glob(os.path.join(os.path.expanduser(d), "*.png"))):
        img = cv2.imread(p)
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        out.append((os.path.basename(p), hashlib.md5(open(p, "rb").read()).hexdigest()[:10], img,
                    float(g.std()), float(g.mean())))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", nargs="+", required=True)
    ap.add_argument("--tag", nargs="*", default=None)
    ap.add_argument("--real-dir", default="/home/ubuntu/zmax_data/real_cam/orin_d405_eval")
    ap.add_argument("--sim-dir", default="data/yolo_peg_holdout/images")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--conf-low", type=float, default=0.01, help="看原始峰值分布用的低阈值")
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--rot-sim", type=int, default=0, help="仿真帧在盘上已是推理朝向 → 0")
    ap.add_argument("--sim-n", type=int, default=60, help="仿真 hold-out 抽样帧数")
    ap.add_argument("--out", default="reports/sim2real_20260917/eval_arms.json")
    ap.add_argument("--vis", default="")
    ap.add_argument("--vis-k", type=int, default=3)
    args = ap.parse_args()
    tags = args.tag or [os.path.basename(os.path.dirname(os.path.dirname(w))) for w in args.weights]

    from ultralytics import YOLO

    real = load_frames(args.real_dir)
    real_ok = [f for f in real if f[3] >= 5.0]
    deg = [f[0] for f in real if f[3] < 5.0]
    sim = load_frames(args.sim_dir)
    sim = sim[::max(1, len(sim) // args.sim_n)][:args.sim_n]
    print(f"真机帧 {len(real)} (退化剔除 {len(deg)}: {deg}) | 仿真 hold-out {len(sim)} 张 "
          f"| conf={args.conf} imgsz={args.imgsz}\n")

    all_res = {"conf": args.conf, "imgsz": args.imgsz,
               "real_dir": args.real_dir, "sim_dir": args.sim_dir,
               "real_degenerate_excluded": deg, "arms": {}}

    for w, tag in zip(args.weights, tags):
        if not os.path.exists(w):
            print(f"⚠️ 权重不存在, 跳过: {w}")
            continue
        m = YOLO(w)
        names = m.model.names
        arm = {"weights": os.path.abspath(w), "size_mb": round(os.path.getsize(w) / 1e6, 1),
               "classes": {str(k): v for k, v in names.items()}, "real": {}, "sim": {}}

        # ── 真机侧: 4 朝向枚举 ──
        best_tot = 0
        max_conf = 0.0
        det_frames = 0
        cls_tot = {}
        for name, md5, img, std, mean in real_ok:
            rec = {"rots": {}}
            for k in range(4):
                im = np.rot90(img, k=k) if k else img
                r = m.predict(np.ascontiguousarray(im), conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
                cl = [names[int(b.cls)] for b in r.boxes]
                cf = [round(float(b.conf[0]), 4) for b in r.boxes]
                H, W = im.shape[:2]
                bx = []
                for b in r.boxes:
                    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
                    bx.append([round(((x1 + x2) / 2) / W, 3), round(((y1 + y2) / 2) / H, 3),
                               round((x2 - x1) / W, 3), round((y2 - y1) / H, 3), names[int(b.cls)]])
                rec["rots"][str(k)] = {"n": len(cl), "cls": cl, "conf": cf, "boxes": bx}
            r_low = m.predict(np.ascontiguousarray(img), conf=args.conf_low, imgsz=args.imgsz, verbose=False)[0]
            rec["peak_low_thresh"] = sorted([round(float(b.conf[0]), 4) for b in r_low.boxes], reverse=True)[:5]
            b = max(rec["rots"].items(), key=lambda kv: kv[1]["n"])
            rec["best_rot"] = int(b[0])
            best_tot += b[1]["n"]
            det_frames += 1 if b[1]["n"] > 0 else 0
            max_conf = max([max_conf] + [c for v in rec["rots"].values() for c in v["conf"]] +
                           (rec["peak_low_thresh"] or [0]))
            for c in b[1]["cls"]:
                cls_tot[c] = cls_tot.get(c, 0) + 1
            arm["real"][f"{md5}_{name}"] = rec
        arm["real_summary"] = {"frames": len(real_ok), "frames_with_det": det_frames,
                               "best_rot_total_det": best_tot, "max_conf_any": round(max_conf, 4),
                               "cls_total_best_rot": cls_tot,
                               "均值每帧检出": round(best_tot / max(1, len(real_ok)), 2)}

        # ── 仿真侧 (不回退判据) ──
        n_all3 = 0
        det_tot = 0
        sim_conf = {}
        for name, md5, img, std, mean in sim:
            im = np.rot90(img, k=args.rot_sim) if args.rot_sim else img
            r = m.predict(np.ascontiguousarray(im), conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
            cl = [names[int(b.cls)] for b in r.boxes]
            det_tot += len(cl)
            if set(cl) >= set(names.values()):
                n_all3 += 1
            for b in r.boxes:
                sim_conf.setdefault(names[int(b.cls)], []).append(float(b.conf[0]))
        arm["sim"] = {"frames": len(sim), "mean_det_per_frame": round(det_tot / max(1, len(sim)), 2),
                      "frames_all_classes": n_all3,
                      "mean_conf": {k: round(float(np.mean(v)), 3) for k, v in sim_conf.items()}}
        all_res["arms"][tag] = arm

        print(f"[{tag}] 真机 {arm['real_summary']['frames']} 帧: 有检出 {det_frames} 帧 · "
              f"最佳朝向检出总数 {best_tot} · 最高 conf {max_conf:.4f} · 分类 {cls_tot}")
        print(f"        仿真 hold-out: 每帧检出 {arm['sim']['mean_det_per_frame']} · 三类齐全 {n_all3}/{len(sim)} · "
              f"平均 conf {arm['sim']['mean_conf']}")

        # 目检图 (最佳朝向, conf=0.15 放宽以便看出"似检非检")
        if args.vis:
            os.makedirs(args.vis, exist_ok=True)
            for name, md5, img, std, mean in real_ok[:args.vis_k]:
                k = arm["real"][f"{md5}_{name}"]["best_rot"]
                im = np.rot90(img, k=k) if k else img
                r = m.predict(np.ascontiguousarray(im), conf=0.15, imgsz=args.imgsz, verbose=False)[0]
                cv2.imwrite(os.path.join(args.vis, f"{tag}_{md5}_rot{k}_{name}"), r.plot())

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(all_res, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"\n判据: 真机『有检出帧数』与『最高 conf』是硬指标 (基线 0 帧 / 0.0107); 仿真侧不得回退。")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
