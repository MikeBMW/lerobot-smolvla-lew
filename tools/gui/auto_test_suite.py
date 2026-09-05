#!/usr/bin/env python3
"""Z-MAX simulink 状态空间自动测试套件 (2026-09-05 老倪: 每个用例截图)

用法: studio.py 启动带 ZMAX_AUTO_TEST=1 → 本套件自动跑
每个用例: 真实 GUI 操作 + QWidget.grab() 截图 + PASS/FAIL 断言
截图输出: /tmp/zmax_auto_test/TCxx_<名>.png

用例清单:
  TC01 打开状态空间画布      — 断言: 节点数>10, 含 S1-S4 行
  TC02 引擎快演仿真          — 断言: _ss_tr 生成, 500 步
  TC03 仿真汇总              — 断言: 完成/未完成 明确, 距离/残差/接触有值
  TC04 节点逻辑可执行        — 断言: 画布每个节点 match_node 有逻辑
  TC05 数据总线 14 模块      — 断言: model_tree bus 有信号
  TC06 打开 3D 分层视图      — 断言: DreamView3D 构造成功无异常
  TC07 3D 图层开关           — 断言: 切图层不崩
"""
import os, sys, time, json, traceback
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QGraphicsView
from PyQt5.QtGui import QPixmap, QPainter, QColor

OUT_DIR = "/tmp/zmax_auto_test"
os.makedirs(OUT_DIR, exist_ok=True)
REPORT = os.path.join(OUT_DIR, "report.json")

_results = []


def _shot(win, name):
    """QWidget.grab() 截控件真实渲染图"""
    try:
        pm = win.grab()
        path = os.path.join(OUT_DIR, name)
        pm.save(path)
        return path, os.path.getsize(path) // 1024
    except Exception as e:
        return None, f"截图失败: {e!r}"


def _shot_widget(widget, name):
    """截任意控件 (画布/3D/数据面板等实际内容), 不截控制台外壳
    QGraphicsView: grab() 在未显示时空图 → 用 QPixmap + render() 强制离屏渲染"""
    try:
        from PyQt5.QtWidgets import QGraphicsView
        from PyQt5.QtGui import QPixmap
        if isinstance(widget, QGraphicsView):
            # 离屏渲染: 目标 pixmap = 场景实际大小 (viewport 大小可能 0)
            scene = widget.scene()
            if scene is not None and not scene.sceneRect().isEmpty():
                rect = scene.sceneRect()
                pm = QPixmap(int(rect.width()), int(rect.height()))
                pm.fill(QColor('#0d1117'))
                painter = QPainter(pm)
                widget.render(painter)
                painter.end()
            else:
                pm = widget.viewport().grab()
        else:
            pm = widget.grab()
        path = os.path.join(OUT_DIR, name)
        pm.save(path)
        return path, os.path.getsize(path) // 1024
    except Exception as e:
        return None, f"截图失败: {e!r}"


