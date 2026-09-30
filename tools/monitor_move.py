#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor_move.py — 只读监控一次真动, 量化"轨迹是否平滑"。

用法: python tools/monitor_move.py <采样秒数> [--speed N]
数据源: ~/zmax_data/rokae_sdk/tcp_out/latest.json (5Hz endInRef, 页面同源)
输出:
  · 三段识别(按 z 单调性自动切: 抬升/横移/下落) + 每段 时长/行程/净Δ/方向
  · 平滑度: ①段内直线度(垂直弦最大偏差/弦长) ②速度均值·峰值·波动 ③加加速度(相邻速度变化)
             ④沿弦回退次数 ⑤姿态角速度(deg/s)均值·峰值·波动
判据口径(现场经验): 直线度 ≤2% 且 回退 0 次 且 速度波动 ≤15% ⇒ 算"丝滑"; 姿态角速度波动 ≤25% ⇒ 转向平顺。
"""
import json, math, os, sys, time

P = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")


def rd():
    try:
        d = json.load(open(P))
        return dict(t=time.time(), p=(d["x"], d["y"], d["z"]), q=(d["qx"], d["qy"], d["qz"], d["qw"]), ts=d["ts"])
    except Exception:
        return None


def qang(a, b):
    d = min(1.0, abs(sum(x * y for x, y in zip(a, b))))
    return math.degrees(2 * math.acos(d))


def seg_stats(S):
    """S = [(t, pos, quat)] → 直线度/速度/回退/角速度"""
    if len(S) < 3:
        return None
    a, b = S[0][1], S[-1][1]
    chord = math.dist(a, b)          # ⚠️ 单位是**米**(真源如此); 门槛 0.5mm 必须写成 0.0005
    if chord < 0.0005:
        return None
    u = [(b[i] - a[i]) / chord for i in range(3)]
    proj, lat, v, av = [], [], [], []
    for i in range(len(S)):
        d = [S[i][1][k] - a[k] for k in range(3)]
        pr = sum(d[k] * u[k] for k in range(3))
        perp = math.sqrt(max(0.0, sum(x * x for x in d) - pr * pr))
        proj.append(pr * 1000.0); lat.append(perp * 1000.0)
        if i:
            dt = max(1e-6, S[i][0] - S[i - 1][0])
            v.append(math.dist(S[i][1], S[i - 1][1]) * 1000.0 / dt)
            av.append(qang(S[i][2], S[i - 1][2]) / dt)
    mv = [x for x in v if x > 0.5]
    back = sum(1 for i in range(1, len(proj)) if proj[i] < proj[i - 1] - 0.3)
    return dict(travel=sum(v[i] * (S[i + 1][0] - S[i][0]) for i in range(len(v))), chord=chord * 1000.0,
                straight=(max(lat) / (chord * 1000.0) * 100.0), vmean=(sum(mv) / len(mv) if mv else 0.0),
                vpeak=(max(v) if v else 0.0), vstd=((sum((x - sum(mv) / len(mv)) ** 2 for x in mv) / len(mv)) ** 0.5 if mv else 0.0),
                jerk=(max(abs(v[i] - v[i - 1]) for i in range(1, len(v))) if len(v) > 1 else 0.0),
                back=back, avmean=(sum([x for x in av if x > 0.5]) / max(1, len([x for x in av if x > 0.5]))),
                avpeak=(max(av) if av else 0.0), dur=S[-1][0] - S[0][0])


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    S, t0 = [], time.time()
    print("👀 只读监控 %.0fs (5Hz 同源真值, 零下发)" % dur)
    f = rd()
    if f:
        print("   起 pos=(%.4f, %.4f, %.4f) quat x=%.6f 帧龄 %.2fs" % (*f["p"], f["q"][0], time.time() - f["ts"]))
    while time.time() - t0 < dur:
        c = rd()
        if c:
            S.append((time.time() - t0, c["p"], c["q"]))
        time.sleep(0.18)
    _dump = os.path.expanduser("~/zmax_data/move_monitor_last.jsonl")
    try:
        with open(_dump, "w", encoding="utf-8") as f:
            for t, p, q in S:
                f.write(json.dumps({"t": t, "p": p, "q": q}) + "\n")
        print("   原始样本已落盘: %s (%d 点)" % (_dump, len(S)))
    except Exception as _e:
        print("   (样本落盘失败: %s)" % _e)
    if len(S) < 3:
        print("   (样本太少)"); return
    _last = rd() or {"ts": time.time()}
    print("   止 pos=(%.4f, %.4f, %.4f) quat x=%.6f · 采样 %d 点 · 真值帧龄 %.2fs" % (*S[-1][1], S[-1][2][0], len(S), time.time() - _last["ts"]))
    # 运动窗口
    mv = [i for i in range(1, len(S)) if math.dist(S[i][1], S[i - 1][1]) * 1000 > 0.15]
    if not mv:
        print("   ⚠️ 全程没检出运动"); return
    i0, i1 = max(0, mv[0] - 2), min(len(S) - 1, mv[-1] + 2)
    W = S[i0:i1 + 1]
    tot = seg_stats(W)
    if not tot:
        print("   ⚠️ 窗口内位移 <0.5mm, 跳过全程统计(样本已落盘, 可事后分析)"); return
    print("   ── 全程 %.1fs · 行程 %.1fmm · 起终点直线 %.1fmm · (全程直线度 %.2f%%/回退 %d —— 多段转移本就非直线, 只作参考) ──"
          % (tot["dur"], tot["travel"], tot["chord"], tot["straight"], tot["back"]))
    print("   速度: 均值 %.1f · 峰值 %.1f · 波动 %.1f%% · 相邻最大跳变 %.1fmm/s" % (tot["vmean"], tot["vpeak"], (tot["vstd"] / tot["vmean"] * 100 if tot["vmean"] else 0), tot["jerk"]))
    print("   姿态: 角速度均值 %.2f°/s · 峰值 %.2f°/s · 总转角 %.2f°" % (tot["avmean"], tot["avpeak"], sum(qang(W[i][2], W[i - 1][2]) for i in range(1, len(W)))))
    # 按 z 变化把运动窗口切成 抬升/平动/下落 段(相邻同类合并; 最短 4 个样本才算一段)
    zs = [s[1][2] for s in W]

    def vtype(i):
        dz = (zs[i] - zs[i - 1]) * 1000.0
        return "抬升" if dz > 0.4 else ("下落" if dz < -0.4 else "平动")

    runs = []
    for i in range(1, len(W)):
        t = vtype(i)
        if runs and runs[-1][0] == t:
            runs[-1][2] = i
        else:
            runs.append([t, i - 1, i])
    segs = [(t, a, b) for (t, a, b) in runs if b - a > 3]
    print("   ── 自动切段 %d 段 ──" % len(segs))
    for k, (nm, a, b) in enumerate(segs, 1):
        st = seg_stats(W[a:b + 1])
        if not st:
            continue
        print("   段%d %s: %.1fs · 行程 %.1fmm · 净 %.1fmm · 直线度 %.2f%% · 速度 %.1f(峰 %.1f, 波动 %.1f%%) · 回退 %d · 角速度 %.2f°/s"
              % (k, nm, st["dur"], st["travel"], st["chord"], st["straight"], st["vmean"], st["vpeak"],
                 (st["vstd"] / st["vmean"] * 100 if st["vmean"] else 0), st["back"], st["avmean"]))


if __name__ == "__main__":
    main()
