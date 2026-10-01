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

# 🔐 真动授权(8793 手动控制台)的单一真源 —— 所有运动下发的**唯一收口**(chan_send/服务调用/夹爪)
#   2026-09-29 老倪: 「我都取消授权了，手臂怎么还在动；金手指检测的点1技能，也要服从手动控制台的授权」
#   原来授权只活在 8793 进程内存里: ①GUI/脚本/自动流程直接写 FIFO 完全绕过它;
#   ②本执行器下发前也不校验 ⇒ 撤销前排队的动作会在 VL 慢层等 300s 之后才真下发。
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ctl_auth as CA
except Exception as _e:                                                 # noqa: BLE001
    CA = None
    print("!! ctl_auth 导入失败(%s) ⇒ 运动下发将**一律拒发**(fail-closed, 现场安全优先)" % _e, flush=True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "tashan@192.168.23.66"
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
# 原子技能注册表路径 (v5.11.1 热加载引入 REG_PATH, 当时漏了这行定义 -> NameError 起不来)
REG_PATH = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; "
      "export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; export ROS_LOCALHOST_ONLY=0; ")

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
    # 2026-09-28 现场修: /robot/tcp_pose 的 DDS 端点已死(机器人栈 2026-09-27 20:52 起的参与者
    # 在 06:22 时钟重同步后不再通告端点, 任何新订阅者 0 帧) ⇒ 执行器一直"位姿读不到"而拒发所有技能。
    # 现改为**优先读 ROKAE SDK 直采文件**(绕开 DDS, 5Hz, 口径 endInRef, 2026-09-21 实测与话题逐位一致),
    # 话题直读作兜底。文件龄 >10s 视为失效(不拿旧值当实时位姿)。
    try:
        import json as _json
        _fp = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
        if os.path.exists(_fp) and (time.time() - os.path.getmtime(_fp)) < 10.0:
            _d = _json.load(open(_fp, encoding="utf-8"))
            _v7 = [float(_d.get(k) or 0.0) for k in ("x", "y", "z", "qx", "qy", "qz", "qw")]
            if any(abs(_v7[i]) > 1e-6 for i in range(3)):
                return _v7
    except Exception as e:                                                   # noqa: BLE001
        log("SDK 直读位姿失败(退回话题): %s" % str(e)[:80])
    try:
        r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc",
                            "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                            "export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; export ROS_LOCALHOST_ONLY=0; ",
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


def _fresh_quat():
    """现读姿态(直读优先; 缓存必须 <5s)。返回 (quat|None, 源, 缓存年龄s)。

    ⚠️ 为什么不能让 rel 段吃 `_pose["q"]`: 那个缓存只由 state_thread(ssh + docker exec 读 ROS
    `/robot/tcp_pose`)更新, 它一旦断线就**静默冻住**从不重连 —— 2026-10-01 实测冻了 4.5 小时
    (停在侧面点1 的朝向 quat 0.7231), 而 rel 段("就地垂直抬 50mm")本该"姿态保持当前"; 吃陈旧
    缓存 ⇒ 真下发变成**边抬边转 93.7°**。相对运动的目标位姿里, 姿态永远取**现读**。
    """
    _p, _q, _src = _pose_best()
    if _q and len(_q) == 4:
        return list(_q), _src, (0.0 if _src == "direct" else max(0.0, time.time() - _pose["t"]))
    return None, _src, None


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
    """常驻位姿流(ssh + ROS 一次性 echo 循环) → `_pose` 缓存。

    ⚠️ 必须**自己重连**: 2026-10-01 实测这条 ssh 只读流断掉后线程直接结束, `_pose` 静默冻住 4.5 小时,
    没有任何日志 —— 而 plan_stage 的 rel 段会吃这个缓存 ⇒ 陈旧姿态被当成"当前姿态"下发。
    现在: 断了就大声记一条 + 5s 后重连; 直读链(`_pose_best`→`_pose_direct`)不受影响。
    """
    cmd = PRE + "while true; do ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null; sleep 0.5; done"
    while True:
        try:
            p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", HOST, cmd],
                                 stdout=subprocess.PIPE, text=True, bufsize=1)
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
            log("⚠️ 位姿常驻流结束(ssh/ROS 断开, 最后更新 %.0fs 前) —— 5s 后重连; 期间 rel 段改走直读" % max(0.0, time.time() - _pose["t"]))
        except Exception as e:                                                   # noqa: BLE001
            log("⚠️ 位姿常驻流异常: %s —— 5s 后重连" % str(e)[:80])
        time.sleep(5)


def _dir_label(dx, dy, dz):
    """运动方向标签(自解释): 前进/后退/向左/向右/上升/下降 + 基座轴向符号

    口径 (与旧注册表标签一致, 机器人右手系): +X=前 · +Y=左 · +Z=上。
    """
    if dz > 0.5:
        return "↑上升(+Z)"
    if dz < -0.5:
        return "↓下降(-Z)"
    if abs(dx) > 0.5 and abs(dx) >= abs(dy):
        return "→前进(+X)" if dx > 0 else "→后退(-X)"
    if abs(dy) > 0.5:
        return "→向左(+Y)" if dy > 0 else "→向右(-Y)"
    return "→平动"


def build_move(sk, spec, pts, cur=None, curq=None):
    # ⚠️ 相对运动的目标 = 真实当前位姿 + 偏移 → 位姿必须直读(常驻流缓存会滞后整分钟级,
    #    会把这 50mm 累加成错的落点); cur/curq 由调用方传入可避免重复直读。
    if cur is None:
        cur, curq, _src = _pose_best()
    p, q = cur, (curq or _pose["q"])
    if not p or not q:
        return None
    t = list(p)
    if sk["ros"] == "line_rel":
        _pd = (sk.get("param") or {}).get("d_mm") or {}
        d = float(spec.get("d_mm", _pd.get("default", 50))) / 1000.0
        a = sk["axis"]
        # 方向技能 (2026-09-20 老倪: 前后平移 → 前进/后退, 左右平移 → 向左/向右):
        #   **距离只填正数, 方向由技能内定** —— 现场不用再填负号(填错符号=往反方向走)。
        if a == "z_pos":
            t[2] = p[2] + abs(d)
        elif a == "z_neg":
            t[2] = p[2] - abs(d)
        elif a == "x_pos":
            t[0] = p[0] + abs(d)
        elif a == "x_neg":
            t[0] = p[0] - abs(d)
        elif a == "y_pos":
            t[1] = p[1] + abs(d)
        elif a == "y_neg":
            t[1] = p[1] - abs(d)
        elif a == "x":                      # 兼容旧行为(带符号)
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
            q, _qe = _quat4(pts[name]["quat"], name)       # 校验/整形: 分量数不对宁可拒, 也不发坏姿态
            if _qe:
                log("拒绝: 点位 %s 的姿态不可用(%s) ⇒ 拒发; 请重录该点" % (name, _qe))
                return None
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


def _quat_R(q):
    """四元数(xyzw) → 3x3 旋转矩阵 (用于工具坐标系平移: 生产口径 PoseTranslateLocalOffset)"""
    x, y, z, w = [float(v) for v in q]
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _qnorm(q):
    """四元数归一 (防数值漂移: 反复相乘后模长偏了会被控制器当成坏姿态)"""
    n = (q[0] ** 2 + q[1] ** 2 + q[2] ** 2 + q[3] ** 2) ** 0.5 or 1.0
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n]


def _quat4(q, name=""):
    """四元数整形/校验 → (q4, err)。**别再用 len(q)!=4 的四元数去拼指令**。

    2026-09-30 实测坑: 示教点库里有 7 个点(slot3/slot7/slot7_up/hole_retract/insert_*)
    的 ``quat`` 只存了 x,y,z(抄 slot1 改写 pos 时把 w 丢了), 而 ``plan_stage`` 取 ``q[3]``
    ⇒ ``IndexError`` 被外层吞成一行 ``执行异常``: 号位技能 dry 和真动**都**干点不动,
    现场只看到"点了没反应"。同类问题在单阶段点位技能里会变成"拼出一条坏姿态指令发出去"。

    口径(宁可拒发, 不瞎猜):
      · 4 分量 → 归一后放行;
      · 3 分量 → 唯一能有据补的形态: 按单位约束 w=+sqrt(1-(x²+y²+z²)) 补(取正号, 与同盘
        已记录点同号; 两候选姿态差 ≈ 2·asin|w| ~1°), **并在日志里喊出来 + 建议重录**;
        x²+y²+z²>1 时补不出来 ⇒ 拒;
      · 其它分量数 ⇒ 拒。
      数据侧已用 ``tools/fix_taught_quat.py`` 一次性补齐(可 --dry 复核)。
    """
    try:
        v = [float(x) for x in (q or [])]
    except (TypeError, ValueError):
        return None, "四元数不是数字"
    if len(v) == 4:
        return _qnorm(v), None
    if len(v) == 3:
        s = sum(x * x for x in v)
        if s > 1.0 + 1e-6:
            return None, "只有 3 分量且 x²+y²+z²=%.6f>1, 补不出 w" % s
        w = max(0.0, 1.0 - s) ** 0.5
        log("⚠️ 点位 %s 的 quat 只有 3 分量(缺 w) ⇒ 按单位约束补 w=+%.6f(与同盘已记录点同号); "
            "建议现场重录该点" % (name or "?", w))
        return _qnorm([v[0], v[1], v[2], w]), None
    return None, "四元数有 %d 个分量(应为 4: x,y,z,w)" % len(v)


