#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_l2_point.py — 记录当前真机 TCP 位姿为 L2 示教点位 (只读订阅, 不下发任何运动)

用法(原 CLI 兼容):
  python3 tools/record_l2_point.py <点位名> ["说明"]
  python3 tools/record_l2_point.py --name slot4 --desc "4号位" --samples 6 [--dry] [--json]

链路: 本机 Docker tap 容器 (ss-remote-tap, ROS_DOMAIN_ID=0) → /robot/tcp_pose 只读订阅
纪律:
  · 连续采样 ≥6 帧算均值 + 极差; **极差过大(机械臂还在动) → 拒绝记录**, 绝不写坏点位;
  · 写前自动备份到 /tmp/taught_points.pre_<name>_<时间>.json;
  · 一律写 4 分量四元数(2026-09-30 教训: 缺 w 的 quat 会让执行器 plan_stage 抛 IndexError);
  · ``--dry`` 只采样+打印不落盘; ``--json`` 末行输出一份机器可读结果(给页面/接口用)。

2026-09-30 老倪: 「4 5 6 号位, 你能自己实现记录么？」—— 记录本身零运动, 所以可以做成
页面按钮(8793 /ctl/record_point → 本脚本), 现场点动到位后一键记住; 但"臂要站在那个
物理位置上"仍需现场(或由几何外推候选 + 人眼确认)。
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 📍号位库(默认) / 🧭空间点库(老倪 2026-10-01「空间1~空间7 独立记录」) —— 两库分开, 互不影响
OUT_TAUGHT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
OUT_SPACE = os.path.join(REPO, "data", "skills", "l2_atomic", "space_points.json")
OUT = OUT_TAUGHT                 # main() 按 --store 覆盖


def _store_path(store):
    return OUT_SPACE if str(store or "").strip().lower() == "space" else OUT_TAUGHT
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
# ⚡ 本地真值文件(rokae_tcp_sampler 写; 与 /robot/tcp_pose 同源, 5Hz)
_TCP_DIR = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out")
TCP_JSONL = os.path.join(_TCP_DIR, "tcp_direct_%s.jsonl" % time.strftime("%Y%m%d"))
TCP_LATEST = os.path.join(_TCP_DIR, "latest.json")
NUM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")


def sample(n=6, timeout=8):
    """只读采样 /robot/tcp_pose 的 pose (position xyz + orientation xyzw)"""
    rows = []
    for _ in range(n):
        cmd = ("source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
               "timeout 4 ros2 topic echo --once /robot/tcp_pose --field pose")
        r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=timeout + 8)
        vals = [float(x) for x in NUM.findall(r.stdout)]
        if len(vals) >= 7:
            rows.append(vals[:7])
        time.sleep(0.5)
    return rows


def sample_fast(n=6, span_s=1.0):
    """⚡ 本地直读真值文件采样(老倪 2026-10-01: 「局域网, 点完 500ms 内要有反应」)。

    与执行器**同源**: rokae_tcp_sampler 订阅 /robot/tcp_pose 后写盘到
    ~/zmax_data/rokae_sdk/tcp_out/tcp_direct_<日期>.jsonl(5Hz) + latest.json。
    这里**不建任何连接**(旧路是 SSH 到 Orin 跑 6 次 `ros2 topic echo`, 一次 1~2s ⇒ 十几秒),
    直接读 jsonl 末尾 ~span_s 秒的帧算均值/极差 ⇒ 整个记录 <100ms。

    守据(不满足就抛异常 ⇒ 上层退回 SSH 慢路, 绝不猜):
      · 最新帧龄 >2s          ⇒ 采样器卡死/容器陈旧, 不用;
      · xyzw 全 0 或 pos≈0    ⇒ 会话陈旧坏值(历史踩过), 不用;
      · 窗口内帧数 <4         ⇒ 数据不足, 不用。
    """
    rows = []
    try:
        with open(TCP_JSONL, "rb") as f:
            f.seek(0, os.SEEK_END)
            _sz = f.tell()
            f.seek(max(0, _sz - 65536))
            _buf = f.read().decode("utf-8", "ignore")
        for _ln in reversed([x for x in _buf.splitlines() if x.strip().startswith("{")]):
            try:
                d = json.loads(_ln)
            except Exception:                                                 # noqa: BLE001
                continue
            _p = [float(d.get(k)) for k in ("x", "y", "z", "qx", "qy", "qz", "qw")]
            if all(abs(v) < 1e-9 for v in _p):
                continue                       # 全 0 = 坏值, 跳过
            rows.append((float(d.get("ts") or 0), _p))
            if len(rows) >= 60:
                break
    except Exception as _e:                                                   # noqa: BLE001
        raise RuntimeError("本地真值文件不可读: %s" % str(_e)[:80])
    if not rows:
        raise RuntimeError("本地真值文件没有可用帧(全 0 或空)")
    rows.sort(key=lambda x: x[0])
    _t_last = rows[-1][0]
    _age = time.time() - _t_last
    if _age > 2.0:
        raise RuntimeError("真值文件陈旧(最新帧 %.1fs 前) ⇒ 采样器可能卡死" % _age)
    _win = [p for (t, p) in rows if _t_last - t <= max(0.2, float(span_s))]
    if len(_win) < 4:
        raise RuntimeError("本地窗口帧数不足(%d <4)" % len(_win))
    return _win[:n] if n and len(_win) >= n else _win


