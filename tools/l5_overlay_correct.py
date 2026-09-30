#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
l5_overlay_correct.py — 让**L5 视觉语言大模型**负责判定「哪里不对、该怎么样」并校正场景叠加
════════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「哪里不对、该怎么样，由 L5 层的视觉语言大模型来负责。」

链路 (全真实, 不出任何真机动作):
  ① 取臂上相机**已叠加**的实帧(带框与标签 ⇒ 模型看到的就是"当前声称")
  ② 把当前框清单(id=origin|label · 像素框 · 类别)一并交给**引擎 L5**(SceneVLM)
  ③ 要它给严格 JSON: keep / fix(id→新框+新label+理由) / delete(id+理由) / missing(漏检)
  ④ 应用: fix+missing → vlm 层; delete → spec["deleted"][cam](按 origin|label 抑制, 与界面删除同口径)
     并**不删**其它层的原始数据(可回退: 每次改前备份 spec, 逐条写审计)
  ⑤ 落台账 reports/l5_overlay_corrections.jsonl (谁改的/为什么/前后框)

判据红线: 只依据图像证据; 不确定 ⇒ keep(不瞎改); 已被操作者删除的 label 不许再给出来。

用法:
  ./gui-venv311/bin/python tools/l5_overlay_correct.py --dry        # 只看模型怎么说, 不改盘
  ./gui-venv311/bin/python tools/l5_overlay_correct.py --apply
  ./gui-venv311/bin/python tools/l5_overlay_correct.py --apply --hint "左边那只横放, 框要贴到槽边"
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))

import scene_overlay as SO                                                        # noqa: E402
import gen_overlay_from_vlm as G                                                  # noqa: E402

SPEC = os.path.join(ROOT, "data", "scene", "overlay_spec.json")
LOG = os.path.join(ROOT, "reports", "l5_overlay_corrections.jsonl")

PROMPT = """你在给机械臂末端相机的**场景叠加**做质量判定与校正。图上已经画出了若干框(可能带标签)。

当前框清单(编号 #n · id | 类别 | 像素框 x1,y1,x2,y2 | 是否有3D框)：
{INVENTORY}

**必须对清单里的每一个 id 都给出一条判定**(ok 或 junk 或 fix)，不许漏、不许只挑几个。

请**只看图上证据**，给出严格 JSON（不要多余文字）：
{{
 "junk": [{{"id":"<清单里的id>","why":"<为什么是错的: 位置/尺寸/类别/对象不存在>"}}],
 "fix":  [{{"id":"<清单里的id>","box":[x1,y1,x2,y2],"label":"<更合适的标签>","why":"<为什么这样改>"}}],
 "missing": [{{"box":[x1,y1,x2,y2],"label":"<漏掉的物体>","why":"<凭什么说它在>"}}],
 "ok": ["<id>", "..."]
}}
规则：
1) 框没贴住物体、明显偏上/偏下/过大过小、标错物体 ⇒ 进 junk 或 fix；
2) **不确定就不要动**（宁可先进 ok）；宁可少给，不要编造看不见的物体；
3) 已被操作者删除的标签不要再出现在 missing 里：{NEGATIVES}；
4) 操作者的现场指示（最高优先级）：{HINT}
"""


def _fetch_annotated(cam: str):
    """优先取**已叠加**的实帧(模型才能看到'当前声称'), 退回原图; 都没有 ⇒ None"""
    import urllib.request
    for name in ("overlay_%s" % cam, cam):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8791/snapshot/%s.jpg" % name, timeout=10) as r:
                b = r.read()
            if b:
                return b, name
        except Exception:
            continue
    return None, None


JUDGEABLE = ("vlm", "meas", "det", "sim")          # 可判: 物体框
PROTECTED = ("trace", "plan", "l5corners")         # 不可判: 轨迹/参考点/规划线/角点(叠加注记, 不是物体)
AUTO_APPLY = ("vlm",)                              # 只有 vlm 层是 L5 自己的地盘 ⇒ 直接改
#   meas(实测3D几何)/sim(画布语义)/det(检测器) ⇒ L5 只能**提案**(记台账给人看), 不可自动删改 ——
#   理由: 2D 视觉模型不该有权抹掉传感器实测的几何(老倪: 「哪里不对由 L5 负责」是**判定**, 不等于
#   让 L5 去删掉别人用真数据量出来的东西)。


