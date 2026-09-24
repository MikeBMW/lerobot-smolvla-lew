# -*- coding: utf-8 -*-
"""focus_quality.py — 融合定位: 模糊识别 → 归因 → 复焦补偿位姿引导 (2026-09-24 老倪需求)

为什么需要 (现状实测):
  外观质量检测 `yolo_3d/quality_check.py` 用 `focus = cv2.Laplacian(gray).var()` + **绝对阈值 focus_min=60**
  判定 `DET-AOI-02 对焦不良/端面破损` → ① **离焦被误判成缺陷** (其注释自己写明了这个混淆)
  ② 只判不修 ③ 全图级非目标 ROI。本模块把"模糊"从**判定项**改成**可观测状态量 + 可补偿量**:

    量测 (ROI 级) → 归因 (曝光/运动/离焦/不可恢复) → 补偿 (沿光轴扫焦 + 修正位姿引导) → 复检闭环

判据口径 (经物理复核, 2026-09-24):
  模糊量用**物理可解释的离焦半径 σ_est (px)** 表达, 由高频能量比反演 (R0 标定常数 c_hf);
  质量分 `q = exp(-(σ_est/σ_tol)²)`, **放行 q_ok=0.78 ⟺ σ_est ≤ 1.0px** (端面/金手指 ROI 可用边缘判缺陷的界限)。
  ⚠️ **"能否修"的决定性判据 = 扫焦行程内 q 峰值能否到放行线**, 不是"q 随 Z 变不变":
     相机在臂上(eye-in-hand), 任意原因导致的图像模糊**都会**随 Z 变化 → 用"变化量"判固有缺陷是错的。
     正确二分: 扫焦后 `q_best ≥ q_ok` → 离焦(可修, 继续复检) ; `q_best < q_ok` → **不可恢复**
     (端面散射/破损/污染/遮挡 → 如实报 NG 转人工, 绝不"移臂硬修")。

设计约束 (老倪架构原则: 上层只给意图/条件, 执行由 L2 收口):
  本模块**只产出** {pose_corrected, intent, expect} —— 不下发动作; 限幅 / 阶段白名单 / 势函数兜底由 L2 闸执行。
"""
from __future__ import annotations

import time

import numpy as np

try:
    import cv2
except ImportError:                                          # 无 cv2 → 显式报错, 不静默假装
    cv2 = None

# ── 工程默认 (产线标定起点; models/focus_curve.json 标定后覆盖 c_hf/sigma_tol) ────────────
DEF = {
    "c_lap": 0.54,         # 拉普拉斯比→σ 反演常数 (R0 标定): σ_est = c_lap·sqrt(1/√r_lap − 1)
    #   为什么不用 HF 比: 2026-09-24 真机实测 HF 比在 σ≥2px 就下溢乱跳 (σ_est 4.7→18.3 非单调),
    #   而拉普拉斯比在 0.5~6px 全程单调 (0.62/1.54/2.79/3.67/4.45) → 只有它能当扫焦信号。
    "sigma_tol": 2.00,     # q 曲线尺度 (px): q=exp(-(σ/σ_tol)²)
    "q_ok": 0.78,          # 放行线 (⟺ σ_est ≤ 1.0px); ≥ 才允许进 AOI 缺陷判定
    "q_warn": 0.50,        # 告警线
    "clip_hi_max": 0.02,   # 过曝像素占比上限 (曝光归因)
    "mean_ratio_min": 0.50,  # 欠曝判据 (相对参考帧): mean < 0.5·ref_mean → 曝光异常
    "mean_abs_min": 0.03,    # 绝对黑帧线 (mean < 3% → 黑帧/镜头盖)
    "ten_min": 50.0,       # 🚦 有效帧闸: ROI Tenengrad 下限 (低于=无结构: 全黑/遮挡/糊到无边缘)
    "std_min": 5.0,        # 🚦 有效帧闸: ROI 灰度 std 下限
    "aniso_band": 0.60,      # 方向性只用最高频带 (实测该带对拖影最敏感: 基线 0.99 vs 拖影 1.7~2.0)
    "aniso_ratio_min": 1.60,  # 方向性**只作正向佐证**: >1.6×基线 才认"疑似运动"
                              #   ⚠️ 实测该判据**方向依赖** (0°/90° 拖影 aniso 反而降到 0.52×/0.62×基线)
                              #   → 运动归因的**主判据是臂速 (编码器真值)**, 图像方向性只作补充
    "sigma_max": 5.00,       # σ 估计封顶 (px): 超出行程可修范围即饱和 (保守: q 更小=更严格)
    "flat_span": 0.05,     # 扫焦曲线波动 < 5% → 对 Z 不敏感 (散射/遮挡类)
    "steps_mm": (3.0, 1.0, 0.3),   # 扫焦步长序列 (粗→细)
    "probe_mm": 1.0,       # 定方向微探步长 (q(σ) 单调 → 1mm 足够判符号, 不浪费行程)
    "travel_mm": 30.0,     # 累计行程上限 (安全)
    "max_iter": 3,         # 细扫每级步长最大迭代 (粗扫不受此限, 受 travel_mm 限)
}
EPS = 1e-9


