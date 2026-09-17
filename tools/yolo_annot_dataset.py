#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_annot_dataset.py — 真机 YOLO 标定数据的**目录规范 + 保存 + 构建 + 体检 + 训练前校验**

老倪 2026-09-17: 「现在要采集真机的图片, 开始真实图片训练 YOLO 模型… 在右键打开的窗口增加标定功能,
让标定工程师根据图像圈选光模块、输入类别、保存当前图片, 而且 YOLO 模型可以通过保存的图片进行模型训练。
做好标定工程、数据保存、数据文件夹路径的设计」

目录规范 (全部在 data/yolo_annot, data/ 已被 .gitignore → 数据不进代码库):

    data/yolo_annot/
    ├── README.md                        目录说明 (--init 生成, 自解释)
    ├── classes.txt                      类别表: **行号 = YOLO class id** (第 1 行 = 0)
    ├── meta.json                        数据集版本 / 全部会话索引 / 张数
    ├── annotations.jsonl                追加式流水: 每张图片的完整记录 (可追溯, 永不改写)
    ├── sessions/<会话>/
    │   ├── session.json                 会话元信息 (设备身份/分辨率/时间/标定员)
    │   ├── frames/<stem>.jpg            原始图片 (= 窗口显示的那一帧, 未旋转的口径)
    │   └── labels/<stem>.txt            YOLO 标注 `cls cx cy w h` (归一化 0~1, 5 位小数)
    └── dataset/                         **训练唯一入口** (由 --build 生成, 给 ultralytics 用)
        ├── images/{train,val}/          图片 (硬链接/拷贝, 不重复占盘)
        ├── labels/{train,val}/          标注
        ├── data.yaml                    train/val 路径 + names (来自 classes.txt)
        └── stats.json                   张数/类别分布/划分比例 (可复现)

为什么"会话 + 构建"两层: 会话层保留**溯源** (哪台相机、第几帧、帧龄多少 → 防拿旧图冒充/可复查),
构建层保证**可复现** (改 val 比例 / 重划分只重跑 --build, 不用重新标定)。

命令行:
  --init [--classes optical_module]           初始化目录 + classes.txt + README
  --build [--val-ratio 0.15] [--seed 0]       生成 dataset/{images,labels}/{train,val} + data.yaml
  --check [--strict]                          体检 (标签格式/范围/类别/配对/重复/空标), 有错退出码 1
  --stats                                     张数 + 类别分布 + 会话清单
  --import-yolo-dir DIR --session NAME        把已有 YOLO 目录(images+labels)导入成一个会话
  --add-class NAME                            追加类别 (返回 id)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time

import numpy as np

ROOT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "yolo_annot")
ROOT_SIM_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "yolo_annot_sim")
# 💻 2026-09-17 老倪: 第三路输入源 = 本机内置摄像头 (无 Orin 也能采真像素) → 数据根独立,
#    避免和真机 D405 帧/仿真渲染帧混在一个类别表里 (口径打结)
ROOT_USBCAM_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "yolo_annot_usbcam")
# 🐛 2026-09-17 口径纠正: 真机类别名必须用 `peg` (不是 optical_module)。
#   依据 = src/lerobot/policies/yolo_3d/frame_source.py:40 的唯一口径源
#   CLASS_MAP = {"hand": "hand", "peg": "光模块", "hole": "hole"} (注释: peg→光模块, id 顺序不许改),
#   下游 tools/real_yolo_perceive.py 按业务名取 det3d.get("hand") / det3d["光模块"] / det3d["hole"]。
#   旧默认 "optical_module" 在 CLASS_MAP 里没有条目 → 真机权重训出来接不进感知链 (光模块那一路恒空)。
DEFAULT_CLASSES = ["peg"]                   # 光模块 (现场一端入镜; 画面若能看到孔口再加 "hole")
DEFAULT_SIM_CLASSES = ["peg", "hole", "hand"]   # 仿真 metaworld 三类 (与 data/yolo_peg 现有口径一致)
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp")


def root_for(source: str) -> str:
    """按**数据源**给数据根: 真机 / 仿真 / 本机摄像头 分开存 (口径不同 —— 仿真 peg 与真机光模块
    不是一回事, 混在一个数据集里训练会让类别语义打结)。"""
    s = str(source)
    if s.startswith("sim"):
        return os.environ.get("ZMAX_ANNOT_ROOT_SIM", ROOT_SIM_DEFAULT)
    if s.startswith("usbcam"):
        return os.environ.get("ZMAX_ANNOT_ROOT_USBCAM", ROOT_USBCAM_DEFAULT)
    return os.environ.get("ZMAX_ANNOT_ROOT", ROOT_DEFAULT)


def default_classes_for(source: str) -> list:
    return list(DEFAULT_SIM_CLASSES) if str(source).startswith("sim") else list(DEFAULT_CLASSES)