def _qmul(a, b):
    """四元数乘法 (w 在末位, 与 xacro/ROS 一致)"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def _axis_q(axis, deg):
    """绕**工具自身**某轴的旋转四元数 (x/y/z = 俯仰/倾侧/自转)"""
    import math
    h = math.radians(deg) / 2.0
    s, c = math.sin(h), math.cos(h)
    return {"x": [s, 0.0, 0.0, c], "y": [0.0, s, 0.0, c], "z": [0.0, 0.0, s, c]}[axis]


def build_pose_rot(sk, spec, cur, curq):
    """🔄 原地姿态旋转 (2026-09-27 老倪手动控制区 A/B/C) —— **位置不动, 只改姿态**。

    数学与已验证的 `tools/l2_pose_rot.py` 同源: R_new = R_cur · R_axis(θ) (右手定则, **工具系**),
    走 /move_pose (TargetPose 同型; 实测该通道不掉电, 所以不用反复上电解锁)。

    axis: a=绕工具X(俯仰) · b=绕工具Y(倾侧) · c=绕工具Z(光轴自转);
    度数只填正数, 方向由技能内定(与方向点动同一口径：现场不用填负号)。
    返回 {"tq": (pos, quat), "deg": deg, "ax": ax, "dir": +1/-1, "label": ...} 或 None(已 log)。
    """
    if not cur or not curq:
        log("拒绝: 目标位姿读不到(直读失败且常驻缓存过期), 旋转需要真实当前姿态")
        return None
    ax = {"a": "x", "b": "y", "c": "z"}.get(str(sk.get("axis", "")).lower())
    if ax is None:
        log("拒绝: 技能 %s 的 axis=%r 不是 a/b/c (绕工具轴旋转只认这三个)" % (sk.get("id"), sk.get("axis")))
        return None
    _pd = (sk.get("param") or {}).get("deg") or {}
    deg = abs(float(spec.get("deg", _pd.get("default", 5))))
    _sign = -1.0 if str(sk.get("id", "")).endswith(("_neg", "_minus", "-")) else 1.0
    deg *= _sign
    g = dict(sk.get("guard") or {})
    g.update(spec.get("guard") or {})
    gmax = abs(float(g.get("max_deg", 30.0)))
    if abs(deg) > gmax:
        log("🛡 拒绝: 单次旋转 %.1f° 超过守卫 max_deg=%.0f° (要更大角度请分次转)" % (deg, gmax))
        return None
    q_new = _qnorm(_qmul(list(curq), _axis_q(ax, deg)))
    _cn = {"x": "A(工具X·俯仰)", "y": "B(工具Y·倾侧)", "z": "C(工具Z·自转)"}[ax]
    return {"tq": (list(cur), q_new), "deg": deg, "ax": ax,
            "label": "绕%s %+.1f°" % (_cn, deg)}


def _quat_angle_deg(a, b):
    """两个四元数之间的夹角(度) —— 用真值判"到底转了多少" """
    import math
    d = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))


def run_rot_chunks(sk, spec, sid, chan):
    """🔄 绕轴旋转: **单次 ≤max_deg 的守卫不变**, 一次点击**自动分次转到位**。

    2026-09-28 现场(老倪)「绕轴旋转怎么不好使」→ 页面角度档 20° > 守卫 max_deg=10° 直接被拒, 且返回文案写成
    "位姿缓存未就绪"(误导成位姿/通道坏了)。第一次修法(逐段"重读姿态再转一次")**又被现场证伪**:
    腕部转动是慢动作(实测单段 10° 要几十秒), 段间读到的还是没动的旧姿态 ⇒ 两段目标重合,
    合计只转了 10°。现修法: 全部段都从**起转前姿态 q0** 算**绝对目标** (q_i = q0 ⊗ R_axis(i·per)),
    相邻两次下发之间仍只差 per ≤ max_deg(守卫意图不变); 发完起个后台线程等终态, 用**真值**报"实测转过多少度"。
    """
    import math
    import threading
    total = abs(float(spec.get("deg") or ((sk.get("param") or {}).get("deg") or {}).get("default", 5) or 5))
    g = dict(sk.get("guard") or {})
    g.update(spec.get("guard") or {})
    gmax = abs(float(g.get("max_deg", 30.0)))
    ax = {"a": "x", "b": "y", "c": "z"}.get(str(sk.get("axis", "")).lower())
    if ax is None:
        msg = "🛡 拒绝: 技能 %s 的 axis=%r 不是 a/b/c (绕工具轴旋转只认这三个)" % (sid, sk.get("axis"))
        log(msg)
        return msg
    _pos0, _q0, _csrc = _pose_best()
    if not _pos0 or not _q0:
        msg = "🛡 拒绝: 姿态读不到(直读失败且常驻缓存过期) — 旋转需要真实当前姿态"
        log(msg)
        return msg
    n = max(1, int(math.ceil(total / gmax - 1e-9)))
    per = total / n
    _sign = -1.0 if str(sk.get("id", "")).endswith(("_neg", "_minus", "-")) else 1.0
    sp = float(spec.get("speed", 60))
    _cn = {"x": "A(工具X·俯仰)", "y": "B(工具Y·倾侧)", "z": "C(工具Z·自转)"}[ax]
    log("🔄 %s 起转: 绕%s %+.1f° · 分 %d 段(每段 %.1f° ≤ 守卫 %.0f°) · 位置不动(%.4f, %.4f, %.4f) · 起转姿态 quat [%.4f %.4f %.4f %.4f]"
        % (sid, _cn, _sign * total, n, per, gmax, _pos0[0], _pos0[1], _pos0[2], *_q0))
    for i in range(1, n + 1):
        _deg = _sign * per * i                 # 绝对目标: 从 q0 复合, 不依赖"上一段转完了没"
        _q_new = _qnorm(_qmul(list(_q0), _axis_q(ax, _deg)))
        _to = int(max(90, 20 + abs(per) * 3))
        call = ('timeout %d ros2 service call /move_pose interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
                'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
                % (_to, sp, _pos0[0], _pos0[1], _pos0[2], *_q_new))
        if spec.get("dry"):
            log("DRY-RUN %s 第 %d/%d 段(绝对 %+.1f°) → %s" % (sid, i, n, _deg, call[:200]))
            return "DRY-RUN(未下发): %s" % call[:170]
        if not chan_send(call, _intent_desc(sid, 0.0, 0.0, 0.0, "绕%s %+.1f° · 第 %d/%d 段" % (_cn, _deg, i, n))):
            _bm = _block_msg()
            log(_bm)
            return _bm
        log("已下发 %s 第 %d/%d 段 → 绝对 %+.1f° (目标姿态 quat [%.4f %.4f %.4f %.4f])"
            % (sid, i, n, _deg, *_q_new))
        if i < n:
            time.sleep(1.5)

    def _report():                              # 后台等终态, 用真值报"实测转了多少" —— 不堵主循环
        t0 = time.time()
        best = 0.0
        _s = ""
        while time.time() - t0 < 90:
            _p, _q, _s = _pose_best()
            if _q:
                best = _quat_angle_deg(_q0, _q)
                if abs(best - total) <= 2.0:
                    break
            time.sleep(2.0)
        log("✅ %s 实测转过 %.1f° (目标 %.1f° · 起转姿态→当前姿态, 真值 %s)" % (sid, best, total, _s or "?"))
    threading.Thread(target=_report, daemon=True).start()
    return "已下发 %d 段 · 合计 %.1f°(腕部转动较慢, 到位实测随后写日志)" % (n, total)


# ===== 🔩 第 6 轴 (J6) 独立自转 (2026-09-30 老倪手动控制台: 逆时针 / 顺时针) =====
#   「让 6 轴独立旋转」= **只转关节 J6 自己**(其余五轴不动)。两条通道:
#     ① 关节通道 `/target_relative_joint` —— 直接给关节增量, 但实测(rx rt 通道)动作后
#        **伺服下电**, 现场要反复上电(老倪骂过「怎么又下电了? 我还没看清动作呢」) ⇒ 不用;
#     ② 等效笛卡尔: 绕 **J6 轴轴线**(法兰原点 + link6 的 z)旋转, 走 `/move_pose`(实测不掉电)。
#   公式(由现场 URDF tool0→tool1 的固定位姿导出, 与当前姿态无关):
#     a_tool = R_off^T·[0,0,1] = (-0.6250, 0.0289, 0.7801)   J6 轴在**工具系**的方向
#     t_tool = R_off^T·t_off                                 TCP→法兰 平移(工具系)
#     a_base = R_tool·a_tool                                 base 系下 J6 轴方向
#     p_fl   = p_tcp − R_tool·t_tool                         法兰原点(轴线上一点)
#     p_new  = p_fl + Rot(a_base,θ)·(p_tcp − p_fl) · q_new = q(a_base,θ) ⊗ q_tcp
#   ⚠️ 别把 URDF 的 t_off 直接当工具系向量用: R_off ≠ I, 必须先换到工具系
#      (踩过: 直接把 t_off 乘 R_tool ⇒ 位置差 11mm/5°, 姿态却完全对 ⇒ 只有位置会错, 很隐蔽)。
#   离线核对(**零运动**): `python3 tools/test_j6_axis.py` —— 与 FK(q, J6±θ) 位置差 6e-14 mm ·
#      姿态差 1.7e-06° ⇒ 公式 = 纯 J6 自转(TCP 沿 ~24.2mm 半径走小圆弧: 5°≈2.1mm, 10°≈4.2mm)。
#   ⚠️ 现有 A/B/C(pose_rot) **转不到 J6**: J6 轴与工具 X/Y/Z 各差 51.3°/88.3°/38.7°。
_J6_RPY = (0.03702517838719945, 0.6751675651256659, 2.375248653715161)      # URDF tool0→tool1 rpy
_J6_T = (-0.01588615307905028, 0.018348498948158043, 0.2586775713451509)    # URDF tool0→tool1 xyz


def _rpy_R(r, p, y):
    """rpy(URDF 口径 Rz·Ry·Rx) → 3x3 旋转矩阵"""
    import math
    def rx(a):
        c, s = math.cos(a), math.sin(a)
        return [[1, 0, 0], [0, c, -s], [0, s, c]]

    def ry(a):
        c, s = math.cos(a), math.sin(a)
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]

    def rz(a):
        c, s = math.cos(a), math.sin(a)
        return [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    _mm = lambda A, B: [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return _mm(rz(y), _mm(ry(p), rx(r)))


def _R_T(R):
    """转置(正交阵的逆)"""
    return [[R[j][i] for j in range(3)] for i in range(3)]


def _R_mv(R, v):
    return [sum(R[i][k] * v[k] for k in range(3)) for i in range(3)]


J6_AXIS_TOOL = _R_mv(_R_T(_rpy_R(*_J6_RPY)), [0.0, 0.0, 1.0])       # J6 轴方向(工具系, 常数)
J6_T_TOOL = _R_mv(_R_T(_rpy_R(*_J6_RPY)), list(_J6_T))             # TCP→法兰平移(工具系, 常数)


def build_j6_rot(sk, spec, cur, curq):
    """🔩 由 TCP 位姿算「绕 J6 轴转 ±deg」的等效笛卡尔目标。

    返回 (p_new, q_new, deg, arc_mm) 或 None(已 log)。方向**由技能名内定**
    (`_ccw`=逆时针=+J6 · `_cw`=顺时针=−J6), 页面只填正数 —— 与方向点动同一口径。
    """
    import math
    if not cur or not curq:
        log("拒绝: 目标位姿读不到(直读失败且常驻缓存过期), J6 自转需要真实当前位姿")
        return None
    sid = str(sk.get("id", ""))
    _pd = (sk.get("param") or {}).get("deg") or {}
    deg = abs(float(spec.get("deg", _pd.get("default", 5))))
    if sid.endswith("_cw"):
        deg = -deg
    elif not sid.endswith("_ccw"):
        log("拒绝: 技能 %s 名字里既没有 _ccw 也没有 _cw —— J6 方向不明确, 不敢猜" % sid)
        return None
    g = dict(sk.get("guard") or {})
    g.update(spec.get("guard") or {})
    gmax = abs(float(g.get("max_deg", 10.0)))
    if abs(deg) > gmax:
        log("🛡 拒绝: J6 单次自转 %.1f° 超过守卫 max_deg=%.0f° (要更大角度请分次点)" % (deg, gmax))
        return None
    R = _quat_R(curq)
    a_base = _R_mv(R, J6_AXIS_TOOL)
    p_fl = [cur[i] - _R_mv(R, J6_T_TOOL)[i] for i in range(3)]        # 法兰原点(轴线过它)
    th = math.radians(deg)
    x, y, z = a_base
    c, s, C = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    Rr = [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
          [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
          [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]
    d = [cur[i] - p_fl[i] for i in range(3)]
    p_new = [p_fl[i] + _R_mv(Rr, d)[i] for i in range(3)]
    h = th / 2.0
    q_new = _qnorm(_qmul([x * math.sin(h), y * math.sin(h), z * math.sin(h), math.cos(h)], list(curq)))
    arc = math.sqrt(sum((p_new[i] - cur[i]) ** 2 for i in range(3))) * 1000.0
    return p_new, q_new, deg, arc


def run_j6_rot(sk, spec, sid, chan):
    """🔩 第 6 轴 (J6) 独立自转 · 单步 (守卫 max_deg=10°), 走 /move_pose。

    与 A/B/C(绕工具轴, TCP 不动)的区别: 这里转的是**关节 J6 自己**, TCP 沿 ~24.2mm 半径
    走小圆弧 —— 但**不掉电**(关节通道才会)。下发前打 Δ + 姿态前后(取证), 下发后后台用**姿态真值**
    报「实测转过多少度」(腕部慢转, 现场只回「已下发」会被当成没反应)。
    """
    import threading
    p0, q0, csrc = _pose_best()
    if not p0 or not q0:
        log("拒绝: 位姿读不到(直读失败且常驻缓存过期) — J6 自转需要真实当前位姿")
        return "🛡 已拒绝: 位姿读不到, 不敢转(原因见日志)"
    r = build_j6_rot(sk, spec, p0, q0)
    if not r:
        return "🛡 已拒绝: J6 自转条件不满足(位姿读不到 / 角度超守卫 / 方向未定义) — 原因见日志"
    p_new, q_new, deg, arc = r
    dx, dy, dz = [(p_new[i] - p0[i]) * 1000.0 for i in range(3)]
    log("🔩 目标 %s: 绕 J6 轴 %+.1f° · TCP Δ=(%+.1f, %+.1f, %+.1f)mm 沿腕轴小圆弧(%.2fmm, 半径≈24.2mm)"
        " · 位姿来源 %s" % (sid, deg, dx, dy, dz, arc, csrc))
    log("🔄 J6 自转 %+.1f°(绕**关节轴**, 非工具轴): quat [%.4f %.4f %.4f %.4f] → [%.4f %.4f %.4f %.4f]"
        % (deg, *q0, *q_new))
    sp = float(spec.get("speed", 8))
    _to = int(max(90, 20 + abs(deg) * 6))
    call = ('timeout %d ros2 service call /move_pose interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
            % (_to, sp, p_new[0], p_new[1], p_new[2], *q_new))
    if spec.get("dry"):
        log("DRY-RUN %s → %s" % (sid, call[:200]))
        return "DRY-RUN(未下发): %s" % call[:170]
    _desc = ("%s 第6轴(J6)自转 %+.1f° · 末端沿腕轴走 %.2fmm 小圆弧(绕关节轴自转, 非平移非下降)"
             % (sid, deg, arc))
    if not chan_send(call, _desc):
        _bm = _block_msg()
        log(_bm)
        return _bm
    log("已下发 %s → 绕 J6 轴 %+.1f° (目标姿态 quat [%.4f %.4f %.4f %.4f])" % (sid, deg, *q_new))

    def _report():                                   # 后台等终态, 用姿态真值报"实测转了多少"
        t0 = time.time()
        best = 0.0
        _s = ""
        while time.time() - t0 < 90:
            _p, _q, _s = _pose_best()
            if _q:
                best = _quat_angle_deg(q0, _q)
                if abs(best - abs(deg)) <= 1.5:
                    break
            time.sleep(2.0)
        log("✅ %s 实测转过 %.1f° (目标 %.1f° · 姿态真值 %s)" % (sid, best, abs(deg), _s or "?"))
    threading.Thread(target=_report, daemon=True).start()
    return "已下发 J6 %+.1f°(腕部慢转, 到位实测随后写日志)" % deg


def _args_to_yaml(a):
    """dict → ROS2 CLI 的服务请求串 {k: v, k2: [..]} (只支持 标量/布尔/数值数组)"""
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return repr(v)
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return str(v)
    return "{" + ", ".join("%s: %s" % (k, val(v)) for k, v in a.items()) + "}"


def _service_cmd(st):
    """服务步 → 远端命令行 (ros2 service call)"""
    return 'timeout %d ros2 service call %s %s "%s"' % (
        int(float(st.get("timeout_s", 60)) + 10), st["srv"], st["type"], _args_to_yaml(st.get("args") or {}))


def _service_call(st):
    """**同步**调一个 ROS 服务并解析真实回执 → (ok, 摘要)。

    为什么必须同步看回执: 力控类原语(里萨如力控插入)的成败只有驱动知道, 失败原因写在 message 里
    (实测 2026-09-17: `FORCE_CONTROL_CLEANUP_FAILED ... setToolset(tool1, wobj0) failed: 工具工件坐标系
    设置失败`)。只看"已下发"会把失败当成功 —— 老倪的红线: 判完成只看真值/真实回执, 不看 success 假象。
    """
    if not st.get("srv") or not st.get("type"):
        return False, "服务步缺少 srv/type"
    _a_ok, _a_why = _auth_guard(str(st.get("srv")) + " " + str(st.get("name") or ""), "服务步")
    if not _a_ok:
        log("🛑 被拦(真动授权): %s | 服务步=%s" % (_a_why, str(st.get("srv"))[:70]))
        return False, _a_why
    _mark_dispatch(_CUR.get("skill") or "服务步", "服务步", str(st.get("srv"))[:100])
    cmd = PRE + _service_cmd(st)
    t0 = time.time()
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd],
                           capture_output=True, text=True, timeout=float(st.get("timeout_s", 60)) + 25)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                                   # noqa: BLE001
        return False, "服务调用异常: %s" % e
    dt = time.time() - t0
    flat = out.replace(" ", "")
    if "success=True" in flat:
        ok = True
    elif "success=False" in flat:
        ok = False
    else:
        return False, "%.1fs · 没拿到 success 字段(超时/服务未起?) · 尾部: %s" % (dt, out.strip()[-200:])
    m = re.search(r"message='([^']*)'", out) or re.search(r'message="([^"]*)"', out)
    return ok, "%.1fs · success=%s · %s" % (dt, ok, (m.group(1) if m else "")[:400])


def _gripper_cmd(st):
    """夹爪步 → 远端命令行 (字段与产线 SetGripperPosition 同口径: pos/speed/force/acc/push_length/push_speed)

    ⚠️ 2026-09-21 (老倪「松开夹爪不好使」): 服务端没起时 `ros2 service call` 会**无限等**
    ("waiting for service to become available...") → 把常驻命令通道**永久卡死**, 后面所有技能排队。
    加 `timeout N`(timeout_s+10) 硬上限: 超时即返回失败, 通道立刻放行。
    注意口径: 客户端超时 ≠ 动作没下发 —— 判完成仍只看真值/回执(绝不重发)。
    """
    return ('timeout %d ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: %.1f, target_speed: %.1f, '
            'target_force: %.1f, target_acc: %.1f, target_push_length: %.1f, target_push_speed: %.1f}"'
            % (int(float(st.get("timeout_s", 30)) + 10),
               float(st.get("pos", 1000.0)), float(st.get("speed", -1.0)), float(st.get("force", -1.0)),
               float(st.get("acc", -1.0)), float(st.get("push_length", 0.0)), float(st.get("push_speed", 40.0))))


def _call_remote(cmd, timeout=40):
    """同步跑一条远端 ROS 服务命令 → (ok, 输出)。夹爪/力控这类必须看真实回执。"""
    _a_ok, _a_why = _auth_guard(str(cmd), "夹爪/力控")
    if not _a_ok:
        log("🛑 被拦(真动授权): %s | 本条=%s" % (_a_why, str(cmd)[:70]))
        return False, _a_why
    _mark_dispatch(_CUR.get("skill") or "夹爪/力控", "夹爪/力控", str(cmd)[:100])
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, PRE + cmd],
                           capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                                   # noqa: BLE001
        log("❌ ROS 回执: 调用异常 %s (cmd=%s)" % (e, str(cmd)[:60]))
        return False, "调用异常: %s" % e
    # 2026-09-29: 补 success/error —— 原来只打 joint_state, 现场出现"下发被应答但臂不动"时
    # 日志上分不清是控制器拒绝还是走完又回(老倪追问过两次)。这里固定留一行定性回执。
    _ok = "response:" in out
    _err = [l for l in out.splitlines() if any(w in l.lower() for w in ("error", "fail", "拒绝", "reject", "denied", "不可达", "unreachable"))]
    log("%s ROS 回执: %s%s" % ("✅" if (_ok and not _err) else "⚠️", "接受" if _ok else "无响应",
                              (" · 疑似错误: " + _err[0][:90]) if _err else ""))
    return _ok, out


def plan_stage(sk, st, pts, spec, cur):
    """算单阶段 目标/Δ/方向/下发字节; 守卫不过 → 返回 {"err":...} (调用方一律不下发)

    `rel: true` = **相对当前位姿**的运动(如"沿工具轴退 15mm"/"下移 3mm 补偿下垂") —— 目标从
    实时位姿算, 姿态保持当前。拔出这类动作必须用相对量: 力控插入会把模块多压进几毫米, 若用
    "回到示教插入位"的绝对点, 就变成了先把模块往回拽(锁着的时候=硬拽锁扣)。
    """
    if sk.get("ros") == "pose_rot":
        # 🔄 旋转是单步技能(位置不动, 一次一个角度) —— 多阶段(steps)会把 name/点位逻辑绕进去,
        #    静默算错落点。宁可直接拒发, 也不让"看起来跑了"。
        return {"err": "pose_rot(绕工具轴旋转)是单步技能, 不支持 steps 多阶段; 请去掉 steps"}
    if sk.get("ros") == "j6_rot":
        # 🔩 同理: J6 自转是单步(一次一个角度), 带 steps 会静默算错落点 ⇒ 直接拒发
        return {"err": "j6_rot(第6轴自转)是单步技能, 不支持 steps 多阶段; 请去掉 steps"}
    _qsrc, _qage = "none", None
    if st.get("rel"):
        name = "rel(当前位姿)"
        t = [float(v) for v in cur]
        # ⚠️ 姿态必须**现读**(见 _fresh_quat 注释): 相对段本来就该"姿态保持当前",
        #    吃陈旧缓存 ⇒ 真下发变成边平移边转大角度(2026-10-01 实测 93.7°)。
        q, _qsrc, _qage = _fresh_quat()
        if not q:
            return {"err": "现读姿态不可用(源=%s) ⇒ 拒发; 相对段要吃当前朝向, 不发陈旧姿态" % _qsrc}
        if _qsrc != "direct":
            log("⚠️ rel 段姿态取自 %s(%.1fs 前) —— 直读失败时的降级; 现场若见转动立即急停" % (_qsrc, _qage or 0.0))
    else:
        name = _point_name(sk, st, spec)
        if name not in pts:
            return {"err": "点位 %s 不在点位库" % name}
        t = [float(v) for v in pts[name]["pos"]]
        if str(st.get("quat", sk.get("quat", ""))).lower() == "taught" and pts[name].get("quat"):
            q, _qe = _quat4(pts[name]["quat"], name)       # 显式回示教姿态 → 纯平移, 不带旋转
            if _qe:
                return {"err": "点位 %s 的姿态不可用(%s) ⇒ 拒发; 请重录该点" % (name, _qe)}
        else:
            q, _qsrc, _qage = _fresh_quat()     # ⚠️ "姿态保持当前"也必须现读, 不吃陈旧缓存
            if q and len(q) != 4:
                return {"err": "当前姿态四元数有 %d 个分量(应为 4) ⇒ 拒发" % len(q)}
        if not q:
            return {"err": "现读姿态不可用(源=%s) ⇒ 拒发; 不发陈旧姿态" % _qsrc}
    t[2] += float(st.get("dz_mm", 0.0)) / 1000.0          # base 系竖直偏移(mm): 正=上, 负=下
    # 工具坐标系平移 (生产口径 PoseTranslateLocalOffset, 如插槽口 = 插入位沿工具 Z 退 60mm):
    #   沿**示教姿态自己的**局部 XYZ 轴平移 mm —— 这才对应"沿模块轴向退/进", 不是 base 竖直偏移。
    lm = st.get("local_mm")
    if lm:
        R = _quat_R(q)
        for i in range(3):
            t[i] += (R[i][0] * float(lm[0]) + R[i][1] * float(lm[1]) + R[i][2] * float(lm[2])) / 1000.0
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
    # 🛡 "先解锁再拔" 硬守卫 (2026-09-20 老倪现场提醒 + 产线口径):
    #   光模块插到位后**锁扣是锁住的**, 直接沿轴退 = 硬拽锁扣(可能伤模块/夹具)。
    #   产线做法: 合爪 force30 夹住后面**绿色环** → 沿工具轴退 15mm 解锁 → 再退 120mm 拔出。
    #   凡标了 needs_unlock 的阶段默认拒发, 只有显式 spec.allow_unlocked_retract=true(已解锁)才放行。
    if st.get("needs_unlock") and not spec.get("allow_unlocked_retract"):
        return {"err": "本阶段会拔出光模块, 但模块是锁住的 → 必须先解锁(合爪夹绿环→沿轴退15mm); "
                       "确认已解锁请带 allow_unlocked_retract=true", "pos": t}
    ml = g.get("max_lin_mm")
    if ml is not None and lin > float(ml):
        # 🔴 2026-09-27 老倪: 「一号位技能怎么没有反映了」—— 技能没坏, 是它每次都在**拒绝**,
        #   但拒答只说"太远", 没说"差多少、往哪个方向走" ⇒ 现场看不出下一步干嘛, 看起来就像没反应。
        #   改成把**方向 + 各轴差量**一起报出来: 照着点动过去, 再点一次本技能即可。
        _pairs = [("+X 前进", dx), ("+Y 左移(朝槽位)", dy)]
        _pairs.append(("+Z 抬升" if dz > 0 else "−Z 下降", abs(dz)))
        _pairs.sort(key=lambda kv: -abs(kv[1]))
        _dir = " · ".join("%s %.0fmm" % (n, abs(v)) for n, v in _pairs[:2] if abs(v) >= 5.0)
        return {"err": "本阶段目标点 %s 离当前位姿 %.0fmm, 超过守卫 %.0fmm ⇒ 先点动靠近再点本技能: %s"
                       % (name, lin, float(ml), _dir or "就在附近"),
                "pos": t, "lin": lin}
    sp = float(spec.get("speed", 60))
    if sk.get("speed_max") is not None:                    # 技能级限速上限(练习用低速, 收口在执行层)
        sp = min(sp, float(sk["speed_max"]))
    # ⚠️ 2026-09-21: 加硬超时, 服务端没起时别把命令通道永久卡死(客户端超时≠没下发, 到位仍只看真值)
    call = ('timeout %d ros2 service call /move_line interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
            % (int(_stage_timeout(st, lin, sp) + 10), sp, t[0], t[1], t[2], q[0], q[1], q[2], q[3]))
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


def _vision_resolve(sk, spec):
    """🎯 视觉引导门 (fail-closed): 跑一次双路视觉判据 → (槽位名, 一句证据, 说明)

    支持自检注入: 环境变量 L2_VISION_FAKE=slot1|slot2|none (离线自检用, 不碰真机)。
    任何异常 → 返回 None (调用方拒发), 绝不退化成"盲发到某个默认槽位"。
    """
    fake = os.environ.get("L2_VISION_FAKE", "").strip()
    if fake:
        if fake in ("slot1", "slot2"):
            return fake, "自检注入(未读真机)", "L2_VISION_FAKE=%s" % fake
        return None, "", "自检注入 %s (不得出槽位)" % fake
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import vision_grasp_skill as vgs                                   # noqa: PLC0415
        j = vgs.judge_slot(verbose=False)
    except Exception as e:                                                 # noqa: BLE001
        return None, "", "视觉模块不可用(%s: %s)" % (type(e).__name__, e)
    if not j.get("ok"):
        return None, "", "视觉判据未过: %s" % j.get("reason")
    ev = j.get("evidence") or {}
    B = (ev.get("routeB_pixel") or {}).get("per_slot", {}).get(j["slot"], {})
    n_det = next((r for r in (ev.get("routeA_box") or {}).get(j["slot"], []) if r.get("hit")), {})
    return j["slot"], ("双路一致 · YOLO Δx=%.1fpx dy=%+.1fpx(conf %.2f) · 像素峰距=%.1fpx"
                       % (n_det.get("dx", -1.0), n_det.get("dy", 0.0), n_det.get("conf", 0.0),
                          B.get("peak_dist_px", -1.0))), "vision_ok"


def _apply_vision_names(steps, guard, name):
    """占位点 slot_vision (阶段 to + 各级 z_floor_point) → 视觉解析出的真实槽位名。"""
    def _fixg(g):
        g = dict(g or {})
        if g.get("z_floor_point") == "slot_vision":
            g["z_floor_point"] = name
        return g
    out = []
    for st in steps:
        st2 = dict(st)
        if st2.get("to") == "slot_vision":
            st2["to"] = name
        if st2.get("guard"):
            st2["guard"] = _fixg(st2["guard"])
        out.append(st2)
    return out, _fixg(guard)


def run_stages(sk, spec, chan, pts):
    """多阶段技能: 逐阶段 ①算目标 ②守卫 ③下发 ④等真值到位 ⑤再进下一阶段。
    任一阶段被守卫拒/未到位 → 中止剩余阶段并**绝不重发**(30s 超时那次的教训)。

    🎯 视觉引导 (2026-09-22 · id=L2.grasp_vision): 条目带 vision_gate → 执行前跑**双路视觉判据**
      解析阶段里的占位点 slot_vision; 判不出/两路冲突/视觉模块不可用 → **拒发** (fail-closed, 宁缺勿假)。
    """
    steps = sk.get("steps") or []
    if sk.get("vision_gate"):
        _vn, _vin, _vwhy = _vision_resolve(sk, spec)
        if not _vn:
            log("🛡 视觉门拒发 (%s): %s" % (sk.get("id"), _vwhy))
            return "🛡 视觉门拒发: %s" % _vwhy
        if _vn not in pts:
            log("🛡 视觉门解析出的槽位 %s 不在点位库 → 拒发" % _vn)
            return "🛡 视觉门拒发: %s 不在点位库" % _vn
        sk = dict(sk)
        steps, _g2 = _apply_vision_names(steps, sk.get("guard"), _vn)
        sk["steps"] = steps
        sk["guard"] = _g2
        spec = dict(spec)
        spec["point"] = _vn
        log("🎯 视觉门通过: 目标槽位 = %s · %s" % (_vn, _vin))
    steps_all = steps
    _only = spec.get("stages")          # 分段执行: 只跑指定阶段(逐段核对/逐段请示, 其余本次不执行)
    if _only:
        _want = [int(x) for x in _only]
        steps = [st for st in steps_all if int(st.get("stage", steps_all.index(st) + 1)) in _want]
        if not steps:
            log("拒绝: stages=%s 没匹配到任何阶段" % _only)
            return "stages 过滤后没有阶段"
        log("分段执行: 只跑阶段 %s (共 %d 段)" % (_want, len(steps)))
    n = len(steps)
    # 🩹 2026-09-21 老倪: 「原子技能 松开夹抓, 怎么不好使了」—— 根因之一: 执行器**一律先读 TCP 位姿**,
    #   位姿源不可用 (产线驱动未跑) 时连纯夹爪指令都被拒 → 守卫越权 (夹爪指令本身不需要位姿)。
    #   改为: 本批若**全部是非运动步**(op=gripper/service), 位姿读不到也放行 (只在日志里声明);
    #   只要有任一运动步, 位姿仍严格要求 (不盲发, 纪律不变)。
    _has_motion = any(st.get("op") not in ("gripper", "service") for st in steps)
    cur, _cq, csrc = _pose_best()
    if not cur:
        if _has_motion:
            log("拒绝: 位姿读不到(直读失败且常驻缓存过期)")
            return "位姿缓存未就绪"
        log("⚠️ 位姿不可用, 但本批 %d 步全为非运动步(夹爪/服务) → 跳过位姿前置 (只发夹爪/服务指令)" % n)
        cur, csrc = [0.0, 0.0, 0.0], "none(非运动步, 无需位姿)"
    log("当前位姿(来源 %s): (%.4f, %.4f, %.4f)" % (csrc, cur[0], cur[1], cur[2]))
    plans, c = [], list(cur)
    # 🧗 运动段计数(2026-10-01 碰撞事故: 多段"设计出来的转移"才校验爬升; 单击回点位不动)
    _n_motion = sum(1 for _s in steps if _s.get("op") not in ("service", "gripper"))
    for i, st in enumerate(steps, 1):
        if st.get("op") == "service":
            # 服务步 (如里萨如力控搜索): 本机不下发运动, 由驱动自己动作 —— 计划阶段只做前置校验
            if not st.get("srv") or not st.get("type"):
                log("🛡 阶段 %d/%d 拒绝: 服务步缺 srv/type" % (i, n))
                return "阶段 %d 拒绝: 服务步缺 srv/type" % i
            plans.append({"service": True, "pos": None, "lin": 0.0, "speed": 0.0, "dx": 0.0, "dy": 0.0,
                          "dz": 0.0, "dir": "服务", "name": st["srv"], "call": _service_cmd(st)})
            log("阶段 %d/%d「%s」→ 调服务 %s (本机不下发运动; 力控由驱动执行)"
                % (i, n, st.get("note", ""), st["srv"]))
            continue
        if st.get("op") == "gripper":
            # 夹爪步: 同步调 gripper_driver + 看回执(curr_pos 是唯一能读到的夹爪真值)
            plans.append({"service": True, "pos": None, "lin": 0.0, "speed": 0.0, "dx": 0.0, "dy": 0.0,
                          "dz": 0.0, "dir": "夹爪", "name": "gripper", "call": _gripper_cmd(st)})
            log("阶段 %d/%d「%s」→ 调夹爪 pos=%s force=%s speed=%s"
                % (i, n, st.get("note", ""), st.get("pos"), st.get("force"), st.get("speed")))
            continue
        pl = plan_stage(sk, st, pts, spec, c)
        if pl.get("err"):
            log("🛡 阶段 %d/%d 拒绝: %s" % (i, n, pl["err"]))
            return "阶段 %d 拒绝: %s" % (i, pl["err"])
        plans.append(pl)
        c = pl["pos"]
        # 🌍 环境校验(2026-09-30 老倪: 「在任何一次运动中, 学习你的环境, 理解安全边界」):
        #    每段目标都过一遍 env_model 的**已验证包络**; 默认只记日志(零行为变化),
        #    设 ZMAX_ENV_GUARD=1 时越界即拒发。模型由 tools/env_model.py + 每 10 分钟 cron 持续学习。
        try:
            import env_model
            env_ok, env_msg = env_model.check_target(pl["pos"])
        except Exception as _e:                                                  # noqa: BLE001
            env_ok, env_msg = True, "环境模型不可用(%s)" % str(_e)[:50]
        # 🛡🛡 爬升闸(2026-10-01 碰撞事故, 见 docs/INCIDENT-20261001-traverse-height-collision.md)
        #   事故实况: 多段转移把"高位横移"高度写成与起点无关的绝对量(目标点 z+180mm) ⇒ 臂从起点再抬 217mm
        #   到 z=0.549 横移 194mm ⇒ 撞(日志里环境校验还写着"✅ 包络内")。现场规矩: 升高不要超过 10cm。
        #   ⚠️ 环境包络校验**不能**替代本闸 —— 包络由历史运动数据拟合, 只代表"臂去过哪儿", 不代表"那儿没东西"。
        #   只对**多段设计转移**(>=2 个运动段)硬拦; 单段直发(老倪日常单击回点位)只吼不拦 ⇒ 零行为变化。
        if _n_motion >= 2 and pl.get("pos") and cur:
            try:
                _climb = (float(pl["pos"][2]) - float(cur[2])) * 1000.0
                _lim = float(spec.get("climb_limit_mm", st.get("climb_limit_mm", 100.0)))
                _allow = float(spec.get("allow_climb_mm", 0.0) or 0.0)
                if _climb > max(_lim, _allow) + 1e-6:
                    log("🛡🛡 阶段 %d/%d 拒发: 相对计划起点抬升 %.0fmm > 上限 %.0fmm 「现场规矩: 升高不要超过 10cm」"
                        " —— 横移高度必须相对当前高度有界, 不能写成与起点无关的绝对量(如\"目标点z+180\")。"
                        " 现场目视确认净空后, 请求带 allow_climb_mm=%.0f 才放行。" % (i, n, _climb, _lim, _climb))
                    return "阶段 %d 拒发: 抬升 %.0fmm 超 %.0fmm 上限(需 allow_climb_mm 显式放行)" % (i, _climb, _lim)
                log("🧗 阶段 %d/%d 抬升检查: 相对计划起点 %+.0fmm · 上限 %.0fmm ✅" % (i, n, _climb, _lim))
            except Exception as _e:                                              # noqa: BLE001
                log("🧗 阶段 %d/%d 抬升检查跳过(%s)" % (i, n, str(_e)[:40]))
        elif pl.get("pos") and cur:
            try:
                _climb = (float(pl["pos"][2]) - float(cur[2])) * 1000.0
                if _climb > 100.0:
                    log("⚠️ 单段直发抬升 %.0fmm 超 10cm 规矩(未拦, 你日常单击回点位用; 若是设计出来的转移请改多段)" % _climb)
            except Exception:                                                    # noqa: BLE001
                pass
        log("🌍 环境校验 阶段 %d/%d: %s" % (i, n, env_msg))
        if not env_ok and os.environ.get("ZMAX_ENV_GUARD") == "1":
            log("🛡 阶段 %d/%d 拒绝: %s (ZMAX_ENV_GUARD=1)" % (i, n, env_msg))
            return "阶段 %d 拒绝: %s" % (i, env_msg)
        log("阶段 %d/%d「%s」点=%s pos=(%.4f, %.4f, %.4f) · 预计Δ=(%+.1f, %+.1f, %+.1f)mm %s · 直线 %.0fmm · speed %s · 等待上限 %.0fs"
            % (i, n, st.get("note", ""), pl["name"], pl["pos"][0], pl["pos"][1], pl["pos"][2],
               pl["dx"], pl["dy"], pl["dz"], pl["dir"], pl["lin"], pl["speed"],
               _stage_timeout(st, pl["lin"], pl["speed"])))
    if spec.get("dry"):
        for i, pl in enumerate(plans, 1):
            if pl.get("service"):
                log("DRY-RUN 阶段 %d/%d 将调用: %s" % (i, n, pl["call"]))
            else:
                log("DRY-RUN 阶段 %d/%d 将下发: %s" % (i, n, pl["call"][:220]))
        return "DRY-RUN(未下发) %d 阶段: %s" % (
            n, " | ".join(("阶段%d 服务 %s" % (i, p["name"])) if p.get("service")
                          else ("阶段%d Δ=(%+.1f,%+.1f,%+.1f)mm%s" % (i, p["dx"], p["dy"], p["dz"], p["dir"]))
                          for i, p in enumerate(plans, 1)))
    for i, st in enumerate(steps, 1):
        pl = plans[i - 1]
        if st.get("op") == "gripper":
            ok, out = _call_remote(_gripper_cmd(st), float(st.get("timeout_s", 30)) + 15)
            _m = re.search(r"curr_pos=([-\d.]+)", out)
            log("阶段 %d/%d「%s」夹爪回执: curr_pos=%s · %s"
                % (i, n, st.get("note", ""), _m.group(1) if _m else "?", "OK" if ok else out.strip()[-160:]))
            if not ok:
                log("🛑 阶段 %d/%d 夹爪服务失败 → 中止剩余阶段" % (i, n))
                return "🛑 阶段 %d 夹爪失败" % i
            time.sleep(float(st.get("dwell_s", 0.5)))
            continue
        if st.get("op") == "service":
            # 力控类原语: **同步**调用 + 看真实回执(success/message), 失败即中止, 绝不重发
            ok, info = _service_call(st)
            log("阶段 %d/%d「%s」服务回执: %s" % (i, n, st.get("note", ""), info))
            if not ok:
                log("🛑 阶段 %d/%d 服务失败 → 中止剩余阶段, 不重发" % (i, n))
                return "🛑 阶段 %d 服务失败: %s" % (i, info)
            time.sleep(float(st.get("dwell_s", 0.5)))
            continue
        live, _lq, lsrc = _pose_best()                     # 下发前用**实时直读位姿**复算 Δ + 复检守卫
        if live:
            pl2 = plan_stage(sk, st, pts, spec, live)
            if pl2.get("err"):
                log("🛡 下发前复检拒绝 阶段 %d/%d: %s" % (i, n, pl2["err"]))
                return "🛡 阶段 %d 被守卫拒绝" % i
            pl = pl2
        _to = _stage_timeout(st, pl["lin"], pl.get("speed", spec.get("speed", 60)))
        if not chan_send(pl["call"], _intent_desc(pl.get("name", "阶段"), pl.get("dx", 0.0), pl.get("dy", 0.0),
                                                  pl.get("dz", 0.0), "直线 %.0fmm" % (pl.get("lin") or 0))):
            # 🧭 把"被哪一层拦、为什么"原样带出去给界面(老倪: 点了必须出结果, 别只说"通道不可用或VL拒发")
            _why = _block_msg()
            log("🛑 阶段 %d/%d 下发被拦 → 中止剩余阶段(绝不重发) · %s" % (i, n, _why))
            return "🛑 阶段 %d 下发被拦: %s" % (i, _why)
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
            # 🛠 2026-09-23: 服务端 4xx/5xx 时把**响应体**读出来 (原来只回 "HTTP Error 500
            #   INTERNAL SERVER ERROR", 看不出真因; 实测 body={"code":500,"msg":"相机初始化失败"}),
            #   并把 AOI 侧常见真因一并提示, 免得现场只能干瞪眼。
            _body = ""
            try:
                _e = getattr(e, "read", None)
                _raw = e.read() if callable(_e) else b""
                _body = _raw.decode("utf-8", "ignore")[:200].replace("\n", " ")
            except Exception:                                        # noqa: BLE001
                pass
            _hint = ""
            _msg = ""
            try:                                                     # body 是 {"code":..,"msg":..} (可能被 \\u 转义)
                _j = json.loads(_body) if _body else {}
                _msg = str(_j.get("msg", "")) or _body
            except Exception:                                        # noqa: BLE001
                _msg = _body
            if "Connection refused" in str(e) or "Errno 111" in str(e):
                _hint = (" | 真因=工控机上那套 AOI 程序**没在监听**(端口拒绝连接) "
                         "→ 需在 .23 上把对应程序(金手指 10082 / 表面 10083)启动起来; 本机侧无解")
            elif "相机初始化失败" in _msg or "相机初始化失败" in _body:
                _hint = (" | 真因=工控机侧**相机初始化失败**: 相机被其它程序独占/USB掉线/未上电 "
                         "→ 需在 .23 上关掉占用相机的程序(或重插相机)后重试; 本机侧无解")
            elif "尚无" in _msg:
                _hint = " | 真因=服务端本轮还没拍过照 → 先跑「金手指①触发拍照检测」"
            log("HTTP 失败 %s: %s %s%s" % (url, e, _msg or _body, _hint))
            return "HTTP 失败: %s | %s%s" % (e, _msg or _body, _hint)
    if sk["ros"] == "gripper":
        # 🩹 2026-09-21: 单步夹爪技能原来没定义 dx/dy/dz/_dir, 走到下面的日志行会抛 NameError
        #   (表现就是"原子技能 松开夹爪 不好使")。夹爪步本来就没有位移, 显式置零并标"夹爪"。
        dx = dy = dz = 0.0
        _dir = "夹爪"
        if "close" in sid:
            fo = float(spec.get("force", sk["param"]["force"].get("default", 40)))
            call = ('timeout 30 ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 0.0, '
                    'target_speed: -1.0, target_force: %s, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"' % fo)
        else:
            call = ('timeout 30 ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 1000.0, '
                    'target_speed: -1.0, target_force: -1.0, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"')
    else:
        # 点位来源: ①演示学习轨迹点 ②L2 传授点库 taught_points.json (2026-09-20 起,
        #   供"进入金手指AOI检测区"这类按现场示教的绝对点回点; 同名以传授点库为准)
        pts = _load_points()
        # 🅰 2026-09-20【一号位】: 技能带 steps → 多阶段执行(逐阶段下发 + 真值等到位再进下一阶段)
        if sk.get("steps"):
            return run_stages(sk, spec, chan, pts)
        # 相对运动(前进/后退/向左/向右/抬升/下降)的落点 = **真实当前位姿** + 偏移
        # → 位姿直读, 不用滞后缓存(缓存滞后会把每一步的误差累加成错落点); 与 Δ 日志共用同一次读。
        # 🔄 2026-09-27 老倪(手动控制区): A/B/C = 原地姿态旋转, 位置不动 → 不走 build_move 的平移分支
        # 🔧 2026-09-28: 页面角度档(20°) > 技能守卫(max_deg=10°) 会被拒且文案误导 ⇒ 交 run_rot_chunks 自动分次
        if sk.get("ros") == "pose_rot":
            return run_rot_chunks(sk, spec, sid, chan)
        # 🔩 2026-09-30 老倪手动控制台: 「让 6 轴独立旋转」—— 只转关节 J6 自己。
        #   等效笛卡尔实现, 走 /move_pose(不掉电); 关节通道 /target_relative_joint 动作后会**伺服下电**。
        #   ⚠️ 别把它并进 pose_rot: pose_rot 是绕**工具轴**且 TCP 不动, 数学上转不到 J6(差 39~88°)。
        if sk.get("ros") == "j6_rot":
            return run_j6_rot(sk, spec, sid, chan)
        _cur, _cq, _csrc = _pose_best()
        _rot = None
        r = build_move(sk, spec, pts, _cur, _cq)
        if not r:
            log("拒绝: 位姿读不到(直读失败且常驻缓存过期)或点位不存在")
            return "位姿缓存未就绪"
        (x, y, z), (qx, qy, qz, qw) = r[0], r[1]
        # 🛡 2026-09-20 事故修复 (老倪按下急停那次): 下发前一律算 Δ 并做方向守卫 ——
        #   架构原则"执行由最下层收口": 上层点错点/送错参数, 底层必须能看见 Δ 并有权拒发。
        _c0 = _cur or [0.0, 0.0, 0.0]
        dx, dy, dz = (x - _c0[0]) * 1000.0, (y - _c0[1]) * 1000.0, (z - _c0[2]) * 1000.0
        _dir = _dir_label(dx, dy, dz)
        log("目标 %s: pos=(%.4f, %.4f, %.4f) · Δ=(%+.1f, %+.1f, %+.1f)mm %s · 位姿来源 %s"
            % (sid, x, y, z, dx, dy, dz, _dir, _csrc))
        # 🌍 环境校验(老倪 2026-09-30「在任何一次运动中, 学习你的环境, 理解安全边界」):
        #    单步技能也在下发前过一遍 env_model 的已验证包络; 默认只记日志, ZMAX_ENV_GUARD=1 才拦。
        try:
            import env_model as _em
            _eok, _emsg = _em.check_target([x, y, z])
        except Exception as _e:                                                   # noqa: BLE001
            _eok, _emsg = True, "环境模型不可用(%s)" % str(_e)[:50]
        log("🌍 环境校验 %s: %s" % (sid, _emsg))
        if not _eok and os.environ.get("ZMAX_ENV_GUARD") == "1":
            log("🛡 %s 拒绝: %s (ZMAX_ENV_GUARD=1)" % (sid, _emsg))
            return "目标出已验证包络: %s" % _emsg
        if _rot:                       # 旋转: 位置必须不动(Δ≈0), 只报姿态前后 —— 这条日志就是取证
            _dir = _rot["label"]
            log("🔄 %s: 当前位置不动, 姿态 quat [%.4f %.4f %.4f %.4f] → [%.4f %.4f %.4f %.4f]"
                % (_rot["label"], *(_cq or [0, 0, 0, 0]), qx, qy, qz, qw))
        _gd = (sk.get("guard") or {}).get("dz_down_limit_mm")
        if _gd is not None and dz < -abs(float(_gd)):
            _allow = spec.get("allow_down_mm")
            if _allow is None or float(_allow) < abs(dz):
                log("🛡 拒绝: 技能守卫 dz_down_limit_mm=%.0fmm, 本次要向下 %.1fmm (要真的下降请带 allow_down_mm)"
                    % (float(_gd), -dz))
                return "🛡 已拒绝: 向下 %.0fmm 超过守卫 %.0fmm" % (-dz, float(_gd))
        sp = float(spec.get("speed", 60))
        # 🔄 旋转走 /move_pose (与 tools/l2_pose_rot.py 已验证通道一致); 平移仍走 /move_line
        _srv = "/move_pose" if _rot else "/move_line"
        _to = int(max(90, 20 + abs(float(_rot["deg"])) * 3)) if _rot else 90
        call = ('timeout %d ros2 service call %s interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
                'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
                % (_to, _srv, sp, x, y, z, qx, qy, qz, qw))
    if spec.get("dry"):
        # 🧪 2026-09-20: 空跑 —— 算出目标位姿与将要下发的 ros2 调用并打印, **不下发**
        #   (反复练习/回点前先核对目标, 避免盲发; 也是无副作用的自证手段)
        log("DRY-RUN %s → %s" % (sid, call[:220]))
        return "DRY-RUN(未下发): %s" % call[:170]
    if not chan_send(call, _intent_desc(sid, dx, dy, dz)):
        _bm = _block_msg()
        log(_bm)
        return _bm
    log("已下发 %s -> %s · Δ=(%+.1f,%+.1f,%+.1f)mm %s"
        % (sid, (spec.get("d_mm", spec.get("force", spec.get("point", "")))), dx, dy, dz, _dir))
    return "已下发"


def out_thread(chan):
    for ln in chan.stdout:
        ln = ln.strip()
        if ln:
            log("ROS: " + ln[:200])


# ── 命令通道自愈 (2026-09-21 老倪: 「原子技能 松开夹爪 不好使」根因之二) ─────────
#   实况取证: 开机 20:08:32 建的常驻 ssh 通道**建完就死了**(子进程 5587 变僵尸 Z 状态),
#   之后每次 chan.stdin.write 直接 Broken pipe → 所有技能静默失效(不止夹爪),
#   而 keepalive 只判\"进程在不在\" → 永不恢复。修法:
#   ① 启动前等直连链路 + 用一次性 ssh 探针确认真能登录(不然白建通道 = 又变僵尸)
#   ② 写失败 → 自动重建通道并重试一次
#   ③ 后台看门狗 15s 一查, 通道静默死掉也自愈
_CHAN = {"p": None, "spawn_t": 0.0}
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "TCPKeepAlive=yes"]


def _link_ready(timeout=120):
    """等直连产线网源地址就绪 (开机竞态: 网卡地址晚于自启服务)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = subprocess.run(["ip", "route", "get", "192.168.23.66"],
                               capture_output=True, text=True, timeout=5)
            if "src 192.168.23.50" in r.stdout:
                return True
        except Exception:                                                    # noqa: BLE001
            pass
        time.sleep(2)
    return False