# ══════════════════════ ① 量测 (ROI 级) ══════════════════════
def roi_from_box(frame, box=None, pad=0.15):
    """YOLO 框 → ROI 裁剪 (带 pad)。box=None → 画面中心 60% (无检测兜底, 返回 roi='center')。"""
    img = np.asarray(frame)
    H, W = img.shape[:2]
    if box is None:
        h, w = int(H * 0.6), int(W * 0.6)
        y0, x0 = (H - h) // 2, (W - w) // 2
        return img[y0:y0 + h, x0:x0 + w], "center"
    x0, y0, x1, y1 = [float(v) for v in box[:4]]
    bw, bh = x1 - x0, y1 - y0
    x0 = int(max(0, x0 - bw * pad)); x1 = int(min(W, x1 + bw * pad))
    y0 = int(max(0, y0 - bh * pad)); y1 = int(min(H, y1 + bh * pad))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return img, "center"
    return img[y0:y1, x0:x1], "box"


def _gray_of(img):
    a = np.asarray(img)
    if a.dtype != np.uint8:
        a = np.clip(a * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY) if a.ndim == 3 else a


def blur_metrics(frame, box=None):
    """ROI → 清晰度指标 + 曝光指标 (全部真实图像处理, 无写死值)。"""
    if cv2 is None:
        raise RuntimeError("cv2 不可用 (需 gui-venv311 / opencv)")
    roi, src = roi_from_box(frame, box)
    g = _gray_of(roi)
    gf = g.astype(np.float32)

    lap = float(cv2.Laplacian(g, cv2.CV_64F).var())              # ① 拉普拉斯方差 (锐度, 与现有 AOI 同口径)
    gx = cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_64F, 0, 1, ksize=3)
    ten = float(np.mean(gx * gx + gy * gy))                     # ② Tenengrad 梯度能量

    h, w = g.shape
    n = min(h, w, 192)                                          # 统一下采样 (可比值 + 省时)
    gs = cv2.resize(gf, (n, n), interpolation=cv2.INTER_AREA)
    win = np.outer(np.hanning(n), np.hanning(n))
    F = np.abs(np.fft.fftshift(np.fft.fft2((gs - gs.mean()) * win)))
    gm = _geom(n)
    r = gm["r"]
    hi = (r > 0.25 * gm["rmax"]) & (r < gm["rmax"])
    lo = (~hi) & (r > 0)
    hf = float((F[hi] ** 2).sum() / ((F[lo] ** 2).sum() + EPS))  # ③ 高频/中低频 能量比 (模糊=高频被砍)
    aniso, theta = _angular_profile(F, n, DEF["aniso_band"])      # ④ 方向性 (最高频带, 只作运动佐证)

    return {"lap": lap, "ten": ten, "hf": hf, "std": float(g.std()),
            "clip_hi": float((g >= 250).mean()), "mean": float(g.mean()) / 255.0,
            "aniso": aniso, "aniso_theta": theta,
            "roi": src, "shape": tuple(g.shape)}


