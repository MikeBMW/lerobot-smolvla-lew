#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档远程采集数据 (4060 侧 ss_remote_tap 产物) → 可追溯数据包

用途: 把 /home/ubuntu/zmax_ss_remote 里持续追加的感知/建议流, 做成**一致快照 + 清单**,
      数据不进 git (大文件纪律), 但每条都有 sha256 与来源指纹, 可回溯。

用法:
    python3 tools/ss_archive_remote_data.py                 # 默认 src=~/zmax_ss_remote
    python3 tools/ss_archive_remote_data.py --src ... --out ... --note "现场示教前基线"

产出 (默认 ~/zmax_data/ss_remote/<YYYYmmdd_HHMM>/):
    state.jsonl.gz / proposal.jsonl.gz   一致性快照 (坏行/半行被剔除并计数)
    status.json                          采集器自证 (端点/频率/几何状态)
    MANIFEST.md                          来源/条数/时间跨度/频率/几何口径/sha256/git 版本
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(p, limit=None):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snap_jsonl(src, dst):
    """一致性快照: 逐行 JSON 校验, 半行/坏行剔除并计数 (采集器边跑边追加)"""
    ok, bad = [], 0
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                ok.append(json.loads(ln))
            except Exception:
                bad += 1
    with gzip.open(dst, "wt", encoding="utf-8") as g:
        for o in ok:
            g.write(json.dumps(o, ensure_ascii=False) + "\n")
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.expanduser("~/zmax_ss_remote"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.expanduser("~/zmax_data/ss_remote"),
                                time.strftime("%Y%m%d_%H%M"))
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in os.listdir(a.src) if f.endswith(".jsonl"))
    rep = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "note": a.note, "src": a.src, "out": out, "streams": {}}
    for fn in files:
        kind = fn.split("_")[0]
        rows, bad = snap_jsonl(os.path.join(a.src, fn), os.path.join(out, f"{kind}.jsonl.gz"))
        st = {"file": fn, "rows": len(rows), "bad_lines": bad}
        if rows:
            st["t_first"], st["t_last"] = rows[0].get("t"), rows[-1].get("t")
            if st["t_first"] and st["t_last"]:
                st["span_s"] = round(st["t_last"] - st["t_first"], 1)
            # 关键字段可用性 (诚实口径: z7 是否真值)
            keys = ("tcp", "jpos", "jvel", "ft", "gripper", "z7", "input_map", "action")
            st["present"] = {k: sum(1 for r in rows if r.get(k) is not None) for k in keys}
            st["input_maps"] = sorted({r.get("input_map") for r in rows if r.get("input_map")})
        st["sha256_gz"] = sha256(os.path.join(out, f"{kind}.jsonl.gz"))
        rep["streams"][kind] = st
    sp = os.path.join(a.src, "status.json")
    if os.path.exists(sp):
        shutil.copy2(sp, os.path.join(out, "status.json"))
        rep["status"] = json.load(open(sp))
    try:
        rep["git_rev"] = subprocess.check_output(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                                                 text=True).strip()
        rep["git_dirty"] = bool(subprocess.check_output(["git", "-C", REPO, "status", "--porcelain"], text=True).strip())
    except Exception:
        pass
    for t in ("tools/ss_remote_tap.py", "tools/ss_local_infer_server.py", "tools/ss_geom_calib.py"):
        p = os.path.join(REPO, t)
        if os.path.exists(p):
            rep.setdefault("tools_sha256", {})[t] = sha256(p)[:16]
    json.dump(rep, open(os.path.join(out, "archive.json"), "w"), ensure_ascii=False, indent=1)
    # 人读清单
    L = [f"# 远程采集数据归档 — {rep['ts']}", ""]
    if a.note:
        L.append(f"> 备注: {a.note}")
    L.append(f"> 来源: `{a.src}` (4060 侧 Docker 只读订阅 Orin 生产话题; Orin 零程序)")
    L.append(f"> 采集工具: tools/ss_remote_tap.py (本节点零数据发布) · git {rep.get('git_rev')} "
             f"{'(工作区有未提交改动)' if rep.get('git_dirty') else ''}")
    L.append("")
    L.append("| 流 | 条数 | 坏行 | 时间跨度 | sha256(前16) |")
    L.append("|---|---|---|---|---|")
    for k, s in rep["streams"].items():
        L.append(f"| {k} | {s['rows']} | {s['bad_lines']} | {s.get('span_s', '-')}s | {s['sha256_gz'][:16]} |")
    L.append("")
    for k, s in rep["streams"].items():
        if s.get("present"):
            L.append(f"**{k}** 字段非空计数: " + " · ".join(f"{a2}={b}" for a2, b in s["present"].items()))
        if s.get("input_maps"):
            L.append(f"**{k}** input_map 取值: {s['input_maps']}")
    L.append("")
    if rep.get("status"):
        st = rep["status"]
        L.append(f"采集器自证: 样本={st.get('samples')} 收包={st.get('recv')} 自证发布者={st.get('self_publishers')} "
                 f"几何={st.get('geom')}")
    L.append("")
    L.append("⚠️ 诚实口径: z7 为 null 时表示**几何未现场示教**, 推理用的是占位口径 (input_map 逐条记录), "
             "不是真口径 —— 恢复真口径需现场示教 peg_head/goal 两点 (tools/ss_geom_calib.py)。")
    open(os.path.join(out, "MANIFEST.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"\n✅ 归档目录: {out}")

if __name__ == "__main__":
    main()
