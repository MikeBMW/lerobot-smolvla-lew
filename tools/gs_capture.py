#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间数据层 · 3DGS 采集器 (v1)

边动边采: 臂上 D405 的 Orin 高速 JPEG  +  ROKAE TCP 真值位姿  →  逐帧配对落盘。
- 图像**原样存** Orin 压好的 JPEG(不重压, 不丢信息)
- 每帧记"取图前/后的位姿 + 取图耗时的单调时刻", 后处理按时间最近邻配对(墙钟不可靠, NTP 会回拨 ⇒ 一律 monotonic)
- 采集期不动任何在役链路(只读 HTTP + 只读 json)
- 结束落 session_meta.json: 手眼/内参快照 + 帧数 + 覆盖统计 + 提示

用法: gs_capture.py --out ~/zmax_data/gs_scan/<会话名> [--hz 8] [--secs 0]
"""
import argparse, json, os, shutil, sys, time, urllib.request

ARM_URL = "http://192.168.23.66:8792/frame.jpg"
POSE_F = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
HANDEYE_F = os.path.expanduser("~/zmax_data/handeye_state.json")


def _now():
    return time.time(), time.monotonic()


def read_json(path, tries=2):
    for _ in range(tries):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            time.sleep(0.004)
    return None


def fetch(url, timeout=3.0):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            b = r.read()
        return b, time.monotonic() - t0, None
    except Exception as e:
        return None, time.monotonic() - t0, str(e)[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default=ARM_URL)
    ap.add_argument("--hz", type=float, default=8.0)
    ap.add_argument("--secs", type=float, default=0.0, help="0 = 跑到 Ctrl-C / 收到 STOP 文件")
    ap.add_argument("--pose-f", default=POSE_F)
    args = ap.parse_args()

    out = os.path.expanduser(args.out)
    fdir = os.path.join(out, "frames")
    os.makedirs(fdir, exist_ok=True)
    man = open(os.path.join(out, "frames.jsonl"), "a", encoding="utf-8")
    stopf = os.path.join(out, "STOP")
    if os.path.exists(stopf):
        os.remove(stopf)

    he = read_json(HANDEYE_F) or {}
    json.dump({"url": args.url, "hz": args.hz, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
               "handeye": {"T_cam2tool": he.get("T_cam2tool"), "resid_trans_mm_rms": he.get("resid_trans_mm_rms"),
                           "resid_rot_deg_rms": he.get("resid_rot_deg_rms"), "session": he.get("session")}},
              open(os.path.join(out, "session_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    period = 1.0 / max(0.2, args.hz)
    t_start = time.monotonic()
    seq = 0
    n_ok = 0
    n_err = 0
    kb = 0.0
    poses = []
    print("[gs_capture] 起采 → %s (%.1fHz, 源 %s)" % (out, args.hz, args.url), flush=True)
    try:
        while True:
            if args.secs and (time.monotonic() - t_start) >= args.secs:
                break
            if os.path.exists(stopf):
                print("[gs_capture] 收到 STOP 文件, 收工", flush=True)
                break
            t_slot = time.monotonic()
            pb, tb = _now(), None
            pose_before = read_json(args.pose_f)
            tb = time.monotonic()
            img, dt, err = fetch(args.url)
            ta = time.monotonic()
            pose_after = read_json(args.pose_f)
            tc = time.monotonic()
            rec = {"seq": seq, "t_wall": pb, "t_mono_fetch0": tb, "t_mono_fetch1": ta,
                   "fetch_ms": round(dt * 1000, 1),
                   "pose_before": pose_before, "pose_after": pose_after,
                   "pose_t_gap_ms": round((tc - tb) * 1000, 1)}
            if img:
                fn = "frame_%06d.jpg" % seq
                with open(os.path.join(fdir, fn), "wb") as f:
                    f.write(img)
                rec.update({"file": fn, "bytes": len(img)})
                n_ok += 1
                kb += len(img) / 1024.0
            else:
                rec.update({"file": None, "bytes": 0, "err": err})
                n_err += 1
            man.write(json.dumps(rec, ensure_ascii=False) + "\n")
            man.flush()
            for p in (pose_after, pose_before):
                if isinstance(p, dict):
                    poses.append(p)
                    break
            seq += 1
            if seq % 40 == 0:
                el = time.monotonic() - t_start
                print("[gs_capture] %d 帧 · ok=%d err=%d · %.1fs · %.2f帧/s · 均%.0fKB"
                      % (seq, n_ok, n_err, el, n_ok / max(el, 0.1), kb / max(n_ok, 1)), flush=True)
            sl = period - (time.monotonic() - t_slot)
            if sl > 0:
                time.sleep(sl)
    except KeyboardInterrupt:
        print("[gs_capture] Ctrl-C, 收工", flush=True)
    finally:
        man.close()
        try:
            P = []
            for p in poses:
                if isinstance(p, dict) and all(k in p for k in ("x", "y", "z")):
                    P.append([float(p["x"]), float(p["y"]), float(p["z"])])
                else:
                    xyz = p.get("xyz") or p.get("tcp_xyz") or p.get("t") or p.get("pos") if isinstance(p, dict) else None
                    if isinstance(xyz, (list, tuple)) and len(xyz) >= 3:
                        P.append([float(v) for v in xyz[:3]])
            meta = {"frames": seq, "ok": n_ok, "err": n_err,
                    "elapsed_s": round(time.monotonic() - t_start, 1),
                    "avg_kb": round(kb / max(n_ok, 1), 1), "ended": time.strftime("%Y-%m-%d %H:%M:%S")}
            if P:
                import statistics as st
                for i, nm in enumerate("xyz"):
                    v = [q[i] for q in P]
                    meta["pose_%s" % nm] = [round(min(v), 4), round(max(v), 4), round(st.median(v), 4)]
                    meta["pose_%s_range_mm" % nm] = round((max(v) - min(v)) * 1000, 1)
                meta["pose_samples"] = len(P)
            json.dump(meta, open(os.path.join(out, "capture_summary.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("[gs_capture] 结束: %s" % json.dumps(meta, ensure_ascii=False), flush=True)
        except Exception as e:
            print("[gs_capture] 汇总失败(不影响数据): %s" % e, flush=True)


if __name__ == "__main__":
    main()
