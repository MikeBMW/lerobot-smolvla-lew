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
        name = spec.get("point", sk["param"]["point"].get("default", "home"))
        if name not in pts:
            return None
        t = list(pts[name]["pos"])
        # 2026-09-20 老倪: "回到能看清光模块的位姿" = 位置+姿态都要回到示教点。
        # 默认沿用旧行为(位置用示教点 · 姿态保持当前), 技能上标 "quat":"taught" 才恢复示教姿态
        # —— 不改既有 goto_point/home 的行为(避免给老技能加姿态旋转风险)。
        if str(sk.get("quat", "")).lower() == "taught" and pts[name].get("quat"):
            q = list(pts[name]["quat"])
    return (t, q)


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
        pts = {}
        for _pf in ("data/skills/l2_muscle/光模块_抓放_演示学习_v1.json",
                    "data/skills/l2_atomic/taught_points.json"):
            try:
                with open(os.path.join(REPO, _pf), encoding="utf-8") as _f:
                    pts.update(json.load(_f).get("points", {}))
            except Exception as _e:                                          # noqa: BLE001
                log("点位库 %s 读取失败(跳过): %s" % (_pf, _e))
        r = build_move(sk, spec, pts)
        if not r:
            log("拒绝: 位姿缓存未就绪或点位不存在")
            return "位姿缓存未就绪"
        (x, y, z), (qx, qy, qz, qw) = r[0], r[1]
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
    log("已下发 %s -> %s" % (sid, (spec.get("d_mm", spec.get("force", spec.get("point", ""))))))
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
                try:
                    log("受理: " + dispatch(reg, spec, chan))
                except Exception as e:
                    log("执行异常: %s" % e)


if __name__ == "__main__":
    main()
