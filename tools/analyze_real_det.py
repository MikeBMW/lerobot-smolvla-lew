# -*- coding: utf-8 -*-
"""真机检出结果分析 — 位置先验自检 (无需人眼)。

现场事实 (老倪 2026-09-17): 光模块只出现在真机画面**最下方正中**。
→ 若模型在真机上"检出了", 框中心应落在这个先验区域内; 落在别处 = 噪声拟检 (假检出)。
判据: 检出框中心 x∈[0.25,0.75] ∧ y∈[0.55,1.00] 记为 先验内。
"""
import argparse, json, os

PRIOR = dict(x=(0.25, 0.75), y=(0.55, 1.00))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="reports/sim2real_20260917/eval_arms.json")
    args = ap.parse_args()
    d = json.load(open(args.json))
    print(f"位置先验 (光模块在画面下方正中): x∈{PRIOR['x']} y∈{PRIOR['y']}  ← 老倪现场口述\n")
    rows = []
    for tag, arm in d["arms"].items():
        n_in = n_out = n_tot = 0
        tops = []
        # 分帧组 (测集自检证明两类帧内容不同: 09:30 组下方 ROI 有成块结构 / 07:xx 组几乎没有)
        grp = {"new_0930": {"frames": 0, "det": 0, "tot": 0, "in": 0, "maxc": 0.0},
               "old_07xx": {"frames": 0, "det": 0, "tot": 0, "in": 0, "maxc": 0.0}}
        for fname, rec in arm["real"].items():
            g = "new_0930" if "20260917_0930" in fname else "old_07xx"
            grp[g]["frames"] += 1
            br = rec["rots"][str(rec["best_rot"])]
            grp[g]["tot"] += br["n"]
            grp[g]["det"] += 1 if br["n"] > 0 else 0
            for c, (cx, cy, bw, bh, cls) in zip(br["conf"], br.get("boxes", [])):
                grp[g]["maxc"] = max(grp[g]["maxc"], c)
                if PRIOR["x"][0] <= cx <= PRIOR["x"][1] and PRIOR["y"][0] <= cy <= PRIOR["y"][1]:
                    grp[g]["in"] += 1
            grp[g]["maxc"] = max(grp[g]["maxc"], max(rec["peak_low_thresh"] or [0]))
            for (cx, cy, bw, bh, cls) in br.get("boxes", []):
                n_tot += 1
                if PRIOR["x"][0] <= cx <= PRIOR["x"][1] and PRIOR["y"][0] <= cy <= PRIOR["y"][1]:
                    n_in += 1
                else:
                    n_out += 1
            for c, (cx, cy, bw, bh, cls) in list(zip(br["conf"], br.get("boxes", [])))[:2]:
                tops.append((c, cls, cx, cy, round(bw, 3), round(bh, 3), fname.split("_")[0]))
        tops.sort(reverse=True)
        rows.append((tag, n_tot, n_in, n_out, arm["real_summary"]["frames_with_det"],
                     arm["real_summary"]["max_conf_any"], arm["real_summary"]["cls_total_best_rot"]))
        print(f"[{tag}] 检出框 {n_tot} 个 · 落在光模块先验区 {n_in} / 区外 {n_out} · "
              f"有检出帧 {arm['real_summary']['frames_with_det']}/{arm['real_summary']['frames']} · "
              f"最高conf {arm['real_summary']['max_conf_any']} · 分类 {arm['real_summary']['cls_total_best_rot']}")
        for c, cls, cx, cy, bw, bh, fr in tops[:3]:
            print(f"      top: conf={c} {cls} 中心=({cx},{cy}) 框={bw}x{bh} 帧={fr}")
        # 朝向一致性: 真机相机朝向固定 → 真检出应集中在同一个 rot; 四个 rot 都零散出框 = 噪声
        per_rot = {k: 0 for k in range(4)}
        for fname, rec in arm["real"].items():
            for k, v in rec["rots"].items():
                per_rot[int(k)] += v["n"]
        print(f"      各朝向检出分布 rot0/90/180/270 = {[per_rot[k] for k in range(4)]}"
              f" → 最集中朝向 rot{max(per_rot, key=per_rot.get)*90}°"
              f" (占比 {max(per_rot.values())/max(1, sum(per_rot.values()))*100:.0f}%)")
        for g, v in grp.items():
            if v["frames"]:
                print(f"      [{g}] {v['frames']} 帧: 有检出 {v['det']} 帧 · 检出框 {v['tot']} 个"
                      f" (先验区内 {v['in']}) · 最高 conf {v['maxc']:.4f}")
    print("\n判据: 『有检出帧数>0 且 检出框落在光模块先验区』才算真提升; 只在区外出框 = 噪声拟检, 不算。")


if __name__ == "__main__":
    main()
