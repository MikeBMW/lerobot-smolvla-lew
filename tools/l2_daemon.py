#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_daemon.py — L2 原子技能常驻执行器 (立即动作, 不再每条指令重连)

架构: 两条常驻 ssh 通道
  A) 命令通道: bash 循环读 stdin -> 直接 eval ROS2 服务调用 (环境只 source 一次)
  B) 状态通道: 循环读 /robot/tcp_pose -> 维护当前位姿缓存 (供相对技能算目标)
接口: FIFO ~/zmax_data/l2_cmd.fifo  (一行一条 JSON: {"skill":"L2.lift","d_mm":100})
"""
import json, os, re, subprocess, sys, threading, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "tashan@192.168.23.66"
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
# 原子技能注册表路径 (v5.11.1 热加载引入 REG_PATH, 当时漏了这行定义 -> NameError 起不来)
REG_PATH = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")

_pose = {"p": None, "q": None, "t": 0.0}

# 直读真值 (与 tools/record_l2_point.py 同一口径): 容器 + 数值解析
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
NUM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")
USE_DIRECT_POSE = True   # 关键判定优先直读话题; 自检里置 False 走缓存(保证离线可测)


def _pose_direct(timeout=10):
    """直读 /robot/tcp_pose (经本机 Docker tap 容器, 只读, 不下发任何指令)。

    2026-09-20 现场教训: 常驻状态流的缓存**会滞后**(实测整分钟级) → 算出的 Δ 是旧值、
    到位被误判("未到位"中止, 而臂其实正在走到位)。所以守卫的 Δ 与"等到位"一律直读话题,
    常驻缓存只当兜底 —— 这也是 memory 里那条"中转 state 流是缓存旧值须直读 topic"的代码化。
    """
    try:
        r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc",
                            "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                            "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"],
                           capture_output=True, text=True, timeout=timeout)
    except Exception as e:                                                   # noqa: BLE001
        log("直读位姿失败: %s" % e)
        return None
    vals = [float(x) for x in NUM.findall(r.stdout)]
    return vals[:7] if len(vals) >= 7 else None


def _pose_best():
    """返回 (pos, quat, 来源)。优先直读话题(direct); 读不到退回常驻流缓存(cache, 新鲜窗口 5s); 都没有 none。"""
    if USE_DIRECT_POSE:
        v = _pose_direct()
        if v:
            return v[:3], v[3:7], "direct"
    if _pose["p"] and (time.time() - _pose["t"]) < 5.0:
        return _pose["p"], _pose["q"], "cache"
    return None, None, "none"


_reg_mtime = [0.0]


def maybe_reload(reg):
    """注册表一变就重读 —— L2 技能热更新 (VL 指挥升级后立即生效, 无需重启)"""
    try:
        m = os.path.getmtime(REG_PATH)
    except OSError:
        return reg
    if m != _reg_mtime[0]:
        try:
            reg2 = json.load(open(REG_PATH, encoding="utf-8"))
            _reg_mtime[0] = m
            log("注册表热加载: %d 个原子技能" % len(reg2.get("skills", [])))
            return reg2
        except Exception as e:
            log("注册表热加载失败(继续用旧): %s" % e)
    return reg

def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def state_thread():
    cmd = PRE + "while true; do ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null; sleep 0.5; done"
    p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HOST, cmd], stdout=subprocess.PIPE, text=True, bufsize=1)
    buf = []
    for ln in p.stdout:
        s = ln.strip()
        if s.startswith("---"):
            continue
        if ":" in s:
            try:
                buf.append(float(s.split(":", 1)[1]))
            except ValueError:
                continue
        if len(buf) >= 7:
            _pose["p"] = buf[:3]
            _pose["q"] = buf[3:7]
            _pose["t"] = time.time()
            buf = []


def build_move(sk, spec, pts):
    p, q = _pose["p"], _pose["q"]
    if not p or not q:
        return None
    t = list(p)
    if sk["ros"] == "line_rel":
        d = float(spec.get("d_mm", sk["param"]["d_mm"].get("default", 50))) / 1000.0
        a = sk["axis"]
        if a == "z_pos":
            t[2] = p[2] + abs(d)
        elif a == "z_neg":
            t[2] = p[2] - abs(d)
        elif a == "x":
            t[0] = p[0] + d
        elif a == "y":
            t[1] = p[1] + d
    elif sk["ros"] == "line_abs":
        # 🛡 2026-09-20 事故修复: 技能可用 point_locked 把目标点锁死在技能定义里 —
        #   收到 spec.point 一律忽略(防 GUI/调用方误送别的点), 并记一条告警。
        #   未锁的技能仍兼容旧的 spec.point / param.point.default 取值链(空 param 也不再 KeyError)。
        _pm = (sk.get("param") or {}).get("point") or {}
        if sk.get("point_locked") and sk.get("point"):
            name = sk["point"]
            if spec.get("point") and spec.get("point") != name:
                log("⚠️ %s 点位已锁定=%s, 忽略收到的 point=%s" % (sk.get("id"), name, spec.get("point")))
        else:
            name = spec.get("point") or _pm.get("default") or sk.get("point") or "home"
        if name not in pts:
            log("拒绝: 点位 %s 不在点位库" % name)
            return None
        t = list(pts[name]["pos"])
        # 2026-09-20 老倪: "回到能看清光模块的位姿" = 位置+姿态都要回到示教点。
        # 默认沿用旧行为(位置用示教点 · 姿态保持当前), 技能上标 "quat":"taught" 才恢复示教姿态
        # —— 不改既有 goto_point/home 的行为(避免给老技能加姿态旋转风险)。
        if str(sk.get("quat", "")).lower() == "taught" and pts[name].get("quat"):
            q = list(pts[name]["quat"])
    return (t, q)


# ── 多阶段技能 (2026-09-20 老倪【一号位】需求: 阶段1 到槽位正上方 → 阶段2 下降到槽位, 全程不松爪) ──
#   设计口径: 每阶段"下发后必须用真值等到位"才允许进下一阶段(判完成只看真值);
#   阶段之间不碰夹爪 —— "全程不松爪"由技能定义里没有 gripper 步骤来保证(执行层不自己发明动作)。
def _load_points():
    """点位库: 演示学习轨迹点 + L2 传授点库 (同名以传授点库为准)"""
    pts = {}
    for _pf in ("data/skills/l2_muscle/光模块_抓放_演示学习_v1.json",
                "data/skills/l2_atomic/taught_points.json"):
        try:
            with open(os.path.join(REPO, _pf), encoding="utf-8") as _f:
                pts.update(json.load(_f).get("points", {}))
        except Exception as _e:                                              # noqa: BLE001
            log("点位库 %s 读取失败(跳过): %s" % (_pf, _e))
    return pts


def _point_name(sk, st, spec):
    """点位名取值链: 技能级锁点(优先且忽略误送) > 阶段 to > spec.point > param.point.default > 技能 point > home"""
    if sk.get("point_locked") and sk.get("point"):
        if spec.get("point") and spec.get("point") != sk["point"]:
            log("⚠️ %s 点位已锁定=%s, 忽略收到的 point=%s" % (sk.get("id"), sk["point"], spec.get("point")))
        return sk["point"]
    _pm = (sk.get("param") or {}).get("point") or {}
    return st.get("to") or spec.get("point") or _pm.get("default") or sk.get("point") or "home"


def plan_stage(sk, st, pts, spec, cur):
    """算单阶段 目标/Δ/方向/下发字节; 守卫不过 → 返回 {"err":...} (调用方一律不下发)"""
    name = _point_name(sk, st, spec)
    if name not in pts:
        return {"err": "点位 %s 不在点位库" % name}
    t = [float(v) for v in pts[name]["pos"]]
    t[2] += float(st.get("dz_mm", 0.0)) / 1000.0          # base 系竖直偏移(mm): 正=上, 负=下
    if str(st.get("quat", sk.get("quat", ""))).lower() == "taught" and pts[name].get("quat"):
        q = [float(v) for v in pts[name]["quat"]]         # 显式回示教姿态 → 纯平移, 不带旋转
    else:
        q = list(_pose["q"]) if _pose["q"] else None
    if not q:
        return {"err": "位姿缓存未就绪(当前姿态缺)"}
    dx, dy, dz = [(t[i] - cur[i]) * 1000.0 for i in range(3)]
    _dir = "↑上升" if dz > 0.5 else ("↓下降" if dz < -0.5 else "→平动")
    lin = (dx * dx + dy * dy + dz * dz) ** 0.5
    g = dict(sk.get("guard") or {})
    g.update(st.get("guard") or {})                        # 阶段级守卫覆盖技能级
    gd = g.get("dz_down_limit_mm")
    if gd is not None and dz < -abs(float(gd)):
        if spec.get("allow_down_mm") is None or float(spec.get("allow_down_mm")) < abs(dz):
            return {"err": "向下 %.1fmm > 守卫 %.0fmm (确需下降请带 allow_down_mm)" % (-dz, float(gd)),
                    "pos": t, "dz": dz}
    # 🛡 z_floor 硬红线 (2026-09-20 现场修正): 目标 z **不得低于参考点位 z**(+偏移)。
    #   前情: 老倪把臂抬到槽位上方 185mm 后点「一号位」被"向下>40mm"守卫误拦 —— 真正该守的是
    #   "绝不下压到槽位点以下"(攻进夹具), 而不是"相对当前位姿下降多少"(转移段本来就该允许大下降)。
    #   这条与 Δ 无关, 与调用方传什么参数无关, 编造不了。
    zf = g.get("z_floor_point")
    if zf:
        if zf not in pts:
            return {"err": "z_floor 参考点 %s 不在点位库" % zf, "pos": t}
        _off = float(g.get("z_floor_offset_mm", 0.0))
        floor = pts[zf]["pos"][2] + _off / 1000.0
        if t[2] < floor - 1e-6:
            _bel = (floor - t[2]) * 1000.0
            _al = spec.get("allow_below_mm")
            if _al is None or float(_al) < _bel:
                return {"err": "目标 z=%.4f 低于下限 %s%+.0fmm=%.4f (低了 %.1fmm; 确需下压请带 allow_below_mm)"
                        % (t[2], zf, _off, floor, _bel), "pos": t, "dz": dz}
            log("⚠️ z_floor 被 allow_below_mm=%.1f 显式放行: 目标低于槽位点 %.1fmm" % (float(_al), _bel))
    ml = g.get("max_lin_mm")
    if ml is not None and lin > float(ml):
        return {"err": "直线距离 %.0fmm > 守卫 %.0fmm (请人工把臂移到槽位附近再跑)" % (lin, float(ml)),
                "pos": t, "lin": lin}
    sp = float(spec.get("speed", 60))
    if sk.get("speed_max") is not None:                    # 技能级限速上限(练习用低速, 收口在执行层)
        sp = min(sp, float(sk["speed_max"]))
    call = ('ros2 service call /move_line interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
            % (sp, t[0], t[1], t[2], q[0], q[1], q[2], q[3]))
    return {"name": name, "pos": t, "quat": q, "dx": dx, "dy": dy, "dz": dz,
            "dir": _dir, "lin": lin, "call": call, "speed": sp}


def wait_arrive(target, tol_mm=2.0, timeout_s=30.0):
    """等到位: **只看真值**(直读 /robot/tcp_pose; 读不到才退常驻缓存), 连续两次落进容差算停稳。
    返回 (ok, 最近偏差mm, 位姿来源)。绝不用 success / 计时来判完成 —— 老倪: 判完成只看真值。"""
    t0, best, src = time.time(), None, "none"
    while time.time() - t0 < timeout_s:
        p, _q, src = _pose_best()
        if p:
            e = max(abs(p[i] - target[i]) * 1000.0 for i in range(3))
            best = e if best is None else min(best, e)
            if e <= tol_mm:
                time.sleep(0.5)
                p2, _q2, src2 = _pose_best()
                if p2:
                    e2 = max(abs(p2[i] - target[i]) * 1000.0 for i in range(3))
                    if e2 <= tol_mm:
                        return True, e2, src2
        time.sleep(0.5)
    return False, best, src


def _stage_timeout(st, lin_mm, speed):
    """等一阶段的**时间上限** —— 按距离和速度估, 不写死。
    前情 (2026-09-20 21:09 现场): 阶段1 直线 448mm, 超时写死 60s → 60s 时臂还在半路(差 196.6mm)
    被判"未到位"而中止; 但指令已发不会撤回, 臂自己走完停在正上方 → **误判成机械臂没回到位**。
    实测口径: rt_speed_ratio=0.05、speed=30 时约 2.8mm/s (155mm 走 56s) ⇒ 约 0.093 mm/s 每单位 speed。
    st.timeout_dynamic=false 时按 timeout_s 硬值(自检用)。
    """
    base = float(st.get("timeout_s", 40.0))
    if not st.get("timeout_dynamic", True):
        return base
    eff = max(0.093 * float(speed or 30), 0.4)            # mm/s 估算
    return max(base, round(15.0 + lin_mm / eff * 1.6, 1))


def run_stages(sk, spec, chan, pts):
    """多阶段技能: 逐阶段 ①算目标 ②守卫 ③下发 ④等真值到位 ⑤再进下一阶段。
    任一阶段被守卫拒/未到位 → 中止剩余阶段并**绝不重发**(30s 超时那次的教训)。"""
    steps = sk.get("steps") or []
    n = len(steps)
    cur, _cq, csrc = _pose_best()
    if not cur:
        log("拒绝: 位姿读不到(直读失败且常驻缓存过期)")
        return "位姿缓存未就绪"
    log("当前位姿(来源 %s): (%.4f, %.4f, %.4f)" % (csrc, cur[0], cur[1], cur[2]))
    plans, c = [], list(cur)
    for i, st in enumerate(steps, 1):
        pl = plan_stage(sk, st, pts, spec, c)
        if pl.get("err"):
            log("🛡 阶段 %d/%d 拒绝: %s" % (i, n, pl["err"]))
            return "阶段 %d 拒绝: %s" % (i, pl["err"])
        plans.append(pl)
        c = pl["pos"]
        log("阶段 %d/%d「%s」点=%s pos=(%.4f, %.4f, %.4f) · 预计Δ=(%+.1f, %+.1f, %+.1f)mm %s · 直线 %.0fmm · speed %s · 等待上限 %.0fs"
            % (i, n, st.get("note", ""), pl["name"], pl["pos"][0], pl["pos"][1], pl["pos"][2],
               pl["dx"], pl["dy"], pl["dz"], pl["dir"], pl["lin"], pl["speed"],
               _stage_timeout(st, pl["lin"], pl["speed"])))
    if spec.get("dry"):
        for i, pl in enumerate(plans, 1):
            log("DRY-RUN 阶段 %d/%d 将下发: %s" % (i, n, pl["call"][:220]))
        return "DRY-RUN(未下发) %d 阶段: %s" % (
            n, " | ".join("阶段%d Δ=(%+.1f,%+.1f,%+.1f)mm%s" % (i, p["dx"], p["dy"], p["dz"], p["dir"])
                          for i, p in enumerate(plans, 1)))
    for i, st in enumerate(steps, 1):
        pl = plans[i - 1]
        live, _lq, lsrc = _pose_best()                     # 下发前用**实时直读位姿**复算 Δ + 复检守卫
        if live:
            pl2 = plan_stage(sk, st, pts, spec, live)
            if pl2.get("err"):
                log("🛡 下发前复检拒绝 阶段 %d/%d: %s" % (i, n, pl2["err"]))
                return "🛡 阶段 %d 被守卫拒绝" % i
            pl = pl2
        _to = _stage_timeout(st, pl["lin"], pl.get("speed", spec.get("speed", 60)))
        chan.stdin.write(pl["call"] + "\n")
        chan.stdin.flush()
        log("已下发 阶段 %d/%d %s → %s · Δ=(%+.1f, %+.1f, %+.1f)mm %s · 直线 %.0fmm · 等到位上限 %.0fs"
            % (i, n, st.get("note", ""), pl["name"], pl["dx"], pl["dy"], pl["dz"], pl["dir"], pl["lin"], _to))
        ok, err, psrc = wait_arrive(pl["pos"], float(st.get("tol_mm", 2.0)), _to)
        if not ok:
            log("🛑 阶段 %d/%d 未在 %.0fs 内到位(最近偏差 %s mm, 位姿来源 %s) → 中止剩余阶段, 绝不重发; "
                "⚠️ 已下发的指令不会撤回, 臂可能仍在走 —— 以真值判定, 别重复点"
                % (i, n, _to, ("%.1f" % err) if err is not None else "无真值", psrc))
            return "🛑 阶段 %d 未到位, 已中止(见日志)" % i
        log("✅ 阶段 %d/%d 到位 · 真值偏差 %.1fmm (来源 %s) · 夹爪未动"
            % (i, n, err if err is not None else -1.0, psrc))
        time.sleep(float(st.get("dwell_s", 1.0)))
    return "✅ 全部 %d 阶段完成" % n


IMG_LAST = os.path.expanduser("~/zmax_data/aoi_last_frame.png")


def _image_health(raw):
    """图像健康度: 尺寸/均值/对比度/最大灰阶 → 判定 (全黑/偏暗/正常)

    为什么必须量化: 2026-09-20 现场"图片框黑屏" —— 文件 2.2MB 看着像真图(纯噪声不可压缩),
    实际全图 15M 像素 mean=3.35/255 max=5 (只有读出噪声底) = 相机在拍但进光≈0。
    光看文件大小会误判, 必须看像素统计。
    """
    try:
        import io
        import numpy as np
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            a = np.asarray(im).astype(np.float32)
            w, h = im.size
        mean, std, mx = float(a.mean()), float(a.std()), float(a.max())
        if mx <= 12 and mean < 8:
            v = "⚠️全黑(相机在拍但进光≈0) — 查光源/镜头盖/曝光(EXPOSURE_US)"
        elif mean < 25:
            v = "⚠️偏暗(进光不足)"
        else:
            v = "✅正常"
        return "%dx%d mean=%.2f std=%.2f max=%.0f → %s" % (w, h, mean, std, mx, v)
    except Exception as e:                                                    # noqa: BLE001
        return "解析失败(%s)" % e


def _pic_meta(url):
    """取该图源元数据 (?meta=1): 文件名 + 拍摄时间 → 给出"帧龄"(新鲜度)

    老倪铁律: 面板禁假值 / 画面要带状态 —— 一张图必须能说出"它是什么时候拍的"。
    """
    try:
        import urllib.parse
        u = url.split("?")[0] + "?meta=1"
        with urllib.request.urlopen(u, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        age = max(0.0, time.time() - float(d.get("t", 0) or 0))
        return "拍摄 %s · 帧龄 %.0fs · 工控机文件 %s" % (
            time.strftime("%H:%M:%S", time.localtime(d.get("t", 0) or 0)), age,
            d.get("file", "?"))
    except Exception as e:                                                      # noqa: BLE001
        return "元数据取不到(%s)" % type(e).__name__


def _accept_image(raw, url, code, dt):
    """图像类 HTTP 返回: 落盘 + 健康度判定(全黑/偏暗/正常) + 帧龄 + 日志/回执

    2026-09-20 现场"图片框黑屏"教训: 文件 2.2MB 看着像真图(纯噪声不可压缩), 实际全图
    mean=3.35/255 max=5 (只有读出噪声底), 必须看像素统计才知道相机是不是真看到东西。
    """
    kb = len(raw) / 1024.0
    try:
        with open(IMG_LAST, "wb") as f:
            f.write(raw)
    except Exception:                                                          # noqa: BLE001
        pass
    h = _image_health(raw)
    msg = "HTTP %s → %s (%.0fms) 图像 %.0fKB · %s · %s · 已存 %s" % (
        url, code, dt, kb, h, _pic_meta(url), IMG_LAST)
    log(msg)
    return msg


def dispatch(reg, spec, chan):
    sid = spec.get("skill", "")
    dx = dy = dz = 0.0                  # 运动类分支会覆写; 夹爪/http 分支保持 0
    _dir = "→平动"
    sk = {s["id"]: s for s in reg["skills"]}.get(sid)
    if not sk:
        log("拒绝: 未知技能 %s" % sid)
        return "未知技能: %s" % sid
    if sk.get("ros") == "http":
        url = sk.get("url", "")
        # 2026-09-20: 支持 query 后缀 (如 ?grab=1 每次重新拍一帧 / ?meta=1 取元数据)
        _q = sk.get("query") or ""
        if _q and "?" not in url:
            url = url + _q
        method = sk.get("method", "POST")
        try:
            req = urllib.request.Request(url, data=(b"" if method == "POST" else None), method=method)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                code = r.status
                ctype = r.headers.get("Content-Type", "")
            dt = (time.time() - t0) * 1000
            # 🖼 二进制图像: 不往日志里倒字节(原实现 decode(utf-8,'ignore') 会把 PNG 乱码灌进日志),
            #   改存盘 + 输出图像健康度判定(全黑/偏暗/正常) —— 老倪 2026-09-20 黑屏排查沉淀
            if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:2] == b"\xff\xd8" or "image" in ctype.lower():
                return _accept_image(raw, url, code, dt)
            body = raw.decode("utf-8", "ignore")
            log("HTTP %s → %s (%.0fms) %s" % (url, code, dt, body[:400]))
            return "HTTP %s → %s (%.0fms) 返回: %s" % (url, code, dt, body[:300].replace("\n", " "))
        except Exception as e:
            log("HTTP 失败 %s: %s" % (url, e))
            return "HTTP 失败: %s" % e
    if sk["ros"] == "gripper":
        if "close" in sid:
            fo = float(spec.get("force", sk["param"]["force"].get("default", 40)))
            call = ('ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 0.0, '
                    'target_speed: -1.0, target_force: %s, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"' % fo)
        else:
            call = ('ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 1000.0, '
                    'target_speed: -1.0, target_force: -1.0, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"')
    else:
        # 点位来源: ①演示学习轨迹点 ②L2 传授点库 taught_points.json (2026-09-20 起,
        #   供"进入金手指AOI检测区"这类按现场示教的绝对点回点; 同名以传授点库为准)
        pts = _load_points()
        # 🅰 2026-09-20【一号位】: 技能带 steps → 多阶段执行(逐阶段下发 + 真值等到位再进下一阶段)
        if sk.get("steps"):
            return run_stages(sk, spec, chan, pts)
        r = build_move(sk, spec, pts)
        if not r:
            log("拒绝: 位姿缓存未就绪或点位不存在")
            return "位姿缓存未就绪"
        (x, y, z), (qx, qy, qz, qw) = r[0], r[1]
        # 🛡 2026-09-20 事故修复 (老倪按下急停那次): 下发前一律算 Δ 并做方向守卫 ——
        #   架构原则"执行由最下层收口": 上层点错点/送错参数, 底层必须能看见 Δ 并有权拒发。
        _cur = _pose["p"] or [0.0, 0.0, 0.0]
        dx, dy, dz = (x - _cur[0]) * 1000.0, (y - _cur[1]) * 1000.0, (z - _cur[2]) * 1000.0
        _dir = "↑上升" if dz > 0.5 else ("↓下降" if dz < -0.5 else "→平动")
        log("目标 %s: pos=(%.4f, %.4f, %.4f) · Δ=(%+.1f, %+.1f, %+.1f)mm %s"
            % (sid, x, y, z, dx, dy, dz, _dir))
        _gd = (sk.get("guard") or {}).get("dz_down_limit_mm")
        if _gd is not None and dz < -abs(float(_gd)):
            _allow = spec.get("allow_down_mm")
            if _allow is None or float(_allow) < abs(dz):
                log("🛡 拒绝: 技能守卫 dz_down_limit_mm=%.0fmm, 本次要向下 %.1fmm (要真的下降请带 allow_down_mm)"
                    % (float(_gd), -dz))
                return "🛡 已拒绝: 向下 %.0fmm 超过守卫 %.0fmm" % (-dz, float(_gd))
        sp = float(spec.get("speed", 60))
        call = ('ros2 service call /move_line interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
                'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
                % (sp, x, y, z, qx, qy, qz, qw))
    if spec.get("dry"):
        # 🧪 2026-09-20: 空跑 —— 算出目标位姿与将要下发的 ros2 调用并打印, **不下发**
        #   (反复练习/回点前先核对目标, 避免盲发; 也是无副作用的自证手段)
        log("DRY-RUN %s → %s" % (sid, call[:220]))
        return "DRY-RUN(未下发): %s" % call[:170]
    chan.stdin.write(call + "\n")
    chan.stdin.flush()
    log("已下发 %s -> %s · Δ=(%+.1f,%+.1f,%+.1f)mm %s"
        % (sid, (spec.get("d_mm", spec.get("force", spec.get("point", "")))), dx, dy, dz, _dir))
    return "已下发"


def out_thread(chan):
    for ln in chan.stdout:
        ln = ln.strip()
        if ln:
            log("ROS: " + ln[:200])


def main():
    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO)
    reg = json.load(open(REG_PATH, encoding="utf-8"))
    threading.Thread(target=state_thread, daemon=True).start()
    loop = PRE + 'while read -r c; do eval "$c"; done'
    chan = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HOST, loop],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    threading.Thread(target=out_thread, args=(chan,), daemon=True).start()
    log("L2 常驻执行器启动 · FIFO=%s · 原子技能 %d 个" % (FIFO, len(reg["skills"])))
    while True:
        reg = maybe_reload(reg)
        with open(FIFO, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    spec = json.loads(line)
                except Exception:
                    log("无效指令: %s" % line[:80])
                    continue
                # 🐛 2026-09-20 21:22 现场: 注册表热加载原来只在主循环顶部做 → 改完注册表后的
                #   **第一条**指令仍用旧表(新建的 L2.slot2 被判"未知技能", 第二条才认)。现在每条指令前重读。
                reg = maybe_reload(reg)
                try:
                    log("受理: " + dispatch(reg, spec, chan))
                except Exception as e:
                    log("执行异常: %s" % e)


if __name__ == "__main__":
    main()