def _ssh_once(cmd, timeout=15):
    try:
        r = subprocess.run(["ssh"] + _SSH_OPTS + [HOST, cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:                                                   # noqa: BLE001
        return False, str(e)


def _chan_alive():
    p = _CHAN["p"]
    return bool(p) and p.poll() is None


def _spawn_chan(force=False):
    """(重)建常驻命令通道。force=True 时先收掉老的(含僵尸, 别留 <defunct>)。"""
    if _chan_alive() and not force:
        return _CHAN["p"]
    old = _CHAN["p"]
    if old is not None:
        for _f in (lambda: old.stdin.close(), old.kill):
            try:
                _f()
            except Exception:                                                # noqa: BLE001
                pass
        try:
            old.wait(timeout=5)          # 收僵尸
        except Exception:                                                    # noqa: BLE001
            pass
    loop = PRE + 'while read -r c; do eval "$c"; done'
    p = subprocess.Popen(["ssh"] + _SSH_OPTS + [HOST, loop], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    _CHAN["p"], _CHAN["spawn_t"] = p, time.time()
    threading.Thread(target=out_thread, args=(p,), daemon=True).start()
    log("🔌 命令通道已建立 (pid=%d)" % p.pid)
    return p


# ===== 🛡 VL 视觉安全闸: DeepSeek VL 进控制环 (2026-09-27 老倪) =====
# 老倪: 「你现在有三个相机，还有深度信号，你的大模型，要负责安全保护。把 deepseek VL 加入控制循环」
# 形态: VL 单次 40~150s ⇒ 当**慢传感器**(vl_safety_monitor.py 常驻维持带时间戳的裁决),
#       执行层每次运动下发前读最新裁决: 缺失/过期/不安全 ⇒ **一律拒发**(fail-closed, 看不清也拒)。
#       关闸: env ZMAX_VL_GUARD=0, 或运行时文件 ~/zmax_data/vl_guard_off.json(带 until 到期即自动恢复) —— 见 _vl_disabled()。
#       停机/复位类**永远放行**(闸门不许挡急停)。
VL_VERDICT_PATH = os.path.expanduser("~/zmax_data/vl_safety.json")
VL_FRESH_S = float(os.environ.get("ZMAX_VL_FRESH_S", "600"))
VL_INTENT_PATH = os.path.expanduser("~/zmax_data/vl_intent.json")
VL_INTENT_WAIT_S = float(os.environ.get("ZMAX_VL_INTENT_WAIT_S", "300"))
# 🔁 同一动作的裁决在这么长时间内可直接复用(见 _vl_reuse_ok): 免去每次点击干等一轮慢层
VL_REUSE_S = float(os.environ.get("ZMAX_VL_REUSE_S", "300"))
_VL_ALWAYS_ALLOW = ("robot_stop", "rokae_recover_estop", "estop", "recover")
# 🔓 关闸的运行时开关 (2026-09-28 现场: 老倪「关闭安全」)
#   除 env 外再给一个**带到期时间的文件**: 现场不重启就能开关, 且到期**自动恢复**安全(fail-closed),
#   避免"关了忘了开"; 每次下发都把开关状态写进审计日志(可追是谁什么时候关的)。
VL_GUARD_OFF_PATH = os.path.expanduser("~/zmax_data/vl_guard_off.json")


def _vl_disabled():
    """(disabled, why): 安全闸是否被显式关掉。env ZMAX_VL_GUARD=0 优先, 其次看运行时文件。"""
    if os.environ.get("ZMAX_VL_GUARD", "1").strip().lower() in ("0", "off", "false", "no"):
        return True, "env ZMAX_VL_GUARD=0"
    try:
        d = json.loads(open(VL_GUARD_OFF_PATH, encoding="utf-8").read())
    except Exception:                                                       # noqa: BLE001
        return False, ""
    if not d.get("enabled"):
        return False, ""
    _u = d.get("until")
    if _u and time.time() > float(_u):
        return False, ""                    # ⏰ 到期即自动恢复安全 —— 不需要任何人操作
    _left = ("到期 %s" % time.strftime("%H:%M:%S", time.localtime(float(_u)))) if _u else "**无到期时间(需手动关)**"
    return True, "%s · by=%s · %s" % (_left, str(d.get("by") or "-")[:24], str(d.get("note") or "")[:44])


_INTENT = {"seq": 0, "desc": ""}
try:      # 序号必须**跨重启单调**: 否则新旧动作撞号, 慢层的"同一动作两轮比对"会错配(2026-09-27 实测踩到)
    _INTENT["seq"] = int(json.loads(open(VL_INTENT_PATH, encoding="utf-8").read()).get("seq") or 0)
except Exception:                                                       # noqa: BLE001
    pass


def _intent_desc(name: str, dx: float, dy: float, dz: float, extra: str = "") -> str:
    """把这一步动作讲清楚(老倪: 闸门要知道"我下一步干什么"才判得准)。"""
    if abs(dz) < 0.5 and (abs(dx) > 0.5 or abs(dy) > 0.5):
        kind = "纯横向平移, 高度不变(不会更接近下方物体)"
    elif dz > 0.5:
        kind = "抬升(远离下方物体; 注意上方横梁/遮挡)"
    elif dz < -0.5:
        kind = "下降(必须确认正下方无障碍且余量足够)"
    else:
        kind = "原地姿态微调(位置不动)"
    return "%s Δ=(%+.1f, %+.1f, %+.1f)mm · %s%s" % (name, dx, dy, dz, kind, (" · " + extra) if extra else "")


def set_intent(desc: str) -> int:
    """把"下一步要做的动作"告诉 VL 慢层, 返回意图序号。"""
    _INTENT["seq"] += 1
    _INTENT["desc"] = desc
    try:
        with open(VL_INTENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "ts_str": time.strftime("%F %T"),
                       "seq": _INTENT["seq"], "desc": desc}, f, ensure_ascii=False, indent=1)
    except Exception as e:                                              # noqa: BLE001
        log("🛡 意图写入失败: %s" % str(e)[:70])
    return _INTENT["seq"]


def _vl_reuse_ok(desc: str):
    """**同一动作**的新鲜裁决可直接复用 —— 不必为每次点击干等一轮慢层(45~190s)。

    🐢 2026-09-28 老倪: 「技能还是不好使, 前进不好使」—— 每次点击都触发慢层重跑(远端 VL 45~190s),
    现场等于不可用(点一下要等 1~3 分钟)。本函数给出**不削弱安全**的复用口径:
      · 复用判据 = 裁决的 intent_desc 与本动作**逐字相同**(同一技能 + 同一 Δ + 同一动作类)
        且 裁决 ts 在 VL_REUSE_S(默认 300s) 内 且 safe=True 且 risk_level=low;
      · 慢层回答的是"**这一类动作**在当前场景能不能做"; 场景**此刻**有没有人/遮挡由快层
        (本地 5Hz · 0.1s)在**下发那一刻**实测 —— 复用不越过快层, 手伸进来照样立刻拒发;
      · 复用与重跑**都写日志**(写明复用了几秒前的哪一条裁决), 事后可核对。
    返回 (ok: bool, 说明: str)
    """
    try:
        d = json.loads(open(VL_VERDICT_PATH, encoding="utf-8").read())
    except Exception as e:                                              # noqa: BLE001
        return False, "无裁决文件(%s)" % str(e)[:60]
    vd = d.get("intent_desc") or ""
    age = time.time() - float(d.get("ts") or 0)
    if vd != desc:
        return False, "动作不同(最近裁决=%.30s…)" % vd
    if age > VL_REUSE_S:
        return False, "同动作但裁决已 %.0fs 前 > %.0fs" % (age, VL_REUSE_S)
    if (not d.get("safe")) or str(d.get("risk_level") or "").lower() not in ("low", "none"):
        return False, "同动作裁决不够干净(safe=%s risk=%s)" % (d.get("safe"), d.get("risk_level"))
    return True, ("复用 %.0fs 前**同一动作**的裁决(seq=%s · risk=%s · %s)"
                  % (age, d.get("intent_seq"), d.get("risk_level"), d.get("ts_str")))


# ===== 🔐 真动授权闸 (8793 手动控制台 · 2026-09-29) =====
#   口径: **凡是能让臂/夹爪动的下发, 一律要此刻有授权**(不是"签发时有"); 撤销 ⇒ 立刻失效。
#   停/复位类永远放行(闸门不许挡急停)。
_CUR = {"epoch": None, "skill": "", "t": 0.0}      # 当前正在处理的 FIFO 命令(签发时的授权 epoch)
DISPATCH_MARK = os.path.expanduser("~/zmax_data/l2_last_dispatch.json")


def _auth_guard(call: str, kind: str = "运动"):
    """(ok, why): 该条下发此刻是否被授权。CA 缺失 ⇒ 拒发(现场安全优先)。"""
    if any(k in (call or "") for k in _VL_ALWAYS_ALLOW):
        return True, "停机/复位类 ⇒ 放行(闸门不挡急停)"
    if CA is None:
        return False, "🛑 ctl_auth 不可用(单一真源缺失) ⇒ 拒发: 运动一律要过 8793 授权"
    ok, why = CA.check(_CUR.get("epoch"))
    if not ok:
        return False, why                        # 只回原因; "🛑 被拦(层)" 前缀由 _note_block/调用方统一加
    return True, why


def _mark_dispatch(skill: str, kind: str, extra: str = ""):
    """下发留痕 —— 撤销时需要知道"刚才有没有真下发", 由 ctl_revoke_stop 决定要不要叫停。"""
    try:
        with open(DISPATCH_MARK, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "ts_str": time.strftime("%F %T"), "skill": skill,
                       "kind": kind, "extra": extra[:120], "auth_epoch": _CUR.get("epoch")}, f, ensure_ascii=False)
    except Exception:                                                   # noqa: BLE001
        pass


def _vl_wait_intent(seq: int, desc: str) -> bool:
    """等到 VL 基于本次意图给出裁决(最多 VL_INTENT_WAIT_S 秒); 等不到 ⇒ 不拿旧裁决放行。"""
    t0 = time.time()
    while time.time() - t0 < VL_INTENT_WAIT_S:
        time.sleep(2.0)
        # 🔐 等慢层期间**每一步都复核真动授权**: 人已点「撤销」⇒ 本条立即作废(现场实测存在的窗口:
        #   点授权 → 排队等慢层 300s → 期间撤销 → 原来照样下发, 表现为"取消了授权还在动")
        _aok, _awhy = _auth_guard("motion", "等慢层")
        if not _aok:
            log("⏹ %s ⇒ 本条立即作废(不再等裁决, 绝不下发)" % _awhy)
            _note_block("真动授权·8793 手动控制台", "%s ⇒ 等慢层期间被撤销, 本条作废(未下发)" % _awhy)
            return False
        try:
            d = json.loads(open(VL_VERDICT_PATH, encoding="utf-8").read())
        except Exception:                                               # noqa: BLE001
            continue
        if int(d.get("intent_seq") or 0) >= seq and (d.get("intent_desc") or "") == desc:
            return True
    return False


def _vl_operator_auth(action: str, consume: bool = True):
    """人工一次性授权(老倪现场授权 · 2026-09-27「继续, 安全, 开干」)。

    只越过**慢层(VL 判断)**: 现场人已确认安全、而远端 VL 因拥塞/限流给不出裁决时用。
    **快层(本地 0.2s 遮挡反射)永远有效, 任何授权都不能越过它** —— 手突然伸进来依然立刻拒发。
    授权文件: ~/zmax_data/vl_operator_auth.json {enabled, ts, ttl_s, max_uses, used, scope[], by, note}
    审计: 每用一次写 ~/zmax_data/vl_operator_auth_log.jsonl(带时刻/动作/授权人/第几次)。
    """
    try:
        p = os.path.expanduser("~/zmax_data/vl_operator_auth.json")
        a = json.loads(open(p, encoding="utf-8").read())
    except Exception:                                                   # noqa: BLE001
        return None
    if not a.get("enabled"):
        return None
    age = time.time() - float(a.get("ts") or 0)
    if age > float(a.get("ttl_s") or 300):
        return None
    if int(a.get("used") or 0) >= int(a.get("max_uses") or 6):
        return None
    scope = a.get("scope") or []
    if scope and not any(s in (action or "") for s in scope):
        return None
    if not consume:                       # peek(只查不记账): 执行层用它决定要不要干等慢层
        return a
    a["used"] = int(a.get("used") or 0) + 1
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=1)
        with open(os.path.expanduser("~/zmax_data/vl_operator_auth_log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "ts_str": time.strftime("%F %T"), "action": (action or "")[:160],
                                "by": a.get("by"), "note": a.get("note"), "use": a["used"],
                                "age_s": round(age, 1)}, ensure_ascii=False) + "\n")
    except Exception:                                                   # noqa: BLE001
        pass
    return a