def parse_args(argv):
    name, desc, samples, dry, js, store = None, "", 6, False, False, "taught"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--dry",):
            dry = True
        elif a in ("--json",):
            js = True
        elif a in ("--name", "-n"):
            i += 1
            name = argv[i]
        elif a in ("--desc", "-d"):
            i += 1
            desc = argv[i]
        elif a in ("--samples", "-s"):
            i += 1
            samples = max(4, int(argv[i]))
        elif a in ("--store",):
            i += 1
            store = argv[i].strip().lower()
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif not a.startswith("-"):
            if name is None:
                name = a
            elif not desc:
                desc = a
        i += 1
    return name, desc, samples, dry, js, store


def main():
    global OUT
    name, desc, samples, dry, js, store = parse_args(sys.argv[1:])
    OUT = _store_path(store)                       # 🧭 space1..7 落 space_points.json, 不碰号位库
    if not name:
        print("用法: python3 tools/record_l2_point.py <点位名> [说明]")
        return 2
    _t0 = time.time()
    try:                                    # ⚡ 先走本地直读(毫秒级); 守据不满足才退回 SSH 慢路
        rows = sample_fast(samples, 1.0)
        _src = "本地真值文件直读(rokae_sdk/tcp_out, 与 /robot/tcp_pose 同源)"
    except Exception as _e:                                                   # noqa: BLE001
        print("⚡ 快路不可用(%s) ⇒ 退回 SSH 慢路(约 4~15s)" % str(_e)[:90])
        rows = sample(samples)
        _src = "/robot/tcp_pose (只读订阅, Docker tap)"
    _ms = int((time.time() - _t0) * 1000)
    if len(rows) < 4:
        out = {"ok": False, "name": name, "msg": "采样不足 (%d 帧) —— 检查 tap 容器/tcp_pose 话题" % len(rows),
               "n_samples": len(rows)}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    cols = list(zip(*rows))
    mean = [sum(c) / len(c) for c in cols]
    spread = [max(c) - min(c) for c in cols]
    pos_max, quat_max = max(spread[:3]), max(spread[3:])
    print("⚡ 采样 %d 帧 / 耗时 %d ms / 源: %s" % (len(rows), _ms, _src))
    print("采样 %d 帧: pos=(%.7f, %.7f, %.7f) m · quat(xyzw)=(%.7f, %.7f, %.7f, %.7f)"
          % (len(rows), mean[0], mean[1], mean[2], mean[3], mean[4], mean[5], mean[6]))
    print("极差: pos %.2e m · quat %.2e  (静止判据: pos 极差 ≤1e-4 m)" % (pos_max, quat_max))
    if pos_max > 1e-4:
        out = {"ok": False, "name": name, "n_samples": len(rows), "spread_pos_m": round(pos_max, 8),
               "msg": "机械臂还在动 (极差 %.2e m > 1e-4) → 拒绝记录, 让现场停稳再录" % pos_max}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    quat = [round(v, 7) for v in mean[3:7]]
    try:                                        # 单位约束自检: 缺分量/坏四元数绝不入库
        n2 = sum(v * v for v in quat)
        if abs(n2 - 1.0) > 1e-4 or len(quat) != 4:
            raise ValueError("|q|^2=%.6f" % n2)
    except Exception as e:                                                    # noqa: BLE001
        out = {"ok": False, "name": name, "msg": "四元数不自洽(%s) → 拒绝记录" % e}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    try:
        store = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        store = {"version": "v1",
                 "note": ("L2 示教绝对点位 (按真机 /robot/tcp_pose 实测记录, 供 line_abs 回点)"
                          if OUT == OUT_TAUGHT else
                          "空间点 1~7 (老倪 2026-10-01: 与号位独立的 7 个空间点; 按真机 /robot/tcp_pose 实测记录)"),
                 "frame": "base_link", "points": {}}
    had = name in (store.get("points") or {})
    entry = {
        "pos": [round(v, 7) for v in mean[:3]],
        "quat": quat,
        "desc": desc or ("%s — 2026-09-30 现场记录" % name),
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": _src,
        "n_samples": len(rows),
        "spread_pos_m": round(pos_max, 8),
        "spread_quat": round(quat_max, 8),
    }
    if not dry:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        if os.path.exists(OUT):
            bak = "/tmp/%s.pre_%s_%s.json" % (os.path.basename(OUT), name, time.strftime("%m%d_%H%M%S"))
            shutil.copy(OUT, bak)
            print("备份: %s" % bak)
        store.setdefault("points", {})[name] = entry
        store["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        print("✅ 已记录点位 %s → %s" % (name, OUT))
    else:
        print("(--dry: 未落盘)")
    out = {"ok": True, "name": name, "written": (not dry), "overwrote": bool(had),
           "elapsed_ms": _ms, "source": _src, "samples_window_s": 1.0,
           "pos": entry["pos"], "quat": entry["quat"], "n_samples": len(rows),
           "spread_pos_m": entry["spread_pos_m"], "spread_quat": entry["spread_quat"],
           "recorded_at": entry["recorded_at"],
           "msg": ("%s已记录 %s" % ("覆盖" if had else "", name)) if not dry else ("%s 演练: 未落盘" % name)}
    if js:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(json.dumps(entry, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
