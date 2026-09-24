# -*- coding: utf-8 -*-
"""aoi_head.py — 🔍 外观质量检测 · **质量检测任务头** (AOI head, 2026-09-24 老倪需求)

需求: 「外观质量检测节点 … 是 YOLO 模型的一个**新的质量检测任务头**, 你来设计任务头训练方案」

设计 (详见 docs/design/aoi_quality_head_and_console_20260924.md):
  · **一个头, 两个角色**: 定位类框给 ROI (图像定位/拉伸) + 缺陷类框给缺陷 (金手指/外观划伤)
  · **两级级联**: 全帧跑定位类 → 取金手指/本体/光口 ROI → 裁剪拉伸到判据分辨率 → ROI 内跑缺陷类
  · **兜底诚实**: 无权重/无检出 → 启发式 AOIQualityChecker 出判决表, 明标 `source="heuristic"`
    (绝不假装是模型输出)
  · **类别真源**: `AOI_CLASSES` 顺序 = classes.txt 行号 = class id; 缺陷↔DET-AOI-0x 映射见 DEFECT_TO_TARGET
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_MODELS = os.path.join(ROOT, "models")

# ── 类别 schema (定位类在前, 缺陷类在后; 顺序 = class id, 改动需同步 detection_targets.json) ──
AOI_LOC_CLASSES = ["module_body", "gold_finger", "optical_port"]
AOI_DEFECT_CLASSES = ["gf_scratch", "gf_contam", "gf_oxide", "gf_chip",
                      "app_scratch", "app_deform", "app_stain"]
AOI_CLASSES = AOI_LOC_CLASSES + AOI_DEFECT_CLASSES
CLASS_CN = {"module_body": "光模块本体", "gold_finger": "金手指", "optical_port": "光口端面",
            "gf_scratch": "金手指划痕", "gf_contam": "金手指污染", "gf_oxide": "金手指氧化/镀层缺损",
            "gf_chip": "金手指崩缺", "app_scratch": "外观划伤", "app_deform": "外观变形/毛刺",
            "app_stain": "外观污渍"}
# 缺陷 → DET-AOI-0x 目标 (flows/detection_targets.json 真源)
DEFECT_TO_TARGET = {
    "gf_scratch": "DET-AOI-01", "gf_contam": "DET-AOI-01", "gf_oxide": "DET-AOI-01",
    "gf_chip": "DET-AOI-01", "app_scratch": "DET-AOI-04", "app_deform": "DET-AOI-04",
    "app_stain": "DET-AOI-04",
}
# ROI 技能 → 定位类
ROI_SKILLS = {"gold_finger": ("🔍 金手指检查", "gold_finger"),
              "module_body": ("🪞 外观划伤", "module_body"),
              "optical_port": ("🔘 光口端面", "optical_port"),
              "full": ("🖼 全帧扫描", None)}


def default_weights_candidates():
    """质量检测权重候选 (在役软链优先; 无则回落到目标检测权重做域适应基座)。"""
    import glob
    cands = [os.path.join(_MODELS, "yolo_aoi_live.pt")]
    cands += sorted(glob.glob(os.path.join(ROOT, "runs", "detect", "outputs", "yolo_aoi*",
                                           "**", "weights", "best.pt"), recursive=True), reverse=True)
    return cands


class AoiQualityHead:
    """质量检测任务头 (级联推理 + 启发式兜底)。"""

    def __init__(self, weights: str | None = None, conf: float = 0.25, imgsz: int = 640,
                 zoom: float = 2.0, root: str | None = None):
        self.weights = weights
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.zoom = float(zoom)
        self.root = root or os.environ.get("ZMAX_ANNOT_ROOT_AOI",
                                           os.path.join(ROOT, "data", "yolo_aoi_annot"))
        self._model = None
        self._load_err = ""
        self.load_ms = 0.0
        self._load()

    # ── 权重加载 (无权重不是错误: 走启发式兜底) ──
    def _load(self):
        ws = self.weights
        if ws is None:
            for c in default_weights_candidates():
                if os.path.isfile(c):
                    ws = c
                    break
        if not ws or not os.path.isfile(ws):
            self._load_err = "无质量检测权重 → 启发式兜底 (判决表标 source=heuristic)"
            self.weights = ""
            return
        try:
            t0 = time.perf_counter()
            from ultralytics import YOLO
            self._model = YOLO(ws)
            self.load_ms = (time.perf_counter() - t0) * 1000.0
            self.weights = ws
        except Exception as e:                                             # noqa: BLE001
            self._load_err = f"权重加载失败 ({type(e).__name__}: {e}) → 启发式兜底"
            self._model = None

    @property
    def model_ready(self) -> bool:
        return self._model is not None

    @property
    def model_classes(self) -> list:
        try:
            return list(self._model.names.values()) if self._model else []
        except Exception:                                                  # noqa: BLE001
            return []

    # ── ① 定位 (全帧, 只取定位类) ──
    def locate(self, rgb) -> list:
        if not self.model_ready:
            return []
        import cv2
        bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)   # ultralytics 吃 BGR (实测坑)
        r = self._model.predict(bgr, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        out = []
        names = r.names
        for b in (r.boxes or []):
            cls = str(names.get(int(b.cls), int(b.cls))) if isinstance(names, dict) else str(names[int(b.cls)])
            if cls in AOI_LOC_CLASSES:
                x0, y0, x1, y1 = [float(v) for v in b.xyxy[0].tolist()]
                out.append({"cls": cls, "cn": CLASS_CN.get(cls, cls), "box": [x0, y0, x1, y1],
                            "conf": round(float(b.conf), 3)})
        return sorted(out, key=lambda d: -d["conf"])

    # ── ② 图像定位/拉伸 (ROI → 高分辨率判据图) ──
    def crop_stretch(self, rgb, box, out: int | None = None, pad: float = 0.12):
        """ROI 裁剪 (带 pad) → 拉伸到 out² (zoom 倍超采样)。返回 (roi_rgb, meta)。"""
        import cv2
        img = np.asarray(rgb)
        H, W = img.shape[:2]
        out = int(out or self.imgsz)
        if box is None:
            roi = img
            meta = {"box": [0, 0, W, H], "pad": 0.0, "zoom": 1.0, "src_shape": [H, W]}
        else:
            x0, y0, x1, y1 = [float(v) for v in box[:4]]
            bw, bh = x1 - x0, y1 - y0
            x0 = int(max(0, x0 - bw * pad)); x1 = int(min(W, round(x1 + bw * pad)))
            y0 = int(max(0, y0 - bh * pad)); y1 = int(min(H, round(y1 + bh * pad)))
            roi = img[y0:y1, x0:x1]
            meta = {"box": [x0, y0, x1, y1], "pad": pad, "src_shape": [H, W]}
        if roi.size == 0:
            return img, {"box": [0, 0, W, H], "pad": 0.0, "zoom": 1.0, "src_shape": [H, W], "empty": True}
        k = max(1.0, float(out) / max(1, min(roi.shape[:2]))) * max(1.0, float(self.zoom))
        roi2 = cv2.resize(roi, (out, out), interpolation=cv2.INTER_CUBIC if k >= 1 else cv2.INTER_AREA)
        meta.update({"zoom": round(k, 3), "out": out})
        return roi2, meta

    # ── ③ 缺陷检测 (ROI 内, 只取缺陷类; 结果逆变换回原帧坐标) ──
    def defect_detect(self, roi_rgb, meta) -> list:
        if not self.model_ready:
            return []
        import cv2
        bgr = cv2.cvtColor(np.asarray(roi_rgb), cv2.COLOR_RGB2BGR)
        r = self._model.predict(bgr, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        names = r.names
        H, W = meta["src_shape"]
        x0, y0, x1, y1 = meta["box"]
        sw, sh = (x1 - x0), (y1 - y0)
        out = []
        for b in (r.boxes or []):
            cls = str(names.get(int(b.cls), int(b.cls))) if isinstance(names, dict) else str(names[int(b.cls)])
            if cls not in AOI_DEFECT_CLASSES:
                continue
            rx0, ry0, rx1, ry1 = [float(v) for v in b.xyxy[0].tolist()]
            kx = sw / max(1.0, roi_rgb.shape[1]); ky = sh / max(1.0, roi_rgb.shape[0])
            bb = [max(0.0, x0 + rx0 * kx), max(0.0, y0 + ry0 * ky),
                  min(float(W), x0 + rx1 * kx), min(float(H), y0 + ry1 * ky)]
            out.append({"cls": cls, "cn": CLASS_CN.get(cls, cls), "target": DEFECT_TO_TARGET.get(cls, "-"),
                        "box": [round(v, 1) for v in bb], "conf": round(float(b.conf), 3)})
        return sorted(out, key=lambda d: -d["conf"])

    # ── 判决表 (启发式数值 + 学习头缺陷; 两者同表, 来源可辨) ──
    def verdict(self, roi_rgb, defects: list) -> dict:
        items, src = [], "heuristic"
        try:
            import sys
            sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
            from quality_check import AOIQualityChecker
            res = AOIQualityChecker().check(np.asarray(roi_rgb))
            items = [dict(it, source="heuristic") for it in res.get("items", [])]
        except Exception as e:                                             # noqa: BLE001
            items = [{"target_id": "-", "target": "启发式不可用", "defect": str(e)[:60],
                      "value": None, "threshold": "-", "pass": False, "source": "error"}]
        for d in defects:
            items.append({"target_id": d["target"], "target": CLASS_CN.get(d["cls"], d["cls"]),
                          "defect": f"学习头检出 {d['cn']}", "value": d["conf"],
                          "threshold": f"conf≥{self.conf}", "pass": False, "conf": d["conf"],
                          "box": d["box"], "source": "model"})
        return {"items": items, "pass": all(it["pass"] for it in items),
                "n_defects": len(defects), "src": src}

    # ── 主入口: 级联检查 ──
    def inspect(self, rgb, roi: str | None = "gold_finger", zoom: float | None = None) -> dict:
        if zoom:
            self.zoom = float(zoom)
        t0 = time.perf_counter()
        loc = self.locate(rgb)
        sel = None
        if roi:
            for l in loc:
                if l["cls"] == roi:
                    sel = l
                    break
        roi_img, meta = self.crop_stretch(rgb, sel["box"] if sel else None)
        defects = self.defect_detect(roi_img, meta)
        v = self.verdict(roi_img, defects)
        return {"ts": time.strftime("%H:%M:%S"), "roi_skill": roi, "loc": loc, "roi_meta": meta,
                "defects": defects, "verdict": v,
                "weights": os.path.basename(self.weights) if self.model_ready else "",
                "model_classes": self.model_classes,
                "note": self._load_err, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    # ── 数据/训练 (委托给已验证的标定数据层与训练器) ──
    def classes_path(self) -> str:
        return os.path.join(self.root, "classes.txt")

    def ensure_schema(self) -> str:
        """把 AOI 类别 schema 落到数据根 classes.txt (行号=class id)。"""
        os.makedirs(self.root, exist_ok=True)
        p = self.classes_path()
        cur = []
        if os.path.isfile(p):
            cur = [x.strip() for x in open(p, encoding="utf-8") if x.strip()]
        if cur != AOI_CLASSES:
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(AOI_CLASSES) + "\n")
        return p

    def stats(self) -> dict:
        try:
            import sys
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import yolo_annot_dataset as yad
            return yad.check_dataset(self.root)
        except Exception as e:                                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