_GEOM: dict = {}          # 按尺寸缓存频谱几何 (避免每帧重算 mgrid/掩码: 45ms → <10ms)
_ANG_BINS: dict = {}


def _geom(n):
    g = _GEOM.get(n)
    if g is None:
        yy, xx = np.mgrid[0:n, 0:n]
        r = np.hypot(yy - n / 2.0, xx - n / 2.0)
        g = {"r": r, "rmax": float(r.max()),
             "ang": np.degrees(np.arctan2(yy - n / 2.0, xx - n / 2.0)) % 180.0}
        _GEOM[n] = g
    return g


def _ang_bins(n, band):
    key = (n, round(float(band), 3))
    b = _ANG_BINS.get(key)
    if b is None:
        gm = _geom(n)
        mask = gm["r"] > band * gm["rmax"]
        b = [mask & (np.abs(((gm["ang"] - a + 90) % 180) - 90) < 2.0) for a in range(0, 180, 2)]
        _ANG_BINS[key] = b
    return b


def _angular_profile(F, n, band):
    """频带内角度能量分布 → (方向性 aniso, 峰值角 θ°)。aniso≈0 各向同性; 大 = 方向条带。"""
    p = np.asarray([float(F[b].mean()) if b.any() else 0.0 for b in _ang_bins(n, band)], float)
    aniso = float((np.percentile(p, 90) - np.percentile(p, 10)) / (p.mean() + EPS))
    return aniso, float(np.arange(0, 180, 2)[int(np.argmax(p))])


def frame_valid(m):
    """🚦 有效帧闸: ROI 有没有**真实结构** (2026-09-24 真机实测缺口)。
    现役 AOI 真机帧实测 mean=8.4/255 · 全图 Tenengrad≈4 · 9 宫格全平 → **黑帧/无结构**,
    这种图既不能判模糊也不能判缺陷 (对 0 结构的图做"清晰度"毫无意义)。
    故任何质量/缺陷判定前先过闸: 无效 → reason='no_target', **不判不修**, 先查取图链路
    (相机选源/曝光/遮挡/镜头盖; 取证口径见技能 camera-frame-forensics)。
    """
    bad = []
    if m["ten"] < DEF["ten_min"]:
        bad.append(f"Tenengrad={m['ten']:.1f} < {DEF['ten_min']:.0f} (无结构)")
    if m["std"] < DEF["std_min"]:
        bad.append(f"std={m['std']:.1f} < {DEF['std_min']:.0f} (近乎平坦)")
    if m["mean"] < DEF["mean_abs_min"]:
        bad.append(f"mean={m['mean']*100:.1f}% < {DEF['mean_abs_min']*100:.0f}% (黑帧/镜头盖)")
    return (len(bad) == 0), ("无效帧: " + " · ".join(bad) if bad else "有效帧")


def estimate_sigma(m, ref, c_lap=None):
    """拉普拉斯比反演离焦半径 σ_est (px)。
    理论: r_lap = Var(∇²I_σ)/Var(∇²I*) = (σ₀²/(σ₀²+σ²))² → σ = c_lap·sqrt(1/√r_lap − 1)。
    实测 (2026-09-24 真机帧) 在 0.5~6px 全程单调 (0.62/1.54/2.79/3.67/4.45), 故可作扫焦信号;
    σ≳3px 后趋于饱和 → 封顶 sigma_max (保守方向: q 更小 = 更严格)。
    """
    c = DEF["c_lap"] if c_lap is None else c_lap
    r_lap = max(m["lap"] / (ref["lap"] + EPS), 1e-9)
    s = float(c * np.sqrt(max(1.0 / np.sqrt(r_lap) - 1.0, 0.0)))
    return float(min(s, DEF["sigma_max"]))


