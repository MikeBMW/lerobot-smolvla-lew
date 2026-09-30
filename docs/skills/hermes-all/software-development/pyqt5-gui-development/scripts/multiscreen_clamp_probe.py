#!/usr/bin/env python3
"""多屏 clamp 取证探针 — 真实窗口 + 真屏幕, 测「窗口被移到副屏后会不会被应用自己的 clamp 拽回」。

为什么需要 (2026-09-17 实测教训): 纯逻辑单测只证明 clamp 函数本身, 证不了
"真窗口 + 真定时节拍 + 真双屏" 下的行为; 而用户报的 "拖到扩展屏就自己跳回" 正是后者。

用法:
  # ① 对照组: 不调任何 clamp — 用来排除 WM/mutter (窗口停得住 = WM 无罪, 是应用代码)
  DISPLAY=:0 python multiscreen_clamp_probe.py --clamp none

  # ② 测被测实现 (真实窗口里按同样节拍调它的 clamp)
  DISPLAY=:0 python multiscreen_clamp_probe.py \
      --clamp-file /path/to/yolo_input_viewer.py --clamp-class YoloInputViewer \
      --method _clamp_to_screen --helpers _screens,_visible_ratio

  # ③ A/B 对照组: 老实现从 git 抠出来存成临时文件再跑同一台架 (同台架 old❌/new✅ 才算证据)
  git show HEAD:tools/gui/yolo_input_viewer.py > /tmp/old_viewer.py

关键选项: --x 2000 (移到副屏的 x) · --watch 14 (观察秒数) · --tick-ms 66 · --throttle 5.0 (clamp 节流秒)
          --expect keep|return (默认 keep = 期望停在副屏不被拽回)
退出码: 0 符合期望 · 1 不符合 · 2 环境问题 (无副屏 / 无 xdotool / 无 wmctrl)
"""
import argparse
import importlib.util
import inspect
import os
import re
import subprocess
import sys
import time

TITLE = "clamp probe %d" % os.getpid()


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clamp", default=None, help="'none' = 对照组 (不调 clamp)")
    ap.add_argument("--clamp-file", default=None, help="被测实现所在 .py 文件")
    ap.add_argument("--clamp-class", default=None, help="被测类名")
    ap.add_argument("--method", default="_clamp_to_screen", help="clamp 方法名")
    ap.add_argument("--helpers", default="_screens,_visible_ratio",
                    help="clamp 依赖的同名辅助方法 (逗号分隔, 可选)")
    ap.add_argument("--x", type=int, default=None, help="移动到副屏的 x (默认取第二块屏的 x)")
    ap.add_argument("--y", type=int, default=100)
    ap.add_argument("--watch", type=float, default=14.0, help="观察秒数")
    ap.add_argument("--tick-ms", type=int, default=66, help="刷新定时器间隔 (对齐被测应用的 _tick)")
    ap.add_argument("--throttle", type=float, default=5.0, help="clamp 调用节流秒数 (对齐被测应用)")
    ap.add_argument("--expect", choices=["keep", "return"], default="keep")
    ap.add_argument("--w", type=int, default=1200)
    ap.add_argument("--h", type=int, default=800)
    args = ap.parse_args()

    os.environ.setdefault("DISPLAY", ":0")
    from PyQt5 import QtCore, QtWidgets                     # noqa: E402

    app = QtWidgets.QApplication(sys.argv[:1])

    # ── 绑定被测实现 ───────────────────────────────────────────────────────
    class Probe(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(None, QtCore.Qt.Window)
            self.setWindowTitle(TITLE)
            self.resize(args.w, args.h)
            self.move(300, 100)
            self._last_clamp = 0.0
            self.t = QtCore.QTimer(self)
            self.t.setInterval(args.tick_ms)
            self.t.timeout.connect(self._tick)
            self.t.start()

        def _log_line(self, s):
            print("        [窗口日志] %s" % s, flush=True)

        def _tick(self):
            if time.time() - self._last_clamp > args.throttle:
                self._last_clamp = time.time()
                self.clamp(silent=False)

    if args.clamp == "none" or not args.clamp_file:
        print("模式: 对照组 (不调任何 clamp) — 只验证窗口能否停在副屏 (排除 WM/mutter)")
        Probe.clamp = lambda self, silent=True: False
    else:
        spec = importlib.util.spec_from_file_location("clamp_mod", args.clamp_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["clamp_mod"] = mod
        spec.loader.exec_module(mod)
        cls = getattr(mod, args.clamp_class)
        # ⚠️ 必须 getattr_static: 直接 setattr(Probe, name, cls.name) 会把 @staticmethod
        #    当实例方法绑定 self → TypeError 被被测代码的 except 吞掉 → 假 PASS
        fn = inspect.getattr_static(cls, args.method)
        print("被测: %s.%s @ %s:%d" % (args.clamp_class, args.method,
                                      inspect.getsourcefile(fn), fn.__code__.co_firstlineno))
        Probe.clamp = fn
        for hname in [h.strip() for h in args.helpers.split(",") if h.strip()]:
            if hasattr(cls, hname):
                setattr(Probe, hname, inspect.getattr_static(cls, hname))
                print("  绑定辅助方法: %s" % hname)

    screens = [(s.name(), s.availableGeometry()) for s in app.screens()]
    print("屏幕: %s" % [(n, (g.x(), g.y(), g.width(), g.height())) for n, g in screens])
    if len(screens) < 2 and args.x is None:
        print("❌ 只有一块屏 — 多屏测试需要接上副屏 (或显式 --x)")
        return 2
    secondary_x = args.x if args.x is not None else max(g.x() for _, g in screens)
    if secondary_x <= (min(g.x() for _, g in screens)):
        print("❌ 没算出副屏 x (副屏应在主屏右侧)")
        return 2
    for tool in ("xdotool", "wmctrl"):
        if sh(["which", tool]).returncode != 0:
            print("❌ 缺 %s (sudo apt-get install -y %s)" % (tool, tool))
            return 2

    win = Probe()
    win.show()
    app.processEvents()

    wid = ""
    for _ in range(20):
        app.processEvents()
        r = sh(["xdotool", "search", "--name", TITLE])
        if r.stdout.strip():
            wid = r.stdout.split()[-1]
            break
        time.sleep(0.3)
    if not wid:
        print("❌ 拿不到本窗口 id (xdotool)")
        return 2

    print("初始: x=%d y=%d %dx%d (窗口 id %s)" % (win.x(), win.y(), win.width(), win.height(), wid))
    print("→ wmctrl 移到副屏 x=%d …" % secondary_x)
    sh(["wmctrl", "-i", "-r", wid, "-e", "0,%d,%d,-1,-1" % (secondary_x, args.y)])

    t0 = time.time()
    samples = []
    while time.time() - t0 < args.watch:
        app.processEvents()
        samples.append((round(time.time() - t0, 1), win.x()))
        time.sleep(0.5)

    print("时间轴 (x):")
    for t, x in samples:
        print("   t=%4.1fs  x=%5d  %s" % (t, x, "副屏✅" if x >= secondary_x else "主屏⬅"))
    after = [x for t, x in samples if t >= 3.0]
    stayed = bool(after) and all(x >= secondary_x for x in after)
    got = "keep" if stayed else "return"
    print("\n观测结果: %s (期望 %s) → %s"
          % (got, args.expect, "✅ PASS" if got == args.expect else "❌ FAIL"))
    app.quit()
    return 0 if got == args.expect else 1


if __name__ == "__main__":
    sys.exit(main())