def session_tag_for(source: str) -> str:
    s = str(source)
    if s.startswith("sim"):
        return "sim_corner2"
    if s.startswith("usbcam"):
        return "usbcam"
    return "d405"
README_TMPL = """# YOLO 真机标定数据 (data/yolo_annot)

> 由 `tools/yolo_annot_dataset.py --init` 生成 / `--build` 更新。**目录即契约, 别手改结构。**

## 怎么用
1. 控制台 → 画布右键「🎯 YOLO 目标检测」→『打开输入图像 (实时原始视频流)』→ 勾「✏️ 标定模式」
2. 在画面上**拖框**圈住光模块 → 选/输入类别 → 「💾 保存标注」(或「⏭ 保存并下一帧」)
3. 攒够数据 (建议首轮 ≥100 张, 覆盖不同位置/光照) → 「📦 构建数据集」→ 「🚀 训练 YOLO」

## 目录
| 路径 | 含义 |
|---|---|
| `classes.txt` | 类别表, **行号 = class id** (第 1 行 = 0)。改这里 = 改训练类别, 顺序别乱动 |
| `sessions/<会话>/frames/*.jpg` | 保存的原始图片 (与窗口显示同一口径, 未旋转) |
| `sessions/<会话>/labels/*.txt` | YOLO 标注 `cls cx cy w h` (归一化, 相对于图片宽高) |
| `sessions/<会话>/session.json` | 会话元信息: 相机身份/分辨率/时间/标定员 |
| `annotations.jsonl` | 追加式流水 (每张一行 JSON): 像素框 + 类别 + 来源帧 seq/帧龄 → 可追溯, 勿改 |
| `dataset/images|labels/{train,val}` | 按 `--build` 划分后的训练集 (硬链接, 省盘) |
| `dataset/data.yaml` | 给 ultralytics 的配置 (train/val 路径 + nc/names) |
| `dataset/stats.json` | 张数/类别分布/划分比例 (可复现依据) |
| `meta.json` | 数据集版本 + 会话索引 |

## 口径 (重要)
- **图片 = 窗口里那一帧的像素**: 真机源为 Orin 侧 JPEG 解码后的画面 (q95 重编码保存), **不做任何旋转**,
  与模型推理时的输入同向 (旋转窗上的框会自动换算回原始帧坐标)。
- 标注只写**框**, 不写 keypoint/分割 → ultralytics 直读 (检测任务)。
- 类别名禁用算法词, 用**能力/物体**命名 (老倪红线), 例如 `optical_module` / `fiber_connector`。
- `val` 划分按**文件名哈希** (稳定可复现): 同一张图永远是同一个 split。

## 训练
```bash
# 构建 + 体检
python3 tools/yolo_annot_dataset.py --build --check
# 微调 (推荐从现有权重继续 → 域适应)
gui-venv311/bin/python tools/yolo_annot_train.py --epochs 100 --imgsz 640 --device 0 \\
    --base <现有 best.pt> --name annot_v1
```
"""


# ───────────────────────── 基础 ─────────────────────────
def paths(root: str = ROOT_DEFAULT) -> dict:
    return {
        "root": root, "sessions": os.path.join(root, "sessions"),
        "classes": os.path.join(root, "classes.txt"),
        "meta": os.path.join(root, "meta.json"),
        "annot": os.path.join(root, "annotations.jsonl"),
        "dataset": os.path.join(root, "dataset"),
        "readme": os.path.join(root, "README.md"),
    }


def _read_lines(p):
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def load_classes(root: str = ROOT_DEFAULT) -> list:
    return _read_lines(paths(root)["classes"])