def quality_score(m, ref, c_hf=None, sigma_tol=None):
    """质量分 q ∈ (0,1]: q = exp(−(σ_est/σ_tol)²); 放行 q_ok=0.78 ⟺ σ_est ≤ 1.0px。"""
    s = estimate_sigma(m, ref, c_hf)
    tol = DEF["sigma_tol"] if sigma_tol is None else sigma_tol
    return float(np.exp(-(s / tol) ** 2))


# ══════════════════════ ② 归因 ══════════════════════
def motion_anisotropy(frame, box=None):
    """频谱角度分布方向性 (≈0 各向同性→离焦; 大→方向条带→运动模糊)。返回 (aniso, θ°) 。"""
    m = blur_metrics(frame, box)          # 与量测同源 (同一份频谱, 避免两套实现漂移)
    return float(m["aniso"]), float(m["aniso_theta"])


def attribute(m, ref, dq_dz=None, speed_norm=0.0, aniso=None):
    """归因 → (reason, detail)。顺序: 有效帧闸 → 曝光 → 运动 → 清晰 → 离焦候选 (能否修由扫焦结果定)。"""
    ok, why = frame_valid(m)
    if not ok:
        return "no_target", why          # 无效帧: 不判不修, 先查取图链路 (相机/曝光/遮挡)
    q = quality_score(m, ref)
    if m["clip_hi"] > DEF["clip_hi_max"]:
        return "exposure", f"过曝 clip_hi={m['clip_hi']*100:.1f}% > {DEF['clip_hi_max']*100:.0f}%"
    if m["mean"] < DEF["mean_ratio_min"] * (ref["mean"] + EPS):
        return "exposure", (f"欠曝 mean={m['mean']:.3f} < 0.5×参考帧({ref['mean']:.3f}) "
                            f"— 相对判据 (暗场工件正常值随参考帧, 不用绝对阈值)")
    if q >= DEF["q_ok"]:
        return "clear", f"清晰 σ_est={estimate_sigma(m,ref):.2f}px q={q:.2f} ≥ {DEF['q_ok']}"
    a = m["aniso"] if aniso is None else float(aniso)
    a_ref = float(ref.get("aniso", 0.0))
    # 🎯 运动归因**只用臂速 (编码器真值)**:
    #   2026-09-24 真机实测 —— 图像方向性比**无法区分**离焦与运动:
    #   离焦 σ≈5.4px 时 aniso=2.12 (2.70×基线), 端面散射 2.30 (2.93×), 而真运动 1.71 (2.17×)
    #   → 离焦把该比值抬得**更高**。任何"方向性 = 运动"的判据都会把离焦误杀。
    #   故图像只回答"糊不糊"(σ_est/q), "为什么糊"由系统状态回答 (臂速/曝光参数)。
    a_note = f" · 图像方向性 {a:.2f} (基线 {a_ref:.2f} → {a/(a_ref+EPS):.2f}×, **仅记录不作判据**)"
    if speed_norm > 0.15:
        return "motion", f"运动模糊 (臂速 {speed_norm:.2f} > 0.15, 编码器真值){a_note} → 驻停重拍, 不动臂"
    return "defocus", (f"离焦候选 σ_est={estimate_sigma(m,ref):.2f}px q={q:.2f} < {DEF['q_ok']}"
                       f"{' · Δq/Δz=%+.3f/mm' % dq_dz if dq_dz is not None else ''}{a_note} → 沿光轴扫焦")


def refocus_intent(reason, q=None):
    """归因 → 意图 (上层只给意图/条件; 执行由 L2 收口)。"""
    act = {"defocus": "refocus", "motion": "settle", "exposure": "light",
           "unresolvable": "none", "no_target": "inspect_chain", "clear": "none"}.get(reason, "none")
    return {"reason": reason, "action": act, "expect_q": DEF["q_ok"],
            "note": {"refocus": "沿光轴扫焦 (L2 限幅执行, 仅非接触阶段)",
                     "settle": "驻停稳定后再拍 (运动中不得判缺陷)",
                     "light": "调曝光/增益/补光后重拍",
                     "inspect_chain": "无效帧 (无结构/黑帧): 先查取图链路 (相机选源/曝光/遮挡/镜头), 不判不修",
                     "none": "不需补偿 (不可恢复项如实报 NG 转人工)"}.get(act, "")}


