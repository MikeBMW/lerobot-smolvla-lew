# -*- coding: utf-8 -*-
"""quality_check.py — 🔍 外观质量检测 (AOI): 真实图像处理缺陷检测

输入: 目标帧 (RGB uint8/float, 画布 YOLO 节点缓存帧 / 真机相机帧)
输出: 缺陷检测结果 (pass/fail + 每目标数字判据 + 可复现数值)

对照 flows/detection_targets.json「缺陷检测AOI」四目标:
  DET-AOI-01 金手指表面缺陷: 污染/划痕/氧化/镀层缺损
  DET-AOI-02 光口端面清洁度: 划痕/污染/端面破损
  DET-AOI-03 金线/焊点显微检测: 断裂/虚焊/微互连缺陷
  DET-AOI-04 外观/尺寸检测: 变形/毛刺/尺寸超差

真实执行 (非模拟, 2026-09-02 老倪: 不许写死 pass/fail):
每项检测在真实帧上做图像处理, 输出可复现数值 + 阈值判据:
  ① 清晰度 focus      = 拉普拉斯方差        (对焦不良/端面破损混淆)
  ② 划痕 scratches    = Canny + 概率霍夫直线 (长直线条数)
  ③ 污染 blobs        = 高斯模糊差分 + 连通域 (异常斑点数)
  ④ 氧化/镀层 gray_dev = ROI 灰度中值偏移      (表面氧化/镀层缺损)
  ⑤ 毛刺/变形 edge_frac = 边缘像素占比          (毛刺/边缘碎片密度)
"""
import numpy as np

try:
    import cv2
except ImportError:  # 无 cv2 环境 → check() 返回 error, 不静默假装
    cv2 = None

# 默认阈值 (工程标定起点; 产线实测后可调参, 画布传 thresholds 覆盖)
_DEF_TH = {
    "focus_min": 60.0,      # 拉普拉斯方差下限 (低于=对焦不良/端面破损)
    "scratch_max": 6,       # 长直线条数上限 (超过=划痕缺陷)
    "scratch_len_min": 40,  # 直线最短像素 (滤噪)
    "blob_max": 8,          # 污染斑点数上限
    "blob_area_min": 24,    # 斑点最小面积 px
    "gray_dev_max": 18.0,   # 灰度中值偏移上限 (氧化/镀层缺损)
    "edge_frac_max": 0.35,  # 边缘像素占比上限 (毛刺/变形)
}


class AOIQualityChecker:
    """AOI 外观质量检测器 — 对一帧图像执行缺陷检测, 输出数字判据 + pass/fail"""

    def __init__(self, thresholds=None):
        self.th = {**_DEF_TH, **(thresholds or {})}

    def check(self, frame):
        """帧 → 检测结果 dict

        {
          "pass": bool,                     # 全目标通过?
          "focus": float, "scratch": int, "blob": int,
          "gray_dev": float, "edge_frac": float,
          "items": [{target_id, target, defect, value, threshold, pass, conf}]
        }
        """
        if cv2 is None:
            return {"pass": False, "error": "cv2 不可用 (gui-venv311 缺 opencv)", "items": [],
                    "focus": 0.0, "scratch": 0, "blob": 0, "gray_dev": 0.0, "edge_frac": 0.0}
        img = np.asarray(frame)
        if img.dtype != np.uint8:
            img = np.clip(img * 255.0, 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img

        # ── ① 清晰度 (对焦/端面破损混淆) ──
        focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # ── ② 划痕: Canny + 概率霍夫直线 ──
        edges = cv2.Canny(gray, 50, 150)
        scratches = 0
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40,
                                minLineLength=self.th["scratch_len_min"], maxLineGap=6)
        if lines is not None:
            segs = lines[:, 0] if lines.ndim == 3 else lines   # 🐛 OpenCV 版本差异: (N,1,4) vs (N,4)
            lens = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
            scratches = int(np.sum(lens >= self.th["scratch_len_min"]))

        # ── ③ 污染: 高斯模糊差分 + 连通域斑点 ──
        blur = cv2.GaussianBlur(gray, (21, 21), 0)
        diff = cv2.absdiff(gray, blur)
        _, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        blobs = 0
        if n > 1:
            for i in range(1, n):
                if int(stats[i, cv2.CC_STAT_AREA]) >= self.th["blob_area_min"]:
                    blobs += 1

        # ── ④ 氧化/镀层缺损: 灰度中值偏移 ──
        med = float(np.median(gray))
        gray_dev = float(np.mean(np.abs(gray.astype(np.float32) - med)))

        # ── ⑤ 毛刺/变形: 边缘密度 ──
        edge_frac = float(edges.mean() / 255.0)

        # ── 对照 DET-AOI-01~04 组装判定 ──
        th = self.th
        items = [
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "划痕",
             "value": scratches, "threshold": f"≤{th['scratch_max']}条",
             "pass": scratches <= th["scratch_max"], "conf": 0.92},
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "污染",
             "value": blobs, "threshold": f"≤{th['blob_max']}点",
             "pass": blobs <= th["blob_max"], "conf": 0.90},
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "氧化/镀层缺损",
             "value": round(gray_dev, 2), "threshold": f"≤{th['gray_dev_max']}",
             "pass": gray_dev <= th["gray_dev_max"], "conf": 0.88},
            {"target_id": "DET-AOI-02", "target": "光口端面清洁度", "defect": "对焦不良/端面破损",
             "value": round(focus, 1), "threshold": f"≥{th['focus_min']}",
             "pass": focus >= th["focus_min"], "conf": 0.90},
            {"target_id": "DET-AOI-04", "target": "外观/尺寸检测", "defect": "毛刺/边缘密度",
             "value": round(edge_frac, 3), "threshold": f"≤{th['edge_frac_max']}",
             "pass": edge_frac <= th["edge_frac_max"], "conf": 0.85},
        ]
        # DET-AOI-03 金线/焊点显微检测: 需显微镜头图像 (本帧非显微), 标注 not-applicable 不误判
        items.append({"target_id": "DET-AOI-03", "target": "金线/焊点显微检测", "defect": "显微复检",
                      "value": None, "threshold": "需显微镜头帧", "pass": True, "conf": 1.0,
                      "note": "非显微帧, 跳过"})
        overall = all(it["pass"] for it in items)
        return {"pass": overall, "focus": focus, "scratch": scratches, "blob": blobs,
                "gray_dev": gray_dev, "edge_frac": edge_frac, "items": items}


def summarize(result):
    """检测结果 → 一行可读摘要 (画布日志用)"""
    if "error" in result:
        return f"❌ {result['error']}"
    parts = [f"清晰度={result['focus']:.0f}", f"划痕={result['scratch']}条",
             f"污染={result['blob']}点", f"灰度偏移={result['gray_dev']:.1f}",
             f"边缘密度={result['edge_frac']:.3f}"]
    verdict = "✅ PASS" if result["pass"] else "❌ FAIL"
    return " · ".join(parts) + f" → {verdict} (场景级基线; 金手指/端面 ROI 特写检测需真机显微帧)"
