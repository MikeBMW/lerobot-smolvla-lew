#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""料盘槽位阵列能不能从画面上检出来? 先探阈值与形态, 不写盘。

口径: 泡棉是黑的, 槽腔是更黑的凹坑 ⇒ 用 black-hat(闭运算-原图) 把"比周围更暗"的
竖直短条挖出来, 再按 长宽比/面积 过滤。检不出就如实报检不出, 不硬凑。

【实测结论 2026-09-28: 这帧检不出, 别走这条路】
9 组 (核×阈值) 组合下候选数在 0~7 之间乱跳, 且命中的多是 ROI 角(0,0)与画面上缘的
绿色电路板工装(363,0 32x89), 不是泡棉槽腔。原因: ①黑泡棉上的槽腔是"黑上更黑",
对比度不足; ②这帧深度对槽位高低也无分辨力(整片 0.4~0.6m 平坦, 独立视觉复核确认)。
⇒ 料盘**全盘槽位阵列**在本路(臂上 D405)这帧无法靠图像/深度得到; 能给的是:
示教槽位 2 个 + 当前被占用槽 2 个(由实测光模块反推)。要全盘槽位得换顶摄 + 平面单应。
本脚本留档以免重复试错。
"""
import sys
from pathlib import Path

REPO = Path("/home/ubuntu/zmax")
sys.path.insert(0, str(REPO / "tools"))
import cv2                                                                           # noqa: E402
import numpy as np                                                                   # noqa: E402
import scene_overlay as SO                                                           # noqa: E402

raw = SO.fetch_frame("arm")
img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
H, W = img.shape[:2]
spec = SO.load_spec()
boxes = (spec.get("cameras", {}).get("arm", {}).get("boxes") or [])

# ROI: 优先用 L5 的「插槽/托盘槽位」框, 没有就用 L5「托盘」框
roi = None
for b in boxes:
    lb = str(b.get("label", ""))
    if b.get("xyxy") and ("插槽" in lb):
        roi = [int(v) for v in b["xyxy"]]
        break
if roi is None:
    for b in boxes:
        if b.get("xyxy") and str(b.get("label", "")).startswith("托盘"):
            roi = [int(v) for v in b["xyxy"]]
            break
if roi is None:
    roi = [110, 80, 580, 330]
x1, y1, x2, y2 = roi
print("ROI(槽位候选区) =", roi, "· 尺寸 %dx%d" % (x2 - x1, y2 - y1))

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
sub = gray[y1:y2, x1:x2]
clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(sub)
print("ROI 灰度: 中位 %d · 5%%= %d · 95%%= %d" % (
    int(np.median(sub)), int(np.percentile(sub, 5)), int(np.percentile(sub, 95))))

dbg = [img.copy()]
for ksz in ((9, 25), (13, 31), (21, 41)):
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, ksz)
    bh = cv2.morphologyEx(clahe, cv2.MORPH_BLACKHAT, ker)
    for thr in (12, 20, 30):
        m = (bh > thr).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
        cand = []
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < 60 or w < 3 or h < 3:
                continue
            ar = h / max(1, w)
            if not (1.3 <= ar <= 8.0):          # 竖直短条
                continue
            if not (25 <= a <= 8000):
                continue
            cand.append((x, y, w, h, a, ar))
        print("  核%s thr=%2d ⇒ 候选槽位 %2d 个 %s" % (
            ksz, thr, len(cand), ["%d,%d(%dx%d)" % (c[0], c[1], c[2], c[3]) for c in cand[:8]]))
        if ksz == (13, 31) and thr == 20:
            vis = img.copy()
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 1)
            for c in cand:
                cv2.rectangle(vis, (x1 + c[0], y1 + c[1]), (x1 + c[0] + c[2], y1 + c[1] + c[3]),
                              (0, 255, 0), 1)
            dbg.append(vis)

out = REPO.parent / ".hermes" / "cache" / "scratch" / "slotprobe"
out.mkdir(parents=True, exist_ok=True)
cv2.imwrite(str(out / "arm_gray.jpg"), sub)
cv2.imwrite(str(out / "blackhat_13x31_t20.jpg"), cv2.normalize(
    cv2.morphologyEx(clahe, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 31))),
    None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8))
cv2.imwrite(str(out / "cand_vis.jpg"), dbg[-1] if len(dbg) > 1 else img)
print("探针图:", out)