# ══════════════════════ ③ 补偿 (意图 + 修正位姿引导) ══════════════════════
def focus_dz_cmd(dq_dz, step_mm, travel_left_mm):
    """扫焦方向 (q 上升方向 = 对焦方向) → Δz 指令 (mm)。"""
    if dq_dz is None or abs(dq_dz) < EPS:
        return 0.0
    sgn = 1.0 if dq_dz > 0 else -1.0
    return float(np.clip(sgn * step_mm, -travel_left_mm, travel_left_mm))


def pose_with_focus_correction(pose, dz_mm, n_cam_in_base):
    """抓取位姿 + 沿相机光轴的 Δfocus → 修正后的位姿引导 (姿态不变, 仅平移)。

    pose: {x,y,z,rx,ry,rz} (抓握点, base 系, mm/deg) · n_cam_in_base: 光轴单位向量 (base 系, 手眼外参可得)
    """
    n = np.asarray(n_cam_in_base, float).ravel()[:3]
    n = n / (np.linalg.norm(n) + EPS)
    d = n * float(dz_mm)
    out = dict(pose)
    for k, i in (("x", 0), ("y", 1), ("z", 2)):
        out[k] = float(pose[k]) + float(d[i])
    out["focus_dz_mm"] = float(dz_mm)
    return out