# 🗣 被拦原因要能一句话说清 (2026-09-28 老倪: 「都不知道发出了没有」+「要在下面的终端反馈问题」):
#   旧文案"A 或 B(见日志)"界面读不出到底为什么 ⇒ 受理行现在原样带出**哪一层闸 + 为什么**。
_LAST_BLOCK: dict = {}


def _note_block(layer: str, why: str):
    """记下"最近一次被拦"的层与原因 (由 dispatch 的受理行带出去给界面底部终端)"""
    _LAST_BLOCK.clear()
    _LAST_BLOCK.update({"layer": layer, "why": str(why), "ts": time.time()})


def _block_msg() -> str:
    """给上层(界面/底部终端)看的一句话: 被谁拦的 + 为什么"""
    if _LAST_BLOCK and (time.time() - float(_LAST_BLOCK.get("ts") or 0)) < 60:
        return "🛑 被拦(%s): %s" % (_LAST_BLOCK.get("layer"), _LAST_BLOCK.get("why"))
    return "🛑 被拦: 命令通道不可用(自动重建后仍失败) — 看日志「🩹 命令通道」"


def _vl_gate_blocks(call: str) -> bool:
    """True = 拦住这条下发。"""
    c = call or ""
    if any(k in c for k in _VL_ALWAYS_ALLOW):
        return False
    _d_off, _w_off = _vl_disabled()
    if _d_off:
        log("🛡 VL 安全闸: **已关闭** ⇒ 本条直接放行 (%s)" % _w_off)
        return False

    def _slow_block(why: str) -> bool:
        """慢层不放行的收口: 先看有无**人工一次性授权**(带 TTL/次数/审计), 没有才拒发。"""
        act = c + " " + str(_INTENT.get("desc") or "")
        a = _vl_operator_auth(act)
        if a:
            log("⚠️ 人工一次性放行(**只越过慢层判断, 快层反射照旧**): %s | 授权人=%s · 用途=%s · 第%s/%s次 · TTL=%ss | 慢层原因: %s"
                % (c[:70], a.get("by"), a.get("note"), a.get("used"), a.get("max_uses"), a.get("ttl_s"), why))
            return False
        log(why)
        _note_block("慢层·VL 判断", why)
        return True

    try:
        d = json.loads(open(VL_VERDICT_PATH, encoding="utf-8").read())
    except Exception as e:                                              # noqa: BLE001
        return _slow_block("🛡 VL 安全闸: 无安全裁决文件(%s) ⇒ 从严**拒发**(fail-closed)" % str(e)[:70])
    age = time.time() - float(d.get("ts") or 0)
    if age > VL_FRESH_S:
        return _slow_block("🛡 VL 安全闸: 裁决过期 %.0fs > %.0fs (上次 %s) ⇒ 拒发; 确认 vl_safety_monitor 在跑"
                           % (age, VL_FRESH_S, d.get("ts_str")))
    if not d.get("safe"):
        hz = "; ".join(("%s@%s" % (h.get("what"), h.get("where")))[:70] for h in (d.get("hazards") or []))
        return _slow_block("🛡 VL 安全闸: **不安全**(risk=%s · %s 裁决): %s | 危害: %s ⇒ 拒发"
                           % (d.get("risk_level"), d.get("ts_str"), d.get("why"), hz or "-"))
    # ⚡ 快反射层(本地 5Hz 遮挡检测, 亚秒级): 必须存在 + 安全 + 新鲜, 否则一律拒发
    try:
        _fp = os.path.expanduser("~/zmax_data/vl_safety_fast.json")
        _fresh = float(os.environ.get("ZMAX_VL_FAST_FRESH_S", "4"))
        f = json.loads(open(_fp, encoding="utf-8").read())
        fage = time.time() - float(f.get("ts") or 0)
        if fage > _fresh:
            log("🛡 VL 安全闸(快层): 反射层裁决过期 %.1fs > %.0fs ⇒ 拒发; 确认 vl_safety_fast 在跑" % (fage, _fresh))
            _note_block("快层·本地反射(5Hz)", "反射层裁决过期 %.1fs > %.0fs ⇒ 拒发; 确认 vl_safety_fast 在跑" % (fage, _fresh))
            return True
        if not f.get("safe"):
            log("🛡 VL 安全闸(快层): **遮挡/糊化**(%s): %s ⇒ 拒发(本地检测, 亚秒级)"
                % (f.get("unsafe_cams"), f.get("why")))
            _note_block("快层·本地反射(5Hz)", "遮挡/糊化 %s: %s" % (f.get("unsafe_cams"), f.get("why")))
            return True
        log("🛡 VL 安全闸(快层): 放行 (裁决 %.1fs 前 · 纹理正常无遮挡)" % fage)
    except Exception as e:                                              # noqa: BLE001
        log("🛡 VL 安全闸(快层): 反射层裁决缺失(%s) ⇒ 从严拒发" % str(e)[:60])
        _note_block("快层·本地反射(5Hz)", "反射层裁决缺失(%s) ⇒ 从严拒发" % str(e)[:60])
        return True
    log("🛡 VL 安全闸: 放行 (risk=%s · 裁决 %.0fs 前 · %s)" % (d.get("risk_level"), age, d.get("image")))
    return False