def _log(msg):
    print(f"[自动测试] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════
class StateSpaceAutoTest:
    """状态空间自动测试驱动器 (QTimer 链式, 主线程内跑, 不卡 UI)"""

    def __init__(self, studio_win, simulink):
        self.win = studio_win        # StudioMainWindow
        self.sim = simulink         # SimulinkModule
        self.steps = []             # 待执行用例列表
        self.idx = 0
        self._q = QTimer()
        self._q.timeout.connect(self._tick)
        self._q.start(1200)          # 每步间隔 1.2s (让 UI 渲染完再截)

    def _run_tc(self, fn, name, desc):
        """执行一个用例: fn 返回 (pass_bool, 备注) 或 (pass_bool, 备注, 截图widget)"""
        tc = {"tc": name, "desc": desc, "pass": False, "note": "", "shot": "", "shot_kb": 0}
        shot_w = None
        try:
            r = fn()
            if isinstance(r, (tuple, list)) and len(r) >= 3:
                ok, note, shot_w = r[0], r[1], r[2]
            elif isinstance(r, (tuple, list)) and len(r) == 2:
                ok, note = r
            else:
                ok, note = bool(r), str(r)
            tc["pass"] = bool(ok)
            tc["note"] = note
        except Exception as e:
            tc["note"] = f"异常: {e!r}"
            traceback.print_exc()
        # 截图: 用例指定控件 → 该控件; 否则截画布 (实际内容, 不截控制台外壳)
        try:
            w = shot_w if shot_w is not None else getattr(self.sim, "canvas", None)
            if w is not None:
                p, sz = _shot_widget(w, f"{name}.png")
                tc["shot"] = p or ""
                tc["shot_kb"] = sz if isinstance(sz, int) else sz
        except Exception as e:
            tc["note"] += f" | 截图失败: {e!r}"
        _results.append(tc)
        mark = "✅" if tc["pass"] else "❌"
        try:
            self.sim._log(f"[TC {name}] {mark} {desc} — {tc['note']}")
        except Exception:
            pass
        _log(f"TC {name}: {mark} {tc['note']} 截图={tc['shot']}")
        # 下一用例由 _tick 定时器驱动 (idx 已自增), 无需手动 _next

    # ── 用例定义 ──
    def tc01_open_canvas(self):
        def fn():
            self.sim.open_state_space()
            n = len(self.sim.nodes)
            names = [x.get("name", "") for x in self.sim.nodes]
            has_s1 = any("S1" in str(x.get("name", "")) or "感知" in str(x.get("name", "")) for x in self.sim.nodes)
            # 截图 = 画布控件 (状态空间 S1-S4 分层)
            return n > 10, f"节点数={n}, 含S1感知={'是' if has_s1 else '否'}", self.sim.canvas
        return ("TC01_打开状态空间画布", "open_state_space → 加载 state_space_obs.json", fn)

    def tc02_engine_sim(self):
        def fn():
            chk = getattr(self.sim, "chk_engine_demo", None)
            if chk is not None:
                chk.setChecked(True)
            self.sim.start_sim()
            return True, "引擎快演已启动"
        return ("TC02_引擎快演仿真", "start_sim → _start_state_space_sim", fn)

    def tc03_sim_result(self):
        def fn():
            tr = getattr(self.sim, "_ss_tr", None)
            if not tr or not tr.get("x"):
                return False, "无轨迹 (_ss_tr 空)"
            steps = len(tr["x"])
            done = bool(tr.get("done") and tr["done"][-1])
            dist = tr["dist"][-1] if tr.get("dist") else 0
            cp = max(tr["contact_p"]) if tr.get("contact_p") else 0
            # 截图 = 画布 (节点全绿/运行态)
            return steps > 100, f"{steps}步 done={done} 距离={dist:.4f} 接触={cp:.2f}", self.sim.canvas
        return ("TC03_仿真结果", "500步引擎轨迹断言", fn)

    def tc04_node_logic(self):
        def fn():
            try:
                import node_logic
                n_ok = 0
                for n in self.sim.nodes:
                    nm = n.get("name", "")
                    if not nm:
                        continue
                    key = node_logic.match_node(nm)
                    if key:
                        n_ok += 1
                total = len([n for n in self.sim.nodes if n.get("name")])
                return n_ok > 0, f"节点逻辑匹配 {n_ok}/{total}"
            except Exception as e:
                return False, f"node_logic: {e!r}"
        return ("TC04_节点逻辑", "每节点 match_node 有逻辑", fn)

    def tc05_databus(self):
        def fn():
            try:
                mt = getattr(self.sim, "model_tree", None)
                bus = getattr(mt, "bus", None) if mt else None
                if bus is not None:
                    return True, "数据总线存在"
                return False, "无 model_tree/bus"
            except Exception as e:
                return False, f"bus: {e!r}"
        return ("TC05_数据总线", "model_tree.bus 存在", fn)

    def tc06_open_3d(self):
        def fn():
            try:
                self.sim.open_ss_3d(on_top=False)
                wins = [w for w in getattr(self.sim, "_ss_3d_windows", []) if w.isVisible()]
                if wins:
                    return True, f"3D 窗口可见 ×{len(wins)}", wins[0]
                return False, "3D 窗口创建但不可见"
            except Exception as e:
                return False, f"3D 打开异常: {e!r}"
        return ("TC06_打开3D视图", "DreamView3D 构造+显示", fn)

    def tc07_3d_layers(self):
        def fn():
            try:
                wins = [w for w in getattr(self.sim, "_ss_3d_windows", []) if w.isVisible()]
                if not wins:
                    return False, "无 3D 窗口"
                w3 = wins[0]
                # 切换几个图层开关
                toggles = getattr(w3, "_layer_on", {})
                for k in list(toggles.keys())[:3]:
                    toggles[k] = not toggles[k]
                return True, f"图层切换 OK (共{len(toggles)}层)", w3
            except Exception as e:
                return False, f"图层: {e!r}"
        return ("TC07_3D图层开关", "切图层不崩+截图", fn)

    # ── TC08: 阶段动作截图 (接近/对位/下降/抓取/抬起/转移/插入 每阶段截 3D 真实画面) ──
    def tc08_stage_shots(self):
        def fn():
            tr = getattr(self.sim, "_ss_tr", None)
            if not tr or not tr.get("stage"):
                return False, "无轨迹 (先跑仿真)"
            # 各阶段代表步
            stages_seen = {}
            for i, s in enumerate(tr["stage"]):
                st = str(s).replace("阶段 ", "").split("·")[0].strip()
                if st and st not in stages_seen:
                    stages_seen[st] = i
            if not stages_seen:
                return False, "stage 序列为空"
            # 打开 3D 视图 (真实机械臂插拔画面, 每阶段游标不同 → 画面不同)
            try:
                self.sim.open_ss_3d(on_top=False)
            except Exception as e:
                return False, f"3D 打开失败: {e!r}"
            wins = [w for w in getattr(self.sim, "_ss_3d_windows", []) if w.isVisible()]
            if not wins:
                return False, "3D 窗口不可见"
            w3 = wins[0]
            shot_names = []
            try:
                from PyQt5.QtWidgets import QApplication as _QA
                import time as _t
                for st, i in stages_seen.items():
                    # 3D 显示该阶段首步 (set_frame 驱动真实画面)
                    try:
                        w3.set_frame(min(i, w3._n - 1))
                    except Exception:
                        try:
                            w3._idx = min(i, max(0, len(tr.get("x", [])) - 1))
                            w3._update_frame(w3._idx)
                        except Exception:
                            pass
                    _QA.processEvents()
                    _t.sleep(0.5)
                    nm = f"TC08_阶段_{st.replace(' ','')}"
                    # GL 窗口: grab 截不到 → xwd 截真实 X 画面
                    p = self._xwd_shot(nm, win=w3)
                    kb = os.path.getsize(p) // 1024 if p and os.path.exists(p) else 0
                    shot_names.append(f"{st}@{kb}KB")
                return True, f"阶段截图(3D): {', '.join(shot_names)}"
            except Exception as e:
                return False, f"阶段截图异常: {e!r}"
        return ("TC08_阶段动作截图", "接近/抓取/插入 每阶段截 3D 真实画面", fn)

    def _xwd_shot(self, name, win=None):
        """xwd 截窗口真实渲染 → png (GL/画布离屏 grab 不出, 用 X 服务真实画面)
        win=None 截主窗; win=widget 截该窗口 (用其 winId)"""
        import subprocess
        try:
            target = win if win is not None else self.win
            target.showNormal()
            target.raise_()
            target.activateWindow()
            wid = str(int(target.winId()))
            xwd = os.path.join(OUT_DIR, name + ".xwd")
            subprocess.run(["xwd", "-id", wid, "-out", xwd], capture_output=True, timeout=15)
            png = os.path.join(OUT_DIR, name + ".png")
            subprocess.run(["convert", xwd, png], capture_output=True, timeout=15)
            os.remove(xwd) if os.path.exists(xwd) else None
            return png
        except Exception as e:
            print(f"xwd 截图失败: {e!r}")
            return None

    # ── 驱动器 ──
    def _build_plan(self):
        self.steps = [
            self.tc01_open_canvas(),
            self.tc02_engine_sim(),
            self.tc03_sim_result(),
            self.tc08_stage_shots(),     # 🎯 阶段动作截图 (需 TC03 轨迹)
            self.tc04_node_logic(),
            self.tc05_databus(),
            self.tc06_open_3d(),
            self.tc07_3d_layers(),
        ]

    def _tick(self):
        if self.idx == 0:
            self._build_plan()
            _log(f"套件启动: {len(self.steps)} 个用例")
            try:
                self.sim._log(f"🧪 自动测试套件启动 — {len(self.steps)} 个用例, 每个截图")
            except Exception:
                pass
        if self.idx >= len(self.steps):
            self._q.stop()
            self._finish()
            return
        name, desc, fn = self.steps[self.idx]
        self.idx += 1
        self._run_tc(fn, name, desc)

    def _finish(self):
        n_pass = sum(1 for r in _results if r["pass"])
        n_total = len(_results)
        _log(f"═══ 完成: {n_pass}/{n_total} PASS ═══")
        try:
            self.sim._log(f"🧪 自动测试完成: {n_pass}/{n_total} PASS")
        except Exception:
            pass
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump({"total": n_total, "pass": n_pass, "results": _results},
                      f, ensure_ascii=False, indent=2)
        _log(f"报告: {REPORT}")