def save_classes(root, names):
    p = paths(root)["classes"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")
    return names


def add_class(root, name) -> int:
    """追加类别 → 返回 class id; 已存在则返回原 id (幂等, 不改顺序)"""
    name = (name or "").strip()
    if not name:
        raise ValueError("类别名不能为空")
    if any(c in name for c in " \t,/\n"):
        raise ValueError(f"类别名不能含空格/逗号/斜杠: {name!r}")
    names = load_classes(root)
    if name in names:
        return names.index(name)
    names.append(name)
    save_classes(root, names)
    return len(names) - 1


def ensure_layout(root: str = ROOT_DEFAULT, classes=None) -> dict:
    P = paths(root)
    for d in (P["root"], P["sessions"], P["dataset"]):
        os.makedirs(d, exist_ok=True)
    if not os.path.isfile(P["classes"]):
        save_classes(root, list(classes or DEFAULT_CLASSES))
    if not os.path.isfile(P["readme"]):
        with open(P["readme"], "w", encoding="utf-8") as f:
            f.write(README_TMPL)
    if not os.path.isfile(P["meta"]):
        _write_json(P["meta"], {"version": 1, "created": time.strftime("%F %T"),
                                "sessions": [], "n_images": 0})
    if not os.path.isfile(P["annot"]):
        open(P["annot"], "a").close()
    return P


def _write_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                      # noqa: BLE001
        return default


def session_name(tag: str = "d405") -> str:
    return f"s{time.strftime('%Y%m%d_%H%M')}_{tag}"


# ───────────────────────── 保存样本 ─────────────────────────
def to_yolo_line(box_px, w, h, cls_id) -> str:
    """像素框 (x1,y1,x2,y2) → YOLO 归一化行 `cls cx cy w h` (5 位小数, 自动夹到图内)"""
    x1, y1, x2, y2 = [float(v) for v in box_px]
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    x1, x2 = max(0.0, min(x1, w)), max(0.0, min(x2, w))
    y1, y2 = max(0.0, min(y1, h)), max(0.0, min(y2, h))
    cx, cy = (x1 + x2) / 2.0 / w, (y1 + y2) / 2.0 / h
    bw, bh = (x2 - x1) / w, (y2 - y1) / h
    return f"{int(cls_id)} {cx:.5f} {cy:.5f} {bw:.5f} {bh:.5f}"


def yolo_line_to_box(line, w, h):
    """YOLO 行 → (cls, x1,y1,x2,y2) 像素框 (体检/回显用)"""
    p = line.split()
    cls = int(float(p[0]))
    cx, cy, bw, bh = [float(v) for v in p[1:5]]
    return cls, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h


def save_sample(root, frame_rgb: np.ndarray, boxes, *, device="", seq=None, ts=None, src="",
                session=None, annotator="", tag="d405", extra=None, jpeg_quality=95) -> dict:
    """把**当前这一帧 + 框**落盘到一个标定会话里。

    frame_rgb: HxWx3 RGB uint8 (与窗口显示同口径, 不旋转)
    boxes: [(x1,y1,x2,y2,cls_id|cls_name), ...] 像素坐标, 可空 (= 背景负样本, 也保存)
    返回: 记录 dict (同时追加进 annotations.jsonl)
    """
    P = ensure_layout(root)
    names = load_classes(root)
    h, w = frame_rgb.shape[:2]
    session = session or session_name(tag)
    sdir = os.path.join(P["sessions"], session)
    fdir, ldir = os.path.join(sdir, "frames"), os.path.join(sdir, "labels")
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(ldir, exist_ok=True)

    recs, lines = [], []
    for b in boxes or []:
        x1, y1, x2, y2, c = b[0], b[1], b[2], b[3], b[4]
        cid = names.index(c) if isinstance(c, str) and c in names else int(c)
        if isinstance(c, str) and c not in names:
            cid = add_class(root, c)
            names = load_classes(root)
        if abs(float(x2) - float(x1)) < 2 or abs(float(y2) - float(y1)) < 2:
            continue                                  # 退化框 (误点) 丢弃, 不写脏数据
        lines.append(to_yolo_line((x1, y1, x2, y2), w, h, cid))
        recs.append({"cls_id": cid, "cls": names[cid],
                     "box_px": [round(float(x1), 2), round(float(y1), 2),
                                round(float(x2), 2), round(float(y2), 2)]})

    stem = time.strftime("%Y%m%d_%H%M%S") + f"_{int((ts or time.time()) * 1000) % 1000:03d}"
    while os.path.exists(os.path.join(fdir, stem + ".jpg")):
        stem += "b"
    jpg, txt = os.path.join(fdir, stem + ".jpg"), os.path.join(ldir, stem + ".txt")
    ok = False
    try:
        import cv2
        ok = bool(cv2.imwrite(jpg, frame_rgb[:, :, ::-1], [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]))
    except Exception:                                                      # noqa: BLE001
        ok = False
    if not ok:                                        # 无 cv2 时用 Qt 落盘 (GUI 环境必有)
        from PyQt5 import QtGui
        img = QtGui.QImage(np.ascontiguousarray(frame_rgb).data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
        ok = img.save(jpg, "JPEG", jpeg_quality)
    if not ok:
        raise RuntimeError("图片保存失败: " + jpg)
    with open(txt, "w", encoding="utf-8") as f:
        f.write(("\n".join(lines) + "\n") if lines else "")

    rec = {"stem": stem, "session": session, "image": jpg, "label": txt,
           "w": w, "h": h, "n_boxes": len(recs), "boxes": recs,
           "device": device, "seq": seq, "src": src,
           "frame_ts": ts, "saved": time.time(), "saved_iso": time.strftime("%F %T"),
           "annotator": annotator, "classes": names}
    if extra:
        rec.update(extra)
    with open(P["annot"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 📌 真值侧车 (老倪 2026-09-17: 训练要有光模块位置/距离) — 一条样本一条真值, 与标注同生命周期。
    #    单独成文件是为了让训练/标定**只读真值**就能用 (不必解析整份 annotations.jsonl 的审计流水)。
    if extra and extra.get("truth"):
        tp = os.path.join(P["sessions"], session, "truth.jsonl")
        try:
            with open(tp, "a", encoding="utf-8") as f:
                f.write(json.dumps({"stem": stem, "session": session, "saved_iso": rec["saved_iso"],
                                    "w": w, "h": h, "boxes": recs, "truth": extra["truth"]},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass
    _register_session(root, session, device, w, h, annotator, src)
    return rec


def _register_session(root, session, device, w, h, annotator, src):
    P = paths(root)
    meta = _read_json(P["meta"], {}) or {}
    idx = {s["name"]: s for s in meta.get("sessions", [])}
    s = idx.setdefault(session, {"name": session, "created": time.strftime("%F %T"), "n_images": 0})
    s.update({"device": device or s.get("device", ""), "w": w, "h": h,
              "annotator": annotator or s.get("annotator", ""), "src": src or s.get("src", ""),
              "updated": time.strftime("%F %T")})
    s["n_images"] = len(glob.glob(os.path.join(P["sessions"], session, "frames", "*")))
    meta["sessions"] = sorted(idx.values(), key=lambda x: x["name"])
    meta["n_images"] = sum(x["n_images"] for x in meta["sessions"])
    meta["classes"] = load_classes(root)
    _write_json(P["meta"], meta)
    _write_json(os.path.join(P["sessions"], session, "session.json"),
                {"session": session, "device": device, "w": w, "h": h, "annotator": annotator,
                 "src": src, "n_images": s["n_images"], "updated": s["updated"]})


def _session_n(root, session) -> int:
    return len([p for p in glob.glob(os.path.join(paths(root)["sessions"], session, "frames", "*"))
                if p.lower().endswith(IMG_EXT)])


def _sync_meta(root):
    """按磁盘实况刷新 meta.json 的会话清单/图片数 + 每个会话的 session.json
    (删除样本后必须调 —— 否则 meta 与磁盘不一致, 「已存 N 张」会骗人)"""
    P = paths(root)
    meta = _read_json(P["meta"], {}) or {}
    idx = {s["name"]: s for s in meta.get("sessions", [])}
    for sd in sorted(glob.glob(os.path.join(P["sessions"], "*"))):
        if not os.path.isdir(sd):
            continue
        name = os.path.basename(sd)
        idx.setdefault(name, {"name": name, "created": time.strftime("%F %T")})
        n = _session_n(root, name)
        idx[name]["n_images"] = n
        sj = os.path.join(sd, "session.json")
        if os.path.isfile(sj):
            d = _read_json(sj, {}) or {}
            d["n_images"] = n
            d["updated"] = time.strftime("%F %T")
            _write_json(sj, d)
    meta["sessions"] = sorted([s for s in idx.values()
                               if os.path.isdir(os.path.join(P["sessions"], s["name"]))],
                              key=lambda x: x["name"])
    meta["n_images"] = sum(int(s.get("n_images", 0)) for s in meta["sessions"])
    _write_json(P["meta"], meta)
    return meta


def delete_sample(root=ROOT_DEFAULT, session=None, stem=None) -> dict:
    """🗑 删掉一张样本 —— **图与标注成对删** (绝不只删图留下孤儿标注)。

    返回 {"deleted": [...], "missing": [...]}: 实际删掉的文件 / 本来就不在的。
    """
    out = {"deleted": [], "missing": []}
    if not (session and stem):
        return out
    sess_dir = os.path.join(paths(root)["sessions"], session)
    for sub, exts in (("frames", IMG_EXT), ("labels", (".txt",))):
        for e in exts:
            fp = os.path.join(sess_dir, sub, stem + e)
            if os.path.isfile(fp):
                os.remove(fp)
                out["deleted"].append(os.path.relpath(fp, root))
            else:
                out["missing"].append(os.path.relpath(fp, root))
    _sync_meta(root)
    # 真值侧车同步 (删样本就把它的真值一起删, 免得训练读到不存在的图)
    tp = os.path.join(sess_dir, "truth.jsonl")
    if os.path.isfile(tp):
        keep = []
        for ln in _read_lines(tp):
            try:
                if json.loads(ln).get("stem") != stem:
                    keep.append(ln)
            except ValueError:
                continue
        with open(tp, "w", encoding="utf-8") as f:
            f.write(("\n".join(keep) + "\n") if keep else "")
    return out


def clear_session(root=ROOT_DEFAULT, session=None) -> dict:
    """🗑 清空一个会话的全部样本 (图+标注), 保留会话目录/类别表; meta 计数同步刷新。"""
    n = 0
    if not session:
        return {"removed": 0}
    sess_dir = os.path.join(paths(root)["sessions"], session)
    for sub in ("frames", "labels"):
        for p in glob.glob(os.path.join(sess_dir, sub, "*")):
            os.remove(p)
            n += 1
    tp = os.path.join(sess_dir, "truth.jsonl")
    if os.path.isfile(tp):                       # 真值侧车随会话一起清
        os.remove(tp)
        n += 1
    _sync_meta(root)
    return {"removed": n, "session": session}


# ───────────────────────── 遍历 / 构建 / 体检 ─────────────────────────
def iter_samples(root=ROOT_DEFAULT):
    P = paths(root)
    for jpg in sorted(glob.glob(os.path.join(P["sessions"], "*", "frames", "*"))):
        if not jpg.lower().endswith(IMG_EXT):
            continue
        stem = os.path.splitext(os.path.basename(jpg))[0]
        sess = os.path.basename(os.path.dirname(os.path.dirname(jpg)))
        yield {"stem": stem, "session": sess, "image": jpg,
               "label": os.path.join(P["sessions"], sess, "labels", stem + ".txt")}


def _split_of(stem, val_ratio, seed) -> str:
    h = hashlib.sha1(f"{seed}:{stem}".encode()).hexdigest()
    return "val" if (int(h[:8], 16) / 0xFFFFFFFF) < val_ratio else "train"


def _emit_split(root, ds, s, sp, names, stats, link, count=True):
    """把一个样本放进 dataset/{images,labels}/<sp>/ (硬链接优先, 跨盘自动拷贝)"""
    import cv2
    img = cv2.imread(s["image"])
    if img is None:
        print(f"  ⚠️ 读不到图片, 跳过: {s['image']}")
        return
    ext = os.path.splitext(s["image"])[1]
    d_img = os.path.join(ds, "images", sp, s["stem"] + ext)
    d_lbl = os.path.join(ds, "labels", sp, s["stem"] + ".txt")
    if os.path.exists(d_img):
        os.remove(d_img)
    if link:
        try:
            os.link(s["image"], d_img)
        except OSError:
            shutil.copy2(s["image"], d_img)
    else:
        shutil.copy2(s["image"], d_img)
    lines = _read_lines(s["label"])
    with open(d_lbl, "w", encoding="utf-8") as f:
        f.write(("\n".join(lines) + "\n") if lines else "")
    stats["n_" + sp] += 1                     # 张数按落盘实际统计 (train/val 各自真实张数)
    if not count:
        return                                # 类别分布/框数只算一次 (小样本 val 是 train 副本)
    for ln in lines:
        cid = int(float(ln.split()[0]))
        k = names[cid] if 0 <= cid < len(names) else f"<非法类 {cid}>"
        stats["per_class"][k] = stats["per_class"].get(k, 0) + 1
        stats["n_boxes"] += 1


def build_dataset(root=ROOT_DEFAULT, val_ratio=0.15, seed=0, link=True) -> dict:
    """会话层 → dataset/{images,labels}/{train,val} + data.yaml + stats.json"""
    import cv2
    P = ensure_layout(root)
    ds = P["dataset"]
    for sp in ("train", "val"):
        for k in ("images", "labels"):
            os.makedirs(os.path.join(ds, k, sp), exist_ok=True)
            for old in glob.glob(os.path.join(ds, k, sp, "*")):
                os.remove(old)
    names = load_classes(root)
    samples = list(iter_samples(root))
    # 小样本兜底: ultralytics 必须有非空 val; 样本太少时 val=train (并在 stats 里**显式标注**,
    # 因为"train=val 同数据"会让 mAP 虚高 —— 只用于跑通管线, 不能当精度证据)
    small = len(samples) < 8
    stats = {"root": root, "built": time.strftime("%F %T"), "val_ratio": val_ratio, "seed": seed,
             "classes": names, "n_train": 0, "n_val": 0, "per_class": {}, "n_boxes": 0,
             "n_samples": len(samples), "val_overlap_train": bool(small),
             "note": ("样本<8: val 复用 train (只用于跑通训练管线, mAP 不可信)" if small
                      else "val 按文件名哈希划分, 与 train 无重叠"),
             "sessions": sorted({s["session"] for s in samples})}
    if not small and all(_split_of(s["stem"], val_ratio, seed) != "val" for s in samples):
        # 哈希碰巧没划出 val → 强制把"哈希最大"的一张划进 val (保证 data.yaml 的 val 非空)
        biggest = max(samples, key=lambda s: hashlib.sha1(f"{seed}:{s['stem']}".encode()).hexdigest())
        forced = {biggest["stem"]}
    else:
        forced = set()
    for s in samples:
        sp = "val" if (small or s["stem"] in forced) else _split_of(s["stem"], val_ratio, seed)
        splits = ("train", "val") if small else (sp,)
        for sp_i in splits:
            # 小样本时 val 是 train 的副本 → 统计只算一次 (否则类别分布/框数翻倍, 看数据时被误导)
            _emit_split(root, ds, s, sp_i, names, stats, link,
                        count=(not small) or sp_i == "train")
    yml = ["# 由 tools/yolo_annot_dataset.py --build 生成 — 别手改 (改完会被下一次 --build 覆盖)",
           f"path: {os.path.abspath(ds)}", "train: images/train", "val: images/val",
           f"nc: {len(names)}", "names:", *[f"  {i}: {n}" for i, n in enumerate(names)]]
    with open(os.path.join(ds, "data.yaml"), "w", encoding="utf-8") as f:
        f.write("\n".join(yml) + "\n")
    # 📌 真值聚合 (老倪 2026-09-17: 「训练要有光模块位置/距离」): 各会话 truth.jsonl → dataset/truth.jsonl
    #    训练/标定只读这一个文件就能拿到每张图的 3D 真值 (与仿真 data/yolo_peg 的真值投影标签同口径)
    stems = {s["stem"] for s in samples}
    trows = []
    for tp in sorted(glob.glob(os.path.join(P["sessions"], "*", "truth.jsonl"))):
        for ln in _read_lines(tp):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("stem") in stems:               # 只留图还在的 (删过的样本不留真值)
                trows.append(r)
    with open(os.path.join(ds, "truth.jsonl"), "w", encoding="utf-8") as f:
        for r in trows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["n_truth"] = len(trows)
    stats["truth_file"] = os.path.join(ds, "truth.jsonl")
    _write_json(os.path.join(ds, "stats.json"), stats)
    return stats


def check_dataset(root=ROOT_DEFAULT, strict=False) -> dict:
    """体检: 图片/标注配对, 标签格式, 类别范围, 坐标范围, 退化框, 重复图, 空标注统计, data.yaml"""
    import cv2
    P = paths(root)
    names = load_classes(root)
    rep = {"n_images": 0, "n_labels": 0, "n_boxes": 0, "n_empty_label": 0, "errors": [], "warnings": [],
           "per_class": {}, "sessions": {}, "data_yaml": None}
    if not names:
        rep["errors"].append("classes.txt 为空 (没有类别)")
    for s in iter_samples(root):
        rep["n_images"] += 1
        rep["sessions"][s["session"]] = rep["sessions"].get(s["session"], 0) + 1
        img = cv2.imread(s["image"])
        if img is None:
            rep["errors"].append(f"图片读不到: {s['image']}")
            continue
        h, w = img.shape[:2]
        if not os.path.isfile(s["label"]):
            rep["errors"].append(f"缺标注文件: {s['label']} (每张图都必须有 .txt, 背景样本写空文件)")
            continue
        rep["n_labels"] += 1
        lines = _read_lines(s["label"])
        if not lines:
            rep["n_empty_label"] += 1
            rep["warnings"].append(f"空标注 (背景样本): {os.path.basename(s['image'])}")
        for i, ln in enumerate(lines, 1):
            p = ln.split()
            if len(p) != 5:
                rep["errors"].append(f"{s['stem']}:{i} 字段数 {len(p)}≠5 → {ln!r}")
                continue
            try:
                cid = int(float(p[0]))
                cx, cy, bw, bh = [float(v) for v in p[1:5]]
            except ValueError:
                rep["errors"].append(f"{s['stem']}:{i} 非数值 → {ln!r}")
                continue
            if not (0 <= cid < len(names)):
                rep["errors"].append(f"{s['stem']}:{i} class id {cid} 超出类别表 (0..{len(names)-1})")
                continue
            if not (0 <= cx <= 1 and 0 <= cy <= 1):
                rep["errors"].append(f"{s['stem']}:{i} 中心 {cx},{cy} 不在 [0,1]")
            if not (0 < bw <= 1 and 0 < bh <= 1):
                rep["errors"].append(f"{s['stem']}:{i} 宽高 {bw},{bh} 非法")
            if bw * w < 2 or bh * h < 2:
                rep["warnings"].append(f"{s['stem']}:{i} 框太小 ({bw*w:.1f}x{bh*h:.1f}px) → 训练噪声")
            rep["n_boxes"] += 1
            rep["per_class"][names[cid]] = rep["per_class"].get(names[cid], 0) + 1
    # 重复图片 (同 md5 = 同一帧被重复标定 → 会泄漏到 train/val 两侧)
    seen = {}
    for s in iter_samples(root):
        try:
            m = hashlib.md5(open(s["image"], "rb").read()).hexdigest()
        except Exception:                                                  # noqa: BLE001
            continue
        if m in seen:
            rep["warnings"].append(f"重复图片: {s['stem']} == {seen[m]} (同 md5)")
        seen[m] = s["stem"]
    yp = os.path.join(P["dataset"], "data.yaml")
    if os.path.isfile(yp):
        txt = open(yp, encoding="utf-8").read()
        rep["data_yaml"] = yp
        for must in ("train:", "val:", "nc:", "names:"):
            if must not in txt:
                rep["errors"].append(f"data.yaml 缺 {must}")
        if f"nc: {len(names)}" not in txt:
            rep["errors"].append(f"data.yaml 的 nc 与 classes.txt ({len(names)}) 不一致 → 重新 --build")
    else:
        rep["warnings"].append("dataset/data.yaml 不存在 → 还没 --build")
    if strict and rep["n_images"] == 0:
        rep["errors"].append("没有任何标定图片 (sessions/*/frames 为空)")
    return rep


def import_yolo_dir(root, src_dir, session, classes=None, tag="import") -> int:
    """把已有 YOLO 目录 (images/ + labels/ 或平铺) 导入成一个会话 (provenance 保留, 内容不改)"""
    import cv2
    P = ensure_layout(root, classes)
    sdir = os.path.join(P["sessions"], session)
    fdir, ldir = os.path.join(sdir, "frames"), os.path.join(sdir, "labels")
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(ldir, exist_ok=True)
    imgs = []
    for ext in IMG_EXT:
        imgs += glob.glob(os.path.join(src_dir, "**", "*" + ext), recursive=True)
    imgs = sorted(set(imgs))
    n = 0
    for ip in imgs:
        stem = os.path.basename(os.path.splitext(ip)[0])
        lp_cands = [os.path.join(os.path.dirname(ip).replace("images", "labels"), stem + ".txt"),
                    os.path.join(os.path.dirname(ip), stem + ".txt"),
                    os.path.join(src_dir, "labels", stem + ".txt")]
        lp = next((x for x in lp_cands if os.path.isfile(x)), None)
        if not lp:
            continue
        img = cv2.imread(ip)
        if img is None:
            continue
        h, w = img.shape[:2]
        out_stem = f"imp_{session}_{stem}"
        dst = os.path.join(fdir, out_stem + ".jpg")
        cv2.imwrite(dst, img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        lines = _read_lines(lp)
        with open(os.path.join(ldir, out_stem + ".txt"), "w", encoding="utf-8") as f:
            f.write(("\n".join(lines) + "\n") if lines else "")
        rec = {"stem": out_stem, "session": session, "image": dst,
               "label": os.path.join(ldir, out_stem + ".txt"), "w": w, "h": h,
               "n_boxes": len(lines), "device": "imported", "src": f"import:{src_dir}",
               "imported_from": ip, "saved": time.time(), "saved_iso": time.strftime("%F %T"),
               "annotator": tag, "classes": load_classes(root)}
        with open(P["annot"], "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
    _register_session(root, session, "imported", 0, 0, tag, f"import:{src_dir}")
    return n


def clean(root=ROOT_DEFAULT, drop_orphan_images=False) -> dict:
    """🧹 清理不配对的残留 (2026-09-17 老倪: 「我把图像删了, 但标注没删」)

    只删**孤儿标注** (有 .txt 没图) —— 这是最容易出错、且一定会让训练/体检报错的东西;
    **只有图没标签**默认保留不删 (那可能是刻意留的背景负样本, 或误删标注), 只统计并在返回里报出来,
    由 --check 提示人决定。dataset/ 是生成物, 清了无妨, 下一次 --build 会重建。
    返回 {sessions_removed, dataset_removed, orphan_images, orphan_labels_kept}
    """
    P = ensure_layout(root)
    ds = P["dataset"]
    removed, kept_imgs = 0, []
    # ① 会话层
    for sd in sorted(glob.glob(os.path.join(P["sessions"], "*"))):
        frames = {os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(sd, "frames", "*")) if p.lower().endswith(IMG_EXT)}
        labels = {os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(sd, "labels", "*.txt"))}
        for st in sorted(labels - frames):
            os.remove(os.path.join(sd, "labels", st + ".txt"))
            removed += 1
        kept_imgs += [os.path.join(sd, "frames", st + img)
                      for st in sorted(frames - labels) for img in [".jpg"]]
    # ② dataset 层 (生成物)
    for sp in ("train", "val"):
        di = {os.path.splitext(os.path.basename(p))[0]
              for p in glob.glob(os.path.join(ds, "images", sp, "*")) if p.lower().endswith(IMG_EXT)}
        dl = {os.path.splitext(os.path.basename(p))[0]
              for p in glob.glob(os.path.join(ds, "labels", sp, "*.txt"))}
        for st in sorted(dl - di):
            os.remove(os.path.join(ds, "labels", sp, st + ".txt"))
            removed += 1
        if drop_orphan_images:
            for st in sorted(di - dl):
                for img in glob.glob(os.path.join(ds, "images", sp, st + ".*")):
                    os.remove(img)
    return {"sessions_removed": removed, "orphan_images": len(kept_imgs),
            "orphan_image_list": [os.path.relpath(p, root) for p in kept_imgs]}


def reset(root=ROOT_DEFAULT, keep_audit=True) -> dict:
    """🗑 清空标定数据 (重来一遍用): 删 sessions 全部 + dataset 全部, **保留** classes.txt / README.md 结构。

    keep_audit=True: annotations.jsonl (谁标了什么的历史) 保留不清 —— 它是审计流水, 不是训练数据。
    meta.json 的会话清单/计数清零。删完请重新采集 (视频流窗口 → 标定模式 → 拖框 → 💾/⏭)。
    """
    P = ensure_layout(root)
    ds = P["dataset"]
    n = 0
    for sub in ("frames", "labels"):
        for p in glob.glob(os.path.join(P["sessions"], "*", sub, "*")):
            os.remove(p)
            n += 1
    for sub in (os.path.join("images", "train"), os.path.join("images", "val"),
                os.path.join("labels", "train"), os.path.join("labels", "val")):
        for p in glob.glob(os.path.join(ds, sub, "*")):
            os.remove(p)
            n += 1
    for f in ("data.yaml", "stats.json"):
        fp = os.path.join(ds, f)
        if os.path.isfile(fp):
            os.remove(fp)
            n += 1
    _write_json(P["meta"], {"version": 1, "created": time.strftime("%F %T"),
                            "sessions": [], "n_images": 0, "classes": load_classes(root),
                            "reset_at": time.strftime("%F %T")})
    if not keep_audit:
        open(P["annot"], "w").close()
    return {"removed": n, "classes": load_classes(root), "audit_kept": keep_audit}


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="真机 YOLO 标定数据管理 (目录规范/保存/构建/体检)")
    ap.add_argument("--root", default=ROOT_DEFAULT)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--classes", nargs="*", default=None)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--copy", action="store_true", help="拷贝而非硬链接 (跨盘/跨文件系统时)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--add-class", default=None)
    ap.add_argument("--import-yolo-dir", default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--clean", action="store_true",
                    help="清理孤儿标注 (有 .txt 没图); dataset 层一并清, 之后重新 --build")
    ap.add_argument("--reset", action="store_true",
                    help="清空全部标定数据 (sessions + dataset), 保留 classes.txt; 需 --yes 确认")
    ap.add_argument("--yes", action="store_true", help="配合 --reset: 跳过确认")
    a = ap.parse_args()

    if a.reset:
        if not a.yes:
            print(f"⚠️ 将清空 {a.root} 下全部标定数据 (sessions + dataset), 保留 classes.txt/README.md。")
            print("   确认请加 --yes 重跑。")
            return 2
        r = reset(a.root)
        print(f"✅ 已清空: 删除 {r['removed']} 个文件 · 类别表保留 {r['classes']} · 审计流水保留={r['audit_kept']}")
        return 0
    if a.clean:
        r = clean(a.root)
        print(f"🧹 清理完成: 删除孤儿标注 {r['sessions_removed']} 个 · "
              f"有图无标注保留 {r['orphan_images']} 个 (需查那就去 --check)")
        for p in r["orphan_image_list"][:10]:
            print("   ⚠️ 有图无标注:", p)
        return 0

    if a.add_class:
        print(f"class id = {add_class(a.root, a.add_class)} (类别表: {load_classes(a.root)})")
        return 0
    if a.init:
        P = ensure_layout(a.root, a.classes)
        print("✅ 初始化:", P["root"])
        print("   类别表:", load_classes(a.root))
        print("   说明:", P["readme"])
        return 0
    if a.import_yolo_dir:
        n = import_yolo_dir(a.root, a.import_yolo_dir, a.session or session_name("import"),
                            a.classes, tag="import")
        print(f"✅ 导入 {n} 张 → sessions/{a.session}")
        return 0 if n else 1
    if a.build:
        st = build_dataset(a.root, a.val_ratio, a.seed, link=not a.copy)
        print(f"✅ 构建完成: train={st['n_train']} val={st['n_val']} 框={st['n_boxes']} 类别={st['classes']}")
        print(f"   类别分布: {st['per_class']}")
        print(f"   data.yaml: {os.path.join(p := paths(a.root)['dataset'], 'data.yaml')}")
    if a.check:
        r = check_dataset(a.root, a.strict)
        print(f"体检: 图片 {r['n_images']} · 标注 {r['n_labels']} · 框 {r['n_boxes']} · "
              f"背景样本 {r['n_empty_label']} · 类别分布 {r['per_class']}")
        print(f"     会话: {r['sessions']}")
        for e in r["errors"][:20]:
            print("  ❌", e)
        for w in r["warnings"][:10]:
            print("  ⚠️", w)
        print("结论:", "✅ 通过" if not r["errors"] else f"❌ {len(r['errors'])} 个错误")
        if r["errors"]:
            return 1
    if a.stats:
        P = ensure_layout(a.root)
        meta = _read_json(P["meta"], {}) or {}
        print(json.dumps({"root": a.root, "classes": load_classes(a.root),
                          "n_images": meta.get("n_images"),
                          "sessions": meta.get("sessions")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
