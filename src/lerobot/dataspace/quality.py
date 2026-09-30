#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面数据质量管理 —— 规则求值器 (纯函数, 不依赖 DDS)

老倪 2026-09-29: 「全面数据质量管理」。规则定义在 topics.py::QUALITY_RULES, 这里做**求值**。
三级裁决(与现场口径一致):
  ok    正常
  warn  记录并显示, 不拦
  veto  拒用/拦下(必须有人处理; 例如标定无效、动作无闸门、帧龄为负)

设计原则:
  · 只对**该话题声明的规则**求值(见 topics.TOPICS[t]["quality"]) —— 不给没声明的量瞎判
  · 缺测(-1.0 / 空) 与 假 0 是两类不同的问题, 分开报
  · 任何规则求值抛异常 = warn(不 veto), 免得一条规则把整条链路卡死
"""
from typing import Any, Dict, List, Optional

# ───────── 判据阈值(集中放, 现场可调) ─────────
TH = {
    "frame_age_s": 5.0,        # 状态类: 超 5s 只报 diag(与守护 STALE_S 同口径)
    "neg_age_tol_s": 1.0,      # ts 超前 now 超过这么多 ⇒ 时间源异常
    "hz_tol": 0.35,            # 实测频率允许偏离设计值 35%
    "liveness_x": 3.0,         # 心跳缺失 > 3×周期
    "latency_ms": 1500.0,      # 推理延时预算(冷启另计)
    "rms_mm": 2.0,             # 手眼残差预算
    "zero_ratio": 0.98,        # 统计字段 0 占比超它 ⇒ 判"假 0"
}
ENUM = {
    "status": {"pending", "running", "success", "failed"},
    "layer": {"L2", "L3", "L4", "L5", "meta", "ALL"},
    "level": {"ok", "warn", "error"},
}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def _unmeasured(v: Any) -> bool:
    """缺测: None / -1.0 / 空列表 —— 全空间统一用 -1.0 表示未测, 不许 0 冒充"""
    if v is None:
        return True
    if isinstance(v, (list, tuple, str)):
        return len(v) == 0
    n = _num(v)
    return n is not None and n == -1.0


def _v(rule, ok, level, msg):
    return {"rule": rule, "ok": bool(ok), "level": level, "msg": msg}


def check(topic: str, fields: Dict[str, Any], now: Optional[float] = None,
          meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """对一个话题的一帧做质量裁决 → [{rule, ok, level, msg}]

    fields: 该帧字段(已白名单提取, 不含 DDS 元数据)
    meta:   probe 实测的 meta(如 {"hz": 12.1, "age_s": 0.2, "dim": 6})
    """
    import time
    from . import topics as T

    now = now if now is not None else time.time()
    meta = meta or {}
    out: List[Dict[str, Any]] = []
    rules = list(T.TOPICS.get(topic, {}).get("quality") or [])
    ts = _num(fields.get("ts"))
    age = (now - ts) if ts else None

    if "freshness" in rules:
        if age is None:
            out.append(_v("freshness", False, "warn", "无 ts 字段, 无法判帧龄"))
        elif age > TH["frame_age_s"]:
            out.append(_v("freshness", False, "warn", "帧龄 %.1fs > %.1fs" % (age, TH["frame_age_s"])))
        else:
            out.append(_v("freshness", True, "ok", "帧龄 %.2fs" % age))

    if "negative_age_reject" in rules:
        if age is not None and age < -TH["neg_age_tol_s"]:
            out.append(_v("negative_age_reject", False, "veto",
                          "帧龄为负 %.1fs(时间源回拨?) ⇒ 拒用" % age))

    if "no_zero_fake" in rules:
        vals = [x for k, x in fields.items()
                if k not in ("ts", "note", "source", "kind", "layer", "stage")
                and isinstance(x, (int, float))]
        un = sum(1 for x in vals if _num(x) == -1.0)
        zs = sum(1 for x in vals if _num(x) == 0.0)
        if vals and zs / float(len(vals)) >= TH["zero_ratio"] and un == 0:
            out.append(_v("no_zero_fake", False, "warn",
                          "%d/%d 个数值全为 0 且无 -1 缺测标记 ⇒ 疑似假 0" % (zs, len(vals))))
        else:
            out.append(_v("no_zero_fake", True, "ok", "缺测 %d 个(标 -1)/数值 %d 个" % (un, len(vals))))

    if "range" in rules:
        bad = []
        for k, lo, hi in (("util_pct", 0, 100), ("cpu_util_pct", 0, 100), ("temp_c", -20, 110),
                          ("health", 0, 1), ("conf", 0, 1), ("progress", 0, 1)):
            n = _num(fields.get(k))
            if n is not None and n != -1.0 and not (lo <= n <= hi):
                bad.append("%s=%s 越界[%s,%s]" % (k, n, lo, hi))
        out.append(_v("range", not bad, "warn" if bad else "ok", "; ".join(bad) or "范围内"))

    if "unit" in rules:
        # 命名即单位: *_pct / *_ms / *_mm / *_gb / *_mb / *_deg —— 只查"该带单位没带"
        bad = [k for k in ("util_pct", "mem_used_mb", "mem_total_mb", "latency_ms",
                           "plane_z_mm", "rms_mm", "disk_free_gb")
               if k in fields and not k.endswith(("_pct", "_mb", "_ms", "_mm", "_gb", "_deg", "_c", "_w", "_hz"))]
        out.append(_v("unit", not bad, "warn" if bad else "ok", "字段名均带单位" if not bad else str(bad)))

    if "latency_budget" in rules:
        n = _num(fields.get("latency_ms"))
        if n is None or n == -1.0:
            out.append(_v("latency_budget", False, "warn", "延时未测(-1)"))
        elif n > TH["latency_ms"]:
            out.append(_v("latency_budget", False, "warn", "延时 %.0fms > 预算 %.0fms" % (n, TH["latency_ms"])))
        else:
            out.append(_v("latency_budget", True, "ok", "延时 %.0fms" % n))

    if "liveness" in rules:
        al = _num(fields.get("alive"))
        out.append(_v("liveness", al == 1, "veto" if al != 1 else "ok",
                      "alive=%s" % fields.get("alive")))

    if "valid_flag" in rules:
        fv = _num(fields.get("valid"))
        lvl = "ok" if fv == 1 else ("veto" if fv == 0 else "warn")
        out.append(_v("valid_flag", fv == 1, lvl, "valid=%s(0=无效 不许用, -1=未知)" % fields.get("valid")))

    if "rms_budget" in rules:
        n = _num(fields.get("rms_mm"))
        if n is None or n == -1.0:
            out.append(_v("rms_budget", False, "warn", "残差未报"))
        elif n > TH["rms_mm"]:
            out.append(_v("rms_budget", False, "veto", "手眼残差 %.2fmm > %.1fmm ⇒ 标定不合格" % (n, TH["rms_mm"])))
        else:
            out.append(_v("rms_budget", True, "ok", "残差 %.2fmm" % n))

    if "counts_consistent" in rules:
        t_, p_, f_ = _num(fields.get("total")), _num(fields.get("passed")), _num(fields.get("failed"))
        if t_ is None or p_ is None or f_ is None:
            out.append(_v("counts_consistent", False, "warn", "计数缺失(total/passed/failed)"))
        else:
            ok = abs(t_ - (p_ + f_)) < 1e-9
            out.append(_v("counts_consistent", ok, "ok" if ok else "warn",
                          "total=%g, passed+failed=%g" % (t_, p_ + f_)))

    for key, rname in (("status", "status_enum"), ("layer", "layer_enum"), ("level", "level_enum")):
        if rname in rules:
            val = str(fields.get(key) or "")
            ok = val in ENUM[key]
            out.append(_v(rname, ok, "warn" if not ok else "ok", "%s=%r" % (key, val)))

    if "gate_audit" in rules:
        gp = fields.get("gate_pass")
        n = _num(gp)
        if n is None or n == -1:
            out.append(_v("gate_audit", False, "veto", "动作未带闸门判定(gate_pass=-1/缺失) ⇒ 不可接受"))
        else:
            out.append(_v("gate_audit", True, "ok", "gate_pass=%s reason=%s" % (gp, fields.get("gate_reason"))))

    if "finite" in rules:
        bad = [k for k, x in fields.items() if isinstance(x, float) and (x != x or abs(x) == float("inf"))]
        out.append(_v("finite", not bad, "veto" if bad else "ok", str(bad) or "有限"))

    if "artifact_exists" in rules:
        art = str(fields.get("artifact") or "")
        import os as _os
        if not art:
            out.append(_v("artifact_exists", False, "warn", "指令未带产物路径"))
        elif not _os.path.exists(art):
            out.append(_v("artifact_exists", False, "veto", "产物路径不存在: %s" % art))
        else:
            out.append(_v("artifact_exists", True, "ok", "产物存在"))

    if "audit_issuer" in rules:
        iss = str(fields.get("issuer") or "")
        out.append(_v("audit_issuer", bool(iss), "veto" if not iss else "ok", "issuer=%r" % iss))

    if "dim_match" in rules:
        dim, vec = _num(fields.get("dim")), fields.get("vec")
        if dim is None or dim == -1:
            out.append(_v("dim_match", False, "warn", "dim 未报"))
        elif not isinstance(vec, (list, tuple)) or len(vec) != int(dim):
            out.append(_v("dim_match", False, "warn", "vec 长度 %s != dim %s" % (len(vec or []), dim)))
        else:
            out.append(_v("dim_match", True, "ok", "dim=%d" % dim))

    if "monotonic_step" in rules and meta.get("prev_step") is not None:
        cur, prev = _num(fields.get("step")), _num(meta.get("prev_step"))
        if cur is not None and prev is not None:
            out.append(_v("monotonic_step", cur >= prev, "warn" if cur < prev else "ok",
                          "step %s ← %s" % (cur, prev)))

    if "loss_finite" in rules:
        n = _num(fields.get("loss"))
        running = _num(fields.get("running"))
        if n is None or n == -1.0:
            # 未训练 ⇒ loss 规范值就是 -1.0(未测), 不算违规; 但**在训**(running=1)却没 loss 才是问题
            ok = not (running == 1)
            out.append(_v("loss_finite", ok, "warn" if not ok else "ok",
                          "loss 未测(-1)%s" % ("但在训练中(running=1) ⇒ 异常" if running == 1 else "(当前无训练)")))
        else:
            bad = (n != n) or abs(n) == float("inf")
            out.append(_v("loss_finite", not bad, "veto" if bad else "ok", "loss=%g" % n))

    if "gain_reported" in rules:
        g = _num(fields.get("gain_obs_pct")) or 0.0
        g2 = _num(fields.get("gain_act_pct")) or 0.0
        ok = not (g == 0.0 and g2 == 0.0)
        out.append(_v("gain_reported", ok, "warn" if not ok else "ok",
                      "gain_obs=%s%% gain_act=%s%%(==0 表示未证明提升)" % (g, g2)))

    if "progress_range" in rules:
        n = _num(fields.get("progress"))
        ok = n is None or n == -1.0 or (0.0 <= n <= 1.0)
        out.append(_v("progress_range", ok, "warn" if not ok else "ok", "progress=%s" % n))

    if "name_primary" in rules:
        nm = str(fields.get("name") or "")
        out.append(_v("name_primary", bool(nm), "warn" if not nm else "ok", "name=%r(id 会变)" % nm))

    if "self_describe_match" in rules:
        hz = meta.get("hz")
        pub = fields.get("publish_hz") or []
        if hz is None:
            out.append(_v("self_describe_match", False, "warn", "本帧无实测频率可对账"))
        else:
            out.append(_v("self_describe_match", True, "ok",
                          "自述 %d 项 vs 实测该话题 %.1fHz(逐项对账见 probe)" % (len(pub), hz)))

    if "hz_tol" in rules:      # 频率对设计值的偏差(probe 提供 hz)
        hz, want = meta.get("hz"), meta.get("want_hz")
        if hz is not None and want:
            ok = hz >= want * (1 - TH["hz_tol"])
            out.append(_v("hz_tol", ok, "warn" if not ok else "ok",
                          "实测 %.2fHz vs 设计 %.2fHz(允许 -%.0f%%)" % (hz, want, TH["hz_tol"] * 100)))

    return out


def verdict(rows: List[Dict[str, Any]]) -> str:
    """整帧裁决: veto > warn > ok"""
    if any(r["level"] == "veto" and not r["ok"] for r in rows):
        return "veto"
    if any(r["level"] == "warn" and not r["ok"] for r in rows):
        return "warn"
    return "ok"


def score(rows: List[Dict[str, Any]]) -> float:
    """0..1 质量分(给看板用): 通过率, veto 额外扣分"""
    if not rows:
        return -1.0
    ok = sum(1 for r in rows if r["ok"]) / float(len(rows))
    if verdict(rows) == "veto":
        ok *= 0.5
    return round(ok, 3)
