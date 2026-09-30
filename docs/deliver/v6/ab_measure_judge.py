# -*- coding: utf-8 -*-
# read-only: measure the newest judge/960/origin images on this machine
import glob, json, os, time
import numpy as np
import cv2


def newest(pat):
    f = sorted(glob.glob(pat), key=os.path.getmtime)
    return f[-1] if f else None


def stats(p):
    im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if im is None:
        return {"error": "imread failed"}
    h, w = im.shape
    hh, ww = (h // 16) * 16, (w // 16) * 16
    b = im[:hh, :ww].reshape(hh // 16, 16, ww // 16, 16).transpose(0, 2, 1, 3).reshape(-1, 16, 16)
    c = im.astype(np.float32)
    c = c - c.mean(axis=0, keepdims=True)
    ac = [float((c[:, :-k] * c[:, k:]).mean() / (c.std() ** 2 + 1e-6)) for k in range(1, 160)]
    out = {"file": os.path.basename(p), "h": h, "w": w, "mtime": time.strftime("%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p))),
           "mean": round(float(im.mean()), 1), "std": round(float(im.std()), 1),
           "block16_std_mean": round(float(b.std(axis=(1, 2)).mean()), 2),
           "pct_gt240": round(float((im > 240).mean() * 100), 2),
           "pct_gt250": round(float((im > 250).mean() * 100), 2),
           "col_ac_peak": round(max(ac), 3), "col_ac_lag": int(np.argmax(ac) + 1)}
    if h > 200:
        out["row_std_max"] = round(float(im.std(axis=1).max()), 1)
    return out


res = {"runs": []}
for label, pat in (("judge_900x332", "goldfinger_images/Finger_TopView_*.png"),
                   ("origin_2448x2048", "goldfinger_images/Finger_Image_*.png"),
                   ("modelin_960", os.path.join(os.environ.get("TEMP", "C:" + os.sep + "Windows" + os.sep + "TEMP"), "zmax_main_960_*.png")),
                   ("judge960_ab", os.path.join(os.environ.get("TEMP", "C:" + os.sep + "Windows" + os.sep + "TEMP"), "zmax_ab_judge960_*.png"))):
    p = newest(pat)
    if not p:
        res["runs"].append({"label": label, "error": "not found"})
        continue
    s = stats(p)
    s["label"] = label
    res["runs"].append(s)
print(json.dumps(res, ensure_ascii=False, indent=1))