# ══════════════════════ ④ 闭环状态机 (复焦 → 复检) ══════════════════════
class RefocusLoop:
    """复焦闭环: 拍 → 量测 → 归因 → 扫焦 → (可恢复/不可恢复)。

    camera_fn(z_mm) → frame: 相机在光轴位置 z 时的一帧 (仿真/真机同构接口)。
    本类只产出指令与判据 (不下发); 真实执行由 L2 把 dz_cmd 落到机械臂。
    """

    def __init__(self, ref, camera_fn, q_ok=None, travel_mm=None, box=None, speed_norm=0.0):
        self.ref = ref
        self.camera_fn = camera_fn
        self.q_ok = q_ok or DEF["q_ok"]
        self.travel_mm = travel_mm or DEF["travel_mm"]
        self.box = box
        self.speed_norm = speed_norm
        self.trace = []

    def _probe(self, z):
        t0 = time.perf_counter()
        frame = self.camera_fn(z)
        m = blur_metrics(frame, self.box)
        ms = (time.perf_counter() - t0) * 1000.0
        q = quality_score(m, self.ref)
        sig = estimate_sigma(m, self.ref)
        self.trace.append({"z_mm": round(float(z), 3), "q": round(q, 4),
                           "sigma_est_px": round(sig, 3), "lap": round(m["lap"], 1),
                           "hf": float(f"{m['hf']:.5g}"), "metric_ms": round(ms, 2),
                           "dz_cmd_mm": None})
        return q, m, ms

    def run(self, z0_mm):
        """返回 (ok, reason, z_final, detail); trace 含完整轨迹与逐步 Δz 指令。"""
        z = float(z0_mm)
        q, m, _ = self._probe(z)
        ok_f, why_f = frame_valid(m)                       # 🚦 无结构/黑帧 → 不判不修
        if not ok_f:
            return False, "no_target", z, why_f
        if q >= self.q_ok:
            return True, "clear", z, f"起始即清晰 q={q:.2f}"

        # ① 微探定方向 (1mm): q(σ) 单调 → 符号足够; 等值时反向再探一次 (地板区也能定向)
        aniso, _ = motion_anisotropy(self.camera_fn(z), self.box)
        p = DEF["probe_mm"]
        z2 = z + p
        q2, m2, _ = self._probe(z2)
        dqdz = (q2 - q) / p
        reason0, detail0 = attribute(m, self.ref, dq_dz=dqdz, speed_norm=self.speed_norm, aniso=aniso)
        if reason0 in ("exposure", "motion"):
            return False, reason0, z, detail0
        travel = p
        sgn = 1.0 if q2 >= q else -1.0
        if abs(q2 - q) < 1e-9:                       # 地板区等值 → 反向探一次定向
            z = z - p
            travel += p
            self._probe(z)
        else:
            z = z2                                  # 🐛 关键: 探针位置要落到状态上 (否则与实际 z 差一步)

        # ② 粗扫 (对比检测式 AF): 3mm 步长两方向对称扫描 ±travel/2。
        #   ⚠️ 为什么不用梯度爬山: 2026-09-24 实测深离焦 (σ>4px) 时 q 落到地板 (≈0.11) **无梯度**,
        #      任何"沿上升方向走"的爬山都会迷路 (实测 12mm 偏差走不回来)。AF 的标准做法就是
        #      有界粗扫 + 局部细化 —— 不依赖梯度, 只依赖 q(z) 单峰 (R1a 已证)。
        step = DEF["steps_mm"][0]
        half = int((self.travel_mm * 0.5) // step)
        best_q, best_z = q, float(z0_mm)
        for k in range(1, half + 1):
            for s_ in (sgn, -sgn):
                zz = float(z0_mm + s_ * k * step)
                if abs(zz - z0_mm) > self.travel_mm * 0.5 or travel + step > self.travel_mm:
                    continue
                travel += step
                qq, _, _ = self._probe(zz)
                if qq > best_q:
                    best_q, best_z = qq, zz
                if qq >= self.q_ok:
                    break
            if self.trace[-1]["q"] >= self.q_ok:
                break
        z = best_z                                    # 落到粗扫最优位置
        if abs(self.trace[-1]["z_mm"] - z) > 1e-6:
            self._probe(z)

        # ③ 细扫: 1mm → 0.3mm 逐级收敛 (方向按 q 变化修正)
        for stp in DEF["steps_mm"][1:]:
            for _ in range(DEF["max_iter"]):
                if self.trace[-1]["q"] >= self.q_ok or travel + stp > self.travel_mm:
                    break
                q_cur = self.trace[-1]["q"]
                q_prev = self.trace[-2]["q"] if len(self.trace) > 1 else q_cur
                if q_cur < q_prev:
                    sgn = -sgn
                self.trace[-1]["dz_cmd_mm"] = round(sgn * stp, 3)
                z += sgn * stp
                travel += stp
                self._probe(z)
            if self.trace[-1]["q"] >= self.q_ok:
                break

        qs = [t["q"] for t in self.trace]
        spread = (max(qs) - min(qs)) / (max(qs) + EPS)
        q_best = max(qs)
        ok = q_best >= self.q_ok
        if ok:
            return True, "defocus", self.trace[-1]["z_mm"], \
                f"扫焦复焦成功 {len(self.trace)} 探测 / 行程 {travel:.2f}mm / q {qs[0]:.2f}→{q_best:.2f}"
        if spread < DEF["flat_span"]:
            return False, "unresolvable", z, \
                f"扫焦曲线近乎平坦 (波动 {spread*100:.1f}% < {DEF['flat_span']*100:.0f}%) → 非对焦所致, 不硬修"
        return False, "unresolvable", self.trace[-1]["z_mm"], \
            f"扫焦 {len(self.trace)} 探测 / 行程 {travel:.2f}mm 仍 q_best={q_best:.2f} < {self.q_ok} → 不可恢复 (破损/污染/遮挡), 报 NG 转人工"


def quality_channel(m, ref, reason, dz_mm=0.0, travel_mm=None):
    """统一状态空间质量通道: [q, Δz_focus 归一, focus_state]。focus_state: -1 不可恢复 / 0 待修 / 1 已清晰。"""
    q = quality_score(m, ref)
    state = 1 if q >= DEF["q_ok"] else (-1 if reason in ("unresolvable", "intrinsic") else 0)
    return [round(q, 4), round(float(dz_mm) / (travel_mm or DEF["travel_mm"]), 4), int(state)]