def chan_send(call, intent_desc=None):
    """下发一条 ROS2 调用; 通道死了就重建并重试一次 (别让技能静默失效)。

    🛡 所有运动类下发在此**唯一收口**: 先过 VL 视觉安全闸(见上), 停机/复位白名单放行。
    🎯 带 intent_desc 时: 先把"这一步要做什么"告诉 VL, 再**等它针对该动作出裁决**, 等不到就拒发。
    """
    # 🩹 2026-09-27 老倪: 「技艺 合抓/松开 怎么不好使了」—— 根因: 夹爪类技能(ros=gripper, 无 steps)
    #   被当成"臂运动" ⇒ 走"告知VL+等针对该动作的裁决"分支 ⇒ 等不到就**挂住**;
    #   而执行器是单线程 ⇒ 挂住期间后续任何技能全部排队不动(表现为"点了没反应")。
    #   夹爪不属于臂运动(位置 Δ=0) ⇒ 免意图等待; 仍走下面的 VL 闸门(快层反射强制, fail-closed 不变)。
    _LAST_BLOCK.clear()          # 每条下发重新判定 —— 别把上一条的"被拦原因"带过来
    # 🔐 真动授权闸: 所有运动下发**唯一收口** ⇒ 授权也必须在这里强制(8793 手动控制台撤销 ⇒ 立刻失效)。
    #    老倪 2026-09-29: 「我都取消授权了，手臂怎么还在动；点1 技能也要服从手动控制台的授权」
    _a_ok, _a_why = _auth_guard(call, "运动")
    if not _a_ok:
        log("🛑 被拦(真动授权): %s | 本条=%s" % (_a_why, str(call)[:70]))
        _note_block("真动授权·8793 手动控制台", "%s | 本条=%s" % (_a_why, str(call)[:60]))
        return False
    _mark_dispatch(_CUR.get("skill") or str(call)[:40], "运动", str(call)[:100])
    _is_grip = bool(intent_desc) and ("gripper" in call or "L2.grip_" in call or "grip_open" in call or "grip_close" in call)
    if _is_grip:
        log("🎯 夹爪类动作 ⇒ 免意图等待(非臂运动), 仍过快层反射闸门: %s" % intent_desc)
    if intent_desc and not _is_grip:
        _seq = set_intent(intent_desc)
        _d_off, _w_off = _vl_disabled()
        if _d_off:
            # 🔓 安全闸关了(现场调试) ⇒ 不审议、不等待, 直接下发; 下面 _vl_gate_blocks 同样整体放行
            log("🎯 安全闸已关闭 ⇒ 不进入本轮审议, 直接下发: %s (%s)" % (intent_desc, _w_off))
        elif _vl_operator_auth(call + " " + intent_desc, consume=False):
            log("🎯 现场授权在场 ⇒ **不干等慢层裁决**, 直接交闸门(快层反射仍强制生效): %s" % intent_desc)
        else:
            _reuse, _rwhy = _vl_reuse_ok(intent_desc)
            if _reuse:
                # 🔁 同一动作 + 裁决新鲜(≤VL_REUSE_S) ⇒ 不重跑慢层, 直接交闸门(快层仍实测当下场景)
                log("🎯 %s | 本动作=%s ⇒ 不重跑慢层, 直接过闸(快层反射仍强制)" % (_rwhy, intent_desc))
            else:
                log("🎯 已把本次动作告知 VL: %s (等针对该动作的裁决, 上限 %.0fs · %s)"
                    % (intent_desc, VL_INTENT_WAIT_S, _rwhy))
                if not _vl_wait_intent(_seq, intent_desc):
                    # 未放行的两种可能: ①真动授权被撤(上面已单独记账) ②VL 慢层没在 %.0fs 内出裁决
                    if not _LAST_BLOCK:
                        log("🛡 VL 安全闸: %.0fs 内未等到针对本次动作的裁决 ⇒ 从严拒发(绝不拿旧/异动作裁决放行)"
                            % VL_INTENT_WAIT_S)
                        _note_block("慢层·VL 判断",
                                    "%.0fs 内未等到针对本次动作的裁决 ⇒ 从严拒发(裁决 seq=%s 未更新 · 复用也不行: %s)"
                                    % (VL_INTENT_WAIT_S, _seq, _rwhy))
                    return False
    if _vl_gate_blocks(call):
        return False
    for attempt in (1, 2):
        if not _chan_alive():
            log("🩹 命令通道不可用 → 重建 (%s)" % ("首次" if attempt == 1 else "重试"))
            _spawn_chan(force=True)
            time.sleep(1.0)
        try:
            _CHAN["p"].stdin.write(call + "\n")
            _CHAN["p"].stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError) as e:
            log("🩹 下发遇到 %s → 重建通道后重试" % type(e).__name__)
            _spawn_chan(force=True)
            time.sleep(1.5)
    return False