def inventory(spec: dict, cam: str) -> list:
    out = []
    for i, b in enumerate(spec["cameras"][cam].get("boxes") or []):
        if str(b.get("origin")) not in JUDGEABLE:
            continue
        bid = "%s|%s" % (b.get("origin"), b.get("label"))
        bb = b.get("box") or b.get("xyxy") or []
        out.append({"n": i, "id": bid, "kind": b.get("kind") or "2d",
                    "box": [round(float(v)) for v in bb[:4]] if bb else None,
                    "has3d": bool(b.get("pts3d"))})
    return out


def ask_l5(cam: str, hint: str, negatives=None) -> dict:
    from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM
    spec = SO.load_spec()
    inv = inventory(spec, cam)
    if not inv:
        return {"ok": False, "why": "叠加里没有框, 无需校正", "verdict": {}}
    raw, which = _fetch_annotated(cam)              # 已叠加的实帧(带框与标签)
    if not raw:
        return {"ok": False, "why": "取不到 %s 帧(8791 无快照), 不猜" % cam, "verdict": {}}
    print("   帧源: /snapshot/%s.jpg (%dB)" % (which, len(raw)))
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="l5corr_")
    os.write(fd, raw)
    os.close(fd)
    p = (PROMPT.replace("{INVENTORY}", json.dumps(inv, ensure_ascii=False, indent=1))
               .replace("{NEGATIVES}", "、".join(sorted(set(negatives or []))) or "无")
               .replace("{HINT}", hint or "无"))
    t0 = time.time()
    if os.environ.get("L5CORR_THINK") == "1":
        os.environ["SS_VLM_THINKING"] = "1"
    try:
        _mt = int(os.environ.get("SS_VLM_MAXTOK_CORR") or
                  ("12000" if os.environ.get("L5CORR_THINK") == "1" else "3000"))
        r = SceneVLM.get().ask(tmp, p, max_tokens=_mt)
        # 2026-09-29: 空内容自动重试一次(更大预算)。现场实测: 带思考时 12000 仍会被 reasoning 吃光,
        # 一轮白等 100~160s 且什么都没判定(环里连续多轮都空)。重试一次的成本远低于"这轮白跑"。
        if r.get("ok") and not (r.get("text") or "").strip():
            _mt2 = max(_mt * 2, 20000)
            print("   ↻ 返回空内容 ⇒ 用 max_tokens=%d 重试一次" % _mt2)
            r = SceneVLM.get().ask(tmp, p, max_tokens=_mt2)
            if (r.get("text") or "").strip():
                _mt = _mt2
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not r.get("ok"):
        return {"ok": False, "why": r.get("why") or "引擎 L5 未返回", "verdict": {}}
    if not (r.get("text") or "").strip():
        return {"ok": False, "verdict": {},
                "why": "引擎返回内容为空 (思考开时 max_tokens 太小会被 reasoning 吃光 ⇒ 已默认 %d)" % _mt}
    v = G.parse_json(r.get("text") or "")
    return {"ok": True, "secs": round(time.time() - t0, 1), "verdict": v,
            "src": r.get("src") or "http", "latency_ms": r.get("latency_ms"),
            "text_head": (r.get("text") or "")[:200], "n_boxes": len(inv)}


