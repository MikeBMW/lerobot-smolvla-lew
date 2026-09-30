"""规整金手指裁剪器 (模板法) —— v4 产线程序的核心, 可离线验证
流程: ①1/4 尺度粗搜角度 → ②1/1 尺度局部窗口精修(角度+尺度) → ③单次仿射映射到规范化画布
角度约定: 与模板生成完全一致 —— 都用 cv2.getRotationMatrix2D(c, a, 1.0)
输出: crop(BGR) + 结构化质量信息 (score/角度/条几何/顶边斜率/金覆盖率), 不达标自动兜底并标记
"""
import cv2
import numpy as np
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gf_metric import centerline_slope, top_edge_slope, core_band_slope


def _top_edge_slope(mask, frac_col=0.3, smooth=None):
    return top_edge_slope(mask, frac_col=frac_col)


class GoldFingerCropper:
    def __init__(self, template_png, canonical_w=1600, canonical_h=220,
                 margin_x=0.02, margin_y=0.03, preserve_aspect=False,
                 coarse_scale=0.25, coarse_angle=3.0, coarse_step=0.5,
                 fine_step=0.1, fine_scales=(0.97, 1.0, 1.03),
                 min_score=0.55, min_psr=6.0, min_gold_cover=0.35,
                 slope_tol=1.0, warm_span=0.25, cold_span=1.0):
        self.tpl = cv2.imread(template_png)
        if self.tpl is None:
            raise FileNotFoundError(template_png)
        self.tpl_gray = cv2.cvtColor(self.tpl, cv2.COLOR_BGR2GRAY)
        meta_path = os.path.splitext(template_png)[0] + ".json"
        if os.path.exists(meta_path):
            self.meta = json.load(open(meta_path))
        else:
            g = self._gold_mask(self.tpl)
            x, y, w, h = cv2.boundingRect(max(cv2.findContours(g, cv2.RETR_EXTERNAL,
                                                               cv2.CHAIN_APPROX_SIMPLE)[0],
                                                 key=cv2.contourArea))
            self.meta = {"strip_w": float(w), "strip_h": float(h),
                         "strip_off": [x + w / 2.0 - self.tpl.shape[1] / 2.0,
                                       y + h / 2.0 - self.tpl.shape[0] / 2.0]}
        self.canonical_w, self.canonical_h = canonical_w, canonical_h
        self.margin_x, self.margin_y = margin_x, margin_y
        self.preserve_aspect = preserve_aspect
        self.coarse_scale, self.coarse_angle, self.coarse_step = coarse_scale, coarse_angle, coarse_step
        self.fine_step, self.fine_scales = fine_step, fine_scales
        self.min_score, self.min_gold_cover = min_score, min_gold_cover
        self.min_psr = min_psr
        self.slope_tol = slope_tol
        self.warm_span, self.cold_span = warm_span, cold_span
        self.tuned_angle = None      # 上次调优的角度 (热启动)
        self._last_psr = None
        self.last = {}

    # ---------------- 基础 ----------------
    @staticmethod
    def _gold_mask(bgr, lo=(8, 60, 50), hi=(45, 255, 255), k=(41, 5)):
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        return cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, k))

    @staticmethod
    def _rot_tpl(tpl, angle, scale):
        t = cv2.resize(tpl, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        th, tw = t.shape[:2]
        M = cv2.getRotationMatrix2D((tw / 2.0, th / 2.0), angle, 1.0)
        ca, sa = abs(M[0, 0]), abs(M[0, 1])
        nw, nh = int(round(th * sa + tw * ca)), int(round(th * ca + tw * sa))
        M[0, 2] += nw / 2.0 - tw / 2.0
        M[1, 2] += nh / 2.0 - th / 2.0
        return cv2.warpAffine(t, M, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    @staticmethod
    def _match(gray, rt, win=None):
        if win is None:
            sub, off = gray, (0, 0)
        else:
            x0, y0, x1, y1 = win
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(gray.shape[1], x1), min(gray.shape[0], y1)
            sub, off = gray[y0:y1, x0:x1], (x0, y0)
        if sub.size == 0 or rt.shape[0] >= sub.shape[0] or rt.shape[1] >= sub.shape[1]:
            return None
        res = cv2.matchTemplate(sub, rt, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        # PSR (峰值/旁瓣): 平纹理模板会让 NCC 处处≈1 —— 用响应图的峰度甄别"真锁定"
        med = float(np.median(res))
        mad = float(np.median(np.abs(res - med))) + 1e-6
        psr = (float(mv) - med) / (1.4826 * mad)
        return {"score": float(mv), "psr": round(psr, 1),
                "center": (ml[0] + off[0] + rt.shape[1] / 2.0, ml[1] + off[1] + rt.shape[0] / 2.0)}

    # ---------------- 主流程 ----------------
    def locate(self, gray):
        """返回 (score, angle, scale, tpl_center_in_img); PSR 记到 self._last_psr"""
        cs = self.coarse_scale
        small = cv2.resize(gray, None, fx=cs, fy=cs, interpolation=cv2.INTER_AREA)
        best = None
        for a in np.arange(-self.coarse_angle, self.coarse_angle + 1e-6, self.coarse_step):
            m = self._match(small, self._rot_tpl(self.tpl_gray, a, cs))
            if m and (best is None or m["score"] > best[0]):
                best = (m["score"], float(a), cs, (m["center"][0] / cs, m["center"][1] / cs))
        if best is None:
            return None
        tw, th = self.tpl.shape[1], self.tpl.shape[0]
        cx, cy = best[3]
        win = (int(cx - tw * 0.6), int(cy - th * 0.6), int(cx + tw * 0.6), int(cy + th * 0.6))
        fine = None
        for s in self.fine_scales:
            for a in np.arange(best[1] - 1.0, best[1] + 1.0 + 1e-6, self.fine_step):
                m = self._match(gray, self._rot_tpl(self.tpl_gray, a, s), win)
                if m and (fine is None or m["score"] > fine[0]):
                    fine = (m["score"], float(a), float(s), m["center"], m.get("psr"))
        if fine:
            self._last_psr = fine[4]
            return fine[:4]
        self._last_psr = None
        return best

    def crop(self, bgr, return_debug=False):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        loc = self.locate(gray)
        if loc is None:
            return self._fallback(bgr, "模板匹配失败(图像尺寸/模板异常)")
        score, angle, scale, tc = loc
        psr = self._last_psr
        # ③ 角度精修: 在 ±span 内扫描, 取"裁剪图里条质心线斜率"最小者 —— 直接对准目标度量, 不猜符号
        angle, scan = self._refine_angle(bgr, angle, scale, tc)
        strip = self._strip_from(angle, scale, tc)
        out, M = self._warp(bgr, strip)                     # 规范化画布(默认拉伸到 canonical, 喂 YOLO)
        out_nat, _ = self._warp(bgr, strip, natural=True)    # 原比例(1:1 像素) —— 指标与目检用
        q = self._quality(bgr, out_nat)
        self.last = {"method": "template", "score": round(score, 4), "psr": psr,
                     "angle": round(angle, 3), "scale": round(scale, 4),
                     "strip": {k: round(v, 2) for k, v in strip.items()},
                     "quality": q, "canonical": (out.shape[1], out.shape[0]),
                     "natural": (out_nat.shape[1], out_nat.shape[0]), "angle_scan": scan}
        if score < self.min_score:
            self.last["warn"] = f"模板匹配弱 score={score:.3f} < {self.min_score} → 需人工复核"
        elif q["stripe_slope_px_per_1000"] is None:
            self.last["warn"] = f"裁剪内未找到金手指条(质心线无效) → 需人工复核"
        elif abs(q["stripe_slope_px_per_1000"]) > self.slope_tol:
            self.last["warn"] = (f"条仍有残余倾角 {q['stripe_slope_px_per_1000']:.1f}px/1000 "
                                 f"> 容差 {self.slope_tol} → 需人工复核")
        elif q["gold_cover"] < self.min_gold_cover:
            self.last["warn"] = f"裁剪内金覆盖低 {q['gold_cover']:.2f} → 需人工复核"
        self._last_natural = out_nat
        if return_debug:
            return out, self.last, {"M": M, "strip": strip, "tpl_center": tc, "natural": out_nat}
        return out, self.last

    def _refine_angle(self, bgr, angle0, scale, tc, span=None, step=0.05):
        # 热启动: 相机固定 → 上次调好的角度就在附近, 只扫小范围(省时间); 冷启动全扫
        if span is None:
            span = self.warm_span if self.tuned_angle is not None else self.cold_span
        if self.tuned_angle is not None and abs(angle0 - self.tuned_angle) < self.warm_span:
            angle0 = angle0
        best, curve = None, []
        n = int(round(2 * span / step)) + 1
        for i in range(n):
            a = angle0 - span + i * step
            out = self._try_strip(bgr, a, scale, tc)
            if out is None:
                continue
            s, res, cols = centerline_slope(self._gold_mask(out, k=(41, 5)), min_gold=8)
            pen = abs(s) if s is not None else 9e9
            curve.append((round(a, 3), None if s is None else round(s, 2)))
            if best is None or pen < best[0]:
                best = (pen, a, s, res)
        if best is None:
            return angle0, curve
        self.tuned_angle = best[1]
        return best[1], curve

    def _strip_from(self, angle, scale, tc):
        ox, oy = self.meta["strip_off"]
        R = cv2.getRotationMatrix2D((0, 0), angle, 1.0)
        return {"cx": float(tc[0] + scale * (R[0, 0] * ox + R[0, 1] * oy)),
                "cy": float(tc[1] + scale * (R[1, 0] * ox + R[1, 1] * oy)),
                "w": float(self.meta["strip_w"] * scale), "h": float(self.meta["strip_h"] * scale),
                "angle": float(angle), "scale": float(scale)}

    def _try_strip(self, bgr, angle, scale, tc):
        try:
            out, _ = self._warp(bgr, self._strip_from(angle, scale, tc))
            return out
        except Exception:
            return None

    @staticmethod
    def _dense_subset(gm, frac=0.95, pad=3):
        """只留"实心金带"核心那几行(行密度≥95%峰值) —— 规整度判据只看它
        实测(5张真图): 用全 ROI 算斜率会被上排离散焊盘带偏(-5~+2 px/1000); 只用核心带则 ≈0.0~0.15, 三套掩膜口径一致"""
        rows = (gm > 0).sum(axis=1)
        if rows.max() <= 0:
            return gm
        idx = np.where(rows > frac * rows.max())[0]
        if len(idx) < 8:
            return gm
        sub = np.zeros_like(gm)
        y0 = max(0, int(idx.min()) - pad)
        y1 = min(gm.shape[0], int(idx.max()) + pad + 1)
        sub[y0:y1, :] = gm[y0:y1, :]
        return sub

    def _crop_slope(self, crop):
        s, _, _ = core_band_slope(self._gold_mask(crop, k=(41, 5)))
        return s

    def _warp(self, bgr, strip, natural=False):
        if natural:
            cw, ch = int(round(strip["w"])), int(round(strip["h"]))
            mx = my = 0
        else:
            cw = self.canonical_w
            ch = self.canonical_h
            mx = int(round(cw * self.margin_x))
            my = int(round(ch * self.margin_y))
            if self.preserve_aspect:
                osw = cw - 2 * mx
                osh = max(1, int(round(osw * strip["h"] / strip["w"])))
                ch = osh + 2 * my
        scale = strip.get("scale", 1.0)
        R = cv2.getRotationMatrix2D((0, 0), strip["angle"], 1.0)   # 与 _rot_tpl 同一约定
        my_ = int(round(ch * self.margin_y)) if (self.preserve_aspect and not natural) else my
        dst = np.float32([[mx, my_], [cw - mx, my_], [cw - mx, ch - my_]])

        def src_pt(dx, dy):        # dx,dy = 模板空间里相对"条中心"的偏移
            return (strip["cx"] + scale * (R[0, 0] * dx + R[0, 1] * dy),
                    strip["cy"] + scale * (R[1, 0] * dx + R[1, 1] * dy))
        hw, hh = self.meta["strip_w"] / 2.0, self.meta["strip_h"] / 2.0
        src = np.float32([src_pt(-hw, -hh), src_pt(hw, -hh), src_pt(hw, hh)])
        # 注意方向: getAffineTransform(src→dst) 配 warpAffine(不带 WARP_INVERSE_MAP) 才是标准用法
        M = cv2.getAffineTransform(src, dst)
        out = cv2.warpAffine(bgr, M, (cw, ch), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return out, M

    def _quality(self, bgr, crop):
        gm_full = self._gold_mask(bgr, k=(41, 5))
        gm = self._gold_mask(crop, k=(41, 5))
        inside = float(gm.sum() / 255.0)
        total = float(gm_full.sum() / 255.0)
        # 规整度只看"实心金带"(最密的那段): 整块 ROI 含上排焊盘, 质心线会被拉歪, 不适合当判据
        rows = (gm > 0).sum(axis=1)
        band = None
        if rows.max() > 0:
            idx = np.where(rows > 0.35 * rows.max())[0]
            band = [int(idx.min()), int(idx.max())]
        rows_dense = (gm > 0).sum(axis=1)
        dense = None
        if rows_dense.max() > 0:
            didx = np.where(rows_dense > 0.95 * rows_dense.max())[0]
            if len(didx) > 8:
                dense = [int(didx.min()), int(didx.max())]
        gsub = self._dense_subset(gm)
        cslope, cresid, cols = core_band_slope(gm, min_gold=8)
        tslope, tresid = top_edge_slope(gsub)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        bright = float((gray > 180).mean())
        return {"gold_cover": round(inside / max(total, 1e-6), 3),
                "stripe_slope_px_per_1000": None if cslope is None else round(cslope, 2),
                "stripe_line_resid_px": None if cresid is None else round(cresid, 2),
                "stripe_cols": cols,
                "top_slope_px_per_1000": None if tslope is None else round(tslope, 2),
                "top_resid_std_px": None if tresid is None else round(tresid, 2),
                "bright_frac": round(bright, 4),
                "gold_px": int(inside), "band_rows_in_crop": band, "dense_rows_in_crop": dense,
                "crop_size": (crop.shape[1], crop.shape[0])}

    def _fallback(self, bgr, why):
        m = self._gold_mask(bgr)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            (cx, cy), (w, h), _ = cv2.minAreaRect(c)
            if w < h:
                w, h = h, w
            # 枚举角度让掩膜外接矩形最小 → 条的水平角
            best = None
            for a in np.arange(-6, 6.01, 0.2):
                M = cv2.getRotationMatrix2D((cx, cy), a, 1.0)
                rm = cv2.warpAffine(m, M, (m.shape[1], m.shape[0]), flags=cv2.INTER_NEAREST)
                cs, _ = cv2.findContours(rm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not cs:
                    continue
                x, y, bw, bh = cv2.boundingRect(max(cs, key=cv2.contourArea))
                if best is None or bw * bh < best[0]:
                    best = (bw * bh, a, bw, bh)
            if best:
                _, a, bw, bh = best
                strip = {"cx": float(cx), "cy": float(cy), "w": float(bw), "h": float(bh),
                         "angle": float(a), "scale": 1.0}
                out, M = self._warp(bgr, strip)
                self.last = {"method": "hsv_fallback", "score": None, "angle": float(a),
                             "strip": {k: round(v, 2) for k, v in strip.items()},
                             "quality": self._quality(bgr, out), "warn": why}
                return out, self.last
        h, w = bgr.shape[:2]
        strip = {"cx": w / 2.0, "cy": h * 0.65, "w": 1520.0, "h": 131.0, "angle": 0.0, "scale": 1.0}
        out, M = self._warp(bgr, strip)
        self.last = {"method": "center_fallback", "score": None, "warn": why + " + 无金像素",
                     "quality": self._quality(bgr, out)}
        return out, self.last


def annotate(bgr, info):
    im = bgr.copy()
    s = info.get("strip") or {}
    if s:
        cx, cy, w, h, a = s["cx"], s["cy"], s["w"], s["h"], s.get("angle", 0.0)
        R = cv2.getRotationMatrix2D((0, 0), a, 1.0)
        pts = []
        for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
            pts.append([int(cx + R[0, 0] * dx + R[0, 1] * dy), int(cy + R[1, 0] * dx + R[1, 1] * dy)])
        cv2.polylines(im, [np.array(pts, np.int32)], True, (0, 0, 255), 4)
        for p in pts:
            cv2.circle(im, tuple(p), 12, (255, 0, 0), -1)
        q = info.get("quality", {})
        txt = f"{info['method']} score={info.get('score')} angle={info.get('angle')} slope={q.get('top_slope_px_per_1000')}"
        cv2.putText(im, txt, (max(20, int(cx - w / 2)), max(60, int(cy - h / 2) - 30)),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 0), 4)
    return im