def chan_watchdog():
    """后台看门狗: 通道静默死掉(ssh 无输出退出/网络闪断)也能自愈。"""
    while True:
        time.sleep(15)
        if not _chan_alive():
            log("🩹 看门狗: 命令通道已死 → 自动重建")
            _spawn_chan(force=True)


def main():
    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO)
    reg = json.load(open(REG_PATH, encoding="utf-8"))
    threading.Thread(target=state_thread, daemon=True).start()
    # ① 等直连链路就绪 ② 一次性 ssh 探针确认真能登录 —— 否则通道"建完即死"变僵尸(2026-09-21 实况)
    if not _link_ready(120):
        log("⚠️ 直连链路 120s 未就绪, 仍尝试建通道(会由看门狗/下发时自愈)")
    for _i in range(1, 61):
        _ok, _out = _ssh_once("echo ZMAX_CHAN_PROBE_OK", timeout=12)
        if _ok and "ZMAX_CHAN_PROBE_OK" in _out:
            log("✅ ssh 探针通过 (第 %d 次尝试)" % _i)
            break
        if _i == 1:
            log("⏳ 等 Orin ssh 就绪中(最多 120s)...")
        time.sleep(2)
    else:
        log("⚠️ ssh 探针 120s 未通过 — 通道由看门狗/下发时重建")
    chan = _spawn_chan(force=True)
    threading.Thread(target=chan_watchdog, daemon=True).start()
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
                # 🔐 记下本条命令**签发时**的授权 epoch: 撤销会 +1 ⇒ 旧 epoch 的命令在执行层一律作废
                _CUR.update({"epoch": spec.get("auth_epoch"), "skill": spec.get("skill") or "", "t": time.time()})
                try:
                    log("受理: " + dispatch(reg, spec, chan))
                except Exception as e:
                    log("执行异常: %s" % e)


if __name__ == "__main__":
    main()