def apply_verdict(cam: str, v: dict) -> dict:
    """应用: junk → deleted(按 origin|label 抑制); fix → 覆盖该 id 的框; missing → 追加 vlm 框。"""
    if not v:
        return {"applied": 0}
    shutil.copy2(SPEC, SPEC + ".bak_l5corr_" + time.strftime("%H%M%S"))
    spec = SO.load_spec()
    cam_obj = spec["cameras"][cam]
    dels = set((spec.setdefault("deleted", {})).setdefault(cam, []) or [])
    n_junk = n_fix = n_miss = 0
    def _auto(bid):
        return bid.split("|")[0] in AUTO_APPLY
    junk_ids = {str(x.get("id")) for x in (v.get("junk") or [])
                if x.get("id") and _auto(str(x.get("id")))}
    fix_by_id = {str(x.get("id")): x for x in (v.get("fix") or [])
                 if x.get("id") and _auto(str(x.get("id")))}
    keep, add = [], []
    for b in (cam_obj.get("boxes") or []):
        bid = "%s|%s" % (b.get("origin"), b.get("label"))
        if bid in junk_ids and str(b.get("origin")) not in PROTECTED:
            dels.add(bid); n_junk += 1; continue
        if bid in fix_by_id:
            f = fix_by_id[bid]
            nb = [float(t) for t in (f.get("box") or [])][:4]
            if len(nb) == 4:
                b = dict(b)
                b["box"] = nb
                if f.get("label"):
                    b["label"] = str(f["label"])
                b["corrected_by"] = "l5"
                b["why"] = str(f.get("why"))[:160]
                n_fix += 1
        keep.append(b)
    for m in (v.get("missing") or []):
        nb = [float(t) for t in (m.get("box") or [])][:4]
        if len(nb) != 4:
            continue
        lab = str(m.get("label") or "未命名")
        if ("vlm|%s" % lab) in dels:                      # 操作者删过 ⇒ 不再给
            continue
        add.append({"origin": "vlm", "label": lab, "kind": "2d", "box": nb, "conf": 0.6,
                    "corrected_by": "l5", "why": str(m.get("why"))[:160]})
        n_miss += 1
    cam_obj["boxes"] = keep + add
    spec["deleted"][cam] = sorted(dels)
    SO.save_spec(spec)
    props = [x for x in (v.get("junk") or []) if x.get("id") and not _auto(str(x.get("id")))] + \
            [x for x in (v.get("fix") or []) if x.get("id") and not _auto(str(x.get("id")))]
    return {"applied": n_junk + n_fix + n_miss, "junk": n_junk, "fix": n_fix, "missing": n_miss,
            "proposals": [{"id": str(p.get("id")), "why": str(p.get("why"))[:120]} for p in props][:12],
            "ok_ids": len(v.get("ok") or []), "deleted_now": sorted(dels)[-6:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm")
    ap.add_argument("--hint", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--think", action="store_true", help="打开 L5 思考(慢层, 约 60~160s, 判得更细)")
    ap.add_argument("--apply-last", action="store_true",
                    help="不重新问模型, 直接应用台账里最后一条判定(证据可追, 省一次 100s 调用)")
    a = ap.parse_args()
    if a.think:
        os.environ["L5CORR_THINK"] = "1"

    spec = SO.load_spec()
    negatives = list((spec.get("deleted") or {}).get(a.cam) or [])
    if a.apply_last:
        last = None
        if os.path.isfile(LOG):
            for ln in open(LOG, encoding="utf-8"):
                if ln.strip():
                    last = ln
        if not last:
            print("台账里没有可应用的判定"); return 2
        rec = json.loads(last)
        v = rec.get("verdict") or {}
        print("↩︎ 应用台账最后一条判定 (%s · junk=%d fix=%d missing=%d ok=%d)"
              % (rec.get("ts"), len(v.get("junk") or []), len(v.get("fix") or []),
                 len(v.get("missing") or []), len(v.get("ok") or [])))
        res = apply_verdict(a.cam, v)
        print("   ✅ 已应用: %s" % json.dumps(res, ensure_ascii=False))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%F %T"), "cam": a.cam, "kind": "apply_last",
                                "verdict": v, "applied": res}, ensure_ascii=False) + "\n")
        return 0
    r = ask_l5(a.cam, a.hint, negatives)
    print("🧠 L5 校正判定: ok=%s %ss · src=%s · lat=%sms · 清单 %s 框"
          % (r.get("ok"), r.get("secs"), r.get("src"), r.get("latency_ms"), r.get("n_boxes")))
    if not r.get("ok"):
        print("   %s" % r.get("why")); return 2
    v = r.get("verdict") or {}
    print("   junk=%d fix=%d missing=%d ok=%d" % (len(v.get("junk") or []), len(v.get("fix") or []),
                                                 len(v.get("missing") or []), len(v.get("ok") or [])))
    for k in ("junk", "fix", "missing"):
        for x in (v.get(k) or [])[:6]:
            print("   [%s] %s %s" % (k, x.get("id") or x.get("label"), str(x.get("why"))[:80]))
    if not v:
        print("   模型没给出可解析 JSON, 原文头: %s" % r.get("text_head"))
        return 3
    rec = {"ts": time.strftime("%F %T"), "cam": a.cam, "hint": a.hint, "verdict": v, "secs": r.get("secs")}
    if a.apply:
        res = apply_verdict(a.cam, v)
        rec["applied"] = res
        print("   ✅ 已应用: %s" % json.dumps(res, ensure_ascii=False))
    else:
        print("   (--dry: 未改盘)")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("   台账: %s" % os.path.relpath(LOG, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
