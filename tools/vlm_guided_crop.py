#!/usr/bin/env python3
"""vlm_guided_crop.py — L2 检测框引导 L1 判读 (检测-放大-判读融合)

问题: 工位相机离得远, 光模块在整幅画面里只有几十像素 → 通用 VLM 认不出 ("目标可见=false"), 
     而我们自己的 YOLO (L2) 在同一帧里能检出 peg。
做法: 取 L2 最新检测记录 (yolo_detections.json) 的框 → 带边距裁剪 → 放大 (最近邻+双三次) 
     → 送 SceneVLM (DeepSeek-Vision 或本地 Qwen) 判读 → 结果并入 data/scene_state.json。

纪律: 
  · 只读 L2 记录 + 帧; 不改任何产线/控制路径;
  · scene_state.json 为追加式合并 (只更新本工具自己的键, 其它键原样) —— 感知源单一真源口径;
  · 输出里带 source/box/帧龄, 便于目检对账 (禁假值)。

用法:
  gui-venv311/bin/python tools/vlm_guided_crop.py                     # 全链 (DeepSeek)
  SS_VLM_PROVIDER=local SS_VLM_MODEL=<snap> gui-venv311/bin/python tools/vlm_guided_crop.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
BYPASS = os.path.expanduser("~/zmax_data/ss_bypass")
REMOTE = os.path.expanduser("~/zmax_ss_remote")
STATE = os.path.join(ROOT, "data", "scene_state.json")
OUT_IMG = os.path.join(BYPASS, "vlm_crop_probe.png")

PROMPT = ("这是从产线工位相机画面里裁出的一个局部(已放大)。请只回答这是什么零件、"
          "有没有金属光泽/绿色拉环/金色触点这些特征。只输出 JSON: "
          '{"是光模块":true/false,"置信":"高/中/低","外观":"...","判断依据":"..."}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin", type=float, default=0.6, help="框外扩比例")
    ap.add_argument("--scale", type=int, default=6, help="放大倍数")
    ap.add_argument("--cls", default="peg", help="用哪类检测框")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args()

    import importlib.util
    from PIL import Image

    # ① L2 记录
    dj = os.path.join(BYPASS, "yolo_detections.json")
    if not os.path.exists(dj):
        print("❌ 没有 L2 检测记录:", dj)
        return 2
    rec = json.load(open(dj))
    age = time.time() - rec.get("t", 0)
    dets = [d for d in rec.get("detections", []) if d.get("cls") == a.cls]
    if not dets:
        print(f"❌ L2 记录里没有 {a.cls} 检测 (共 {rec.get('n')} 个框); 记录龄 {age:.1f}s")
        return 3

    src_img = os.path.join(REMOTE, rec.get("image", "cam_local.png"))
    im = Image.open(src_img).convert("RGB")
    print(f"L2 记录: {rec.get('image')} · 源={rec.get('source_label')} · 记录龄={age:.1f}s · {a.cls} 框 {len(dets)} 个")

    # ② 裁剪放大
    crops = []
    for i, d in enumerate(dets):
        x1, y1, x2, y2 = d["xyxy"]
        w, h = x2 - x1, y2 - y1
        mx, my = w * a.margin, h * a.margin
        bx = (max(0, x1 - mx), max(0, y1 - my), min(im.width, x2 + mx), min(im.height, y2 + my))
        c = im.crop(tuple(int(v) for v in bx))
        c = c.resize((c.width * a.scale, c.height * a.scale), Image.BICUBIC)
        p = os.path.join(BYPASS, f"vlm_crop_{i}.png")
        c.save(p)
        crops.append({"box": [round(v, 1) for v in d["xyxy"]], "conf": d.get("conf"), "crop": p})
    # 拼一张多框对照图 (目检用)
    if crops:
        ims = [Image.open(c["crop"]) for c in crops]
        W = sum(i.width for i in ims) + 10 * (len(ims) - 1)
        H = max(i.height for i in ims)
        sheet = Image.new("RGB", (W, H), (20, 20, 20))
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0))
            x += i.width + 10
        sheet.save(OUT_IMG)
        print(f"裁剪图: {OUT_IMG} ({W}x{H})")

    # ③ L1 判读 (SceneVLM: DeepSeek 或本地 Qwen)
    spec = importlib.util.spec_from_file_location(
        "scene_vlm", f"{ROOT}/src/lerobot/policies/left_right/state_space/scene_vlm.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    v = m.SceneVLM.get()
    print("L1:", json.dumps(v.status(), ensure_ascii=False))
    results = []
    for c in crops:
        r = v.ask(c["crop"], PROMPT, max_tokens=200)
        results.append({"box": c["box"], "conf": c["conf"], "crop": os.path.basename(c["crop"]),
                        "ok": r.get("ok"), "vlm": r.get("json") or r.get("text"),
                        "latency_ms": r.get("latency_ms"), "src": r.get("src")})
        print(f"  框 {c['box']} conf={c['conf']} → {json.dumps(results[-1]['vlm'], ensure_ascii=False)[:220]}")
    v.close()

    # ④ 合并进 scene_state.json (只更新自己的键, 其它原样)
    st = {}
    if os.path.exists(a.state):
        try:
            st = json.load(open(a.state))
        except Exception:                                                       # noqa: BLE001
            st = {}
    st["vlm_guided_crop"] = {
        "ts": time.time(), "l2_image": rec.get("image"), "l2_source": rec.get("source_label"),
        "l2_age_s": round(age, 2), "cls": a.cls, "n_boxes": len(crops),
        "results": results, "sheet": OUT_IMG,
        "note": "L2 检测框 → 裁剪放大 → L1 判读 (检测引导判读; 源为工位相机时不代表产线视角)",
    }
    os.makedirs(os.path.dirname(a.state), exist_ok=True)
    json.dump(st, open(a.state, "w"), ensure_ascii=False, indent=1)
    print("已并入:", a.state, "键 vlm_guided_crop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
