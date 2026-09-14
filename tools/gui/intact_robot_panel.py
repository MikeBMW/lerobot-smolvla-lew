# -*- coding: utf-8 -*-
"""🤖 INTACT 标准机器人切换面板 (数据源层 UI)

设计 (老倪 2026-09-12 需求: "在状态空间中增加一个符合 INTACT 标准的机器人; 在数据源层增加
机器人切换节点; 你来设计切换 UI"):

  三层结构
    ① 注册表 (后端): tools/intact_native_robot.py 里的 ROBOTS = 4 个 INTACT **原生标准**机器人
       (reacher / pusht / cube / tworoom) —— 原项目权重 + 原项目环境 + zero-search direct。
       每个都带: 环境名 / 类型 / 动作空间 / 官方成绩 / 数据集是否就位 / 权重是否就位 / 视频数。
    ② 切换节点 (状态层): 当前选中的机器人写到 data/intact_robot_state.json ——
       下游数据源节点 (画布上的「🤖 INTACT机器人」/「🔀 机器人切换」节点) 读这个文件决定用谁。
    ③ 本面板 (UI): 表格看全部机器人 → 一键「切换为当前」→ 「跑一轮」后台出官方渲染视频 → 播放。

诚实标注: 这里全是**原项目原生**能力 (零搜索, 无候选搜索); 我们域内微调的 Sawyer 插拔
**不在**这张表里 (它是另一条线, 由 INTACT 域内微调 v2 提供)。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
                             QWidget)

TOOLS = os.path.dirname(os.path.abspath(__file__))        # tools/gui
ROOT = os.path.dirname(os.path.dirname(TOOLS))            # 仓库根 (tools/gui → tools → root)
INTACT_PY = "/home/ubuntu/INTACT-JEPA/.venv/bin/python"
BACKEND = os.path.join(ROOT, "tools", "intact_native_robot.py")
STATE_FILE = os.path.join(ROOT, "data", "intact_robot_state.json")
VID_DIR = os.path.join(ROOT, "reports", "intact_native")

try:
    from studio import C_BG, C_BG2, C_CARD, C_BLUE, C_GREEN, C_WHITE, C_DIM, C_BORDER, C_RED, C_YELLOW
except Exception:
    C_BG, C_BG2, C_CARD = "#0d1117", "#161b22", "#1c2333"
    C_BLUE, C_GREEN, C_WHITE, C_DIM, C_BORDER, C_RED, C_YELLOW = (
        "#58a6ff", "#3fb950", "#e6edf3", "#484f58", "#30363d", "#f85149", "#e3b341")


class _Runner(QThread):
    """后台跑「原项目权重 + 原项目环境」的一轮 rollout (不卡 UI)。"""
    line = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, robot, episodes):
        super().__init__()
        self.robot, self.episodes = robot, episodes

    def run(self):
        env = dict(os.environ)
        env.update({"STABLEWM_HOME": env.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
                    "LOCAL_DATASET_DIR": env.get("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")})
        try:
            p = subprocess.run([INTACT_PY, BACKEND, "--run", "--robot", self.robot,
                                "--episodes", str(self.episodes), "--video-dir", VID_DIR],
                               capture_output=True, text=True, env=env, timeout=3600)
            out = (p.stdout or "").strip().splitlines()
            res = {}
            for ln in out:
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                if d.get("stage") == "start":
                    self.line.emit(f"▶️ 启动: {d.get('robot')} · {d.get('env')} · 权重 {d.get('ckpt')}")
                elif d.get("stage") == "done":
                    res = d
                    self.line.emit(f"✅ 完成: 成功率 {d.get('success_rate')} · 视频 {len(d.get('videos') or [])} 段")
            self.done.emit(res or {"ok": False, "tail": out[-6:]})
        except Exception as e:
            self.done.emit({"ok": False, "error": f"{type(e).__name__}: {e}"})


class IntactRobotPanel(QDialog):
    """INTACT 标准机器人切换面板 (数据源层)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🤖 INTACT 标准机器人 · 切换 (数据源层)")
        self.resize(1060, 720)
        self.setMinimumSize(860, 600)
        self.setStyleSheet(f"QDialog{{background:{C_BG}; border:2px solid {C_BLUE};}}")
        self._rows = []
        self._task = None
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 12, 14, 12)

        # ① 当前机器人 banner (切换节点的"当前值")
        self.lbl_cur = QLabel()
        self.lbl_cur.setTextFormat(Qt.RichText)
        self.lbl_cur.setFont(QFont("Arial", 11))
        self.lbl_cur.setStyleSheet(f"background:{C_CARD}; border:1px solid {C_GREEN}66;"
                                   f" border-radius:8px; padding:10px; color:{C_WHITE};")
        lay.addWidget(self.lbl_cur)

        # ② 机器人表格 (注册表)
        head = QHBoxLayout()
        t = QLabel("INTACT 原生机器人注册表 (原项目权重 · 零搜索 direct)")
        t.setFont(QFont("Arial", 12, QFont.Bold))
        t.setStyleSheet(f"color:{C_BLUE}; background:transparent;")
        head.addWidget(t)
        head.addStretch()
        for txt, tip, fn in (("🔄 刷新注册表", "重扫数据集/权重/视频就位情况", self.refresh),
                             ("✅ 切换为当前", "写 data/intact_robot_state.json (切换节点读它)", self.switch_to_current),
                             ("▶️ 跑一轮出视频", "用原项目权重在该机器人原生环境跑 rollout", self.run_rollout),
                             ("🎬 播放最近视频", "打开最近一次 rollout 的视频", self.play_video),
                             ("📂 视频目录", "打开视频所在目录", self.open_vid_dir)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                            f" border-radius:4px; padding:6px 12px;")
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["机器人", "原生环境", "类型", "动作空间", "官方成绩", "数据集", "权重", "视频"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setStyleSheet(f"""
            QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER}; }}
            QTableWidget::item {{ padding:4px 6px; }}
            QTableWidget::item:selected {{ background:{C_BLUE}44; }}
            QHeaderView::section {{ background:{C_BG2}; color:{C_BLUE}; border:1px solid {C_BORDER}; padding:5px; font-weight:bold; }}
        """)
        self.table.doubleClicked.connect(lambda *_: self.switch_to_current())
        lay.addWidget(self.table, 3)

        # ③ 日志 + 说明
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setStyleSheet(f"background:{C_BG2}; color:{C_DIM};"
                               f" border:1px solid {C_BORDER}; border-radius:6px; font-family:Consolas; font-size:11px;")
        lay.addWidget(self.log)
        note = QLabel("说明: 本表机器人 = 原项目论文权重在**其原生环境**里零搜索直接驱动 (get_cost_calls=0)。"
                      "切换后写 data/intact_robot_state.json —— 画布数据源层的「🔀 机器人切换」节点读它决定下游用哪个机器人。"
                      "我们域内微调的 Sawyer 插拔不在此表 (走 INTACT 域内微调 v2)。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C_DIM}; background:transparent; font-size:11px;")
        lay.addWidget(note)

        self.refresh()

    # ── 数据 ──
    def refresh(self):
        try:
            p = subprocess.run([INTACT_PY, BACKEND, "--list"], capture_output=True, text=True,
                               env=dict(os.environ), timeout=180)
            d = json.loads((p.stdout or "{}").strip().splitlines()[-1])
        except Exception as e:
            self.log.append(f"❌ 注册表读取失败: {type(e).__name__}: {e}")
            return
        self._rows = d.get("robots", [])
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            cells = [r["name"], r["env"], r["kind"], r["action"], r.get("official", "?"),
                     "✅" if r.get("dataset_ready") else "❌缺", "✅" if r.get("ckpt_ready") else "❌缺",
                     str(r.get("videos", 0))]
            for j, v in enumerate(cells):
                it = QTableWidgetItem(str(v))
                if j in (5, 6) and "❌" in str(v):
                    it.setForeground(Qt.red)
                self.table.setItem(i, j, it)
        self._show_current()
        self.log.append(f"[注册表] {len(self._rows)} 个 INTACT 原生机器人 · "
                        f"可跑 {sum(1 for r in self._rows if r.get('runnable'))} 个 (数据集+权重齐)")

    def _show_current(self):
        cur = {}
        try:
            cur = json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
        rb = cur.get("robot")
        if rb:
            m = cur.get("meta", {})
            self.lbl_cur.setText(f"当前机器人 (切换节点输出): <b>{rb}</b> · {m.get('kind', '')} · "
                                 f"环境 {m.get('env', '')} · 权重 {m.get('ckpt', '')}<br>"
                                 f"<font color='{C_DIM}' size='2'>设置时间 {cur.get('ts')} · "
                                 f"状态文件 {STATE_FILE}</font>")
        else:
            self.lbl_cur.setText(f"当前机器人: <font color='{C_YELLOW}'>未选择</font> "
                                 f"<font color='{C_DIM}'>(选中表格一行 → 点「✅ 切换为当前」)</font>")

    def _selected(self):
        if not self.table.selectionModel() or not self.table.selectionModel().selectedRows():
            return None
        i = self.table.selectionModel().selectedRows()[0].row()
        return self._rows[i] if 0 <= i < len(self._rows) else None

    # ── 动作 ──
    def switch_to_current(self):
        r = self._selected()
        if not r:
            self.log.append("⚠️ 先选一个机器人")
            return
        try:
            p = subprocess.run([INTACT_PY, BACKEND, "--set-current", r["name"]],
                               capture_output=True, text=True, env=dict(os.environ), timeout=60)
            ok = json.loads((p.stdout or "{}").strip().splitlines()[-1]).get("ok")
            self.log.append(("✅ 已切换" if ok else "❌ 切换失败") + f": {r['name']} → {STATE_FILE}")
        except Exception as e:
            self.log.append(f"❌ 切换异常: {type(e).__name__}: {e}")
        self._show_current()
        # 🤖 选完机器人 = 立刻可以在画布上"运行 INTACT 项目": 打开该机器人的实况窗
        #   (老倪 2026-09-12: "选择 reacher 后, 既可以运行 INTACT 项目")
        try:
            win = LiveViewWindow(r["name"], self)
            win.setAttribute(Qt.WA_DeleteOnClose, True)
            win.show()
            self._live_win = win
            self.log.append(f"🖥 实况窗已打开: {r['name']} (点「▶️ 跑一轮」= 原项目权重在该环境外推)")
        except Exception as e:
            self.log.append(f"❌ 实况窗打开失败: {type(e).__name__}: {e}")

    def run_rollout(self):
        r = self._selected()
        if not r:
            self.log.append("⚠️ 先选一个机器人")
            return
        if not r.get("runnable"):
            self.log.append(f"❌ {r['name']} 数据或权重未就位 (数据集 {r.get('dataset_ready')} / "
                            f"权重 {r.get('ckpt_ready')}) → 先补数据再跑")
            return
        if self._task is not None and self._task.isRunning():
            self.log.append("⚠️ 已有一轮在跑, 等它结束")
            return
        self.log.append(f"▶️ 跑一轮: {r['name']} (原项目权重 · 零搜索) — 后台执行")
        self._task = _Runner(r["name"], 2)
        self._task.line.connect(lambda s: self.log.append(s))
        self._task.done.connect(self._on_rollout_done)
        self._task.start()

    def _on_rollout_done(self, res):
        if res.get("ok"):
            self.log.append(f"✅ {res.get('robot')} 成功率={res.get('success_rate')} · "
                            f"视频 {len(res.get('videos') or [])} 段 → {VID_DIR}")
            self._last_video = (res.get("videos") or [None])[0]
        else:
            self.log.append(f"❌ rollout 失败 rc={res.get('rc')} · {res.get('error', '')}")
            for ln in (res.get("tail") or [])[-3:]:
                self.log.append("   " + str(ln)[:160])
        self.refresh()

    def _latest_video(self):
        if getattr(self, "_last_video", None) and os.path.isfile(self._last_video):
            return self._last_video
        if not os.path.isdir(VID_DIR):
            return None
        fs = [os.path.join(VID_DIR, f) for f in os.listdir(VID_DIR) if f.endswith(".mp4")]
        return max(fs, key=os.path.getmtime) if fs else None

    def play_video(self):
        v = self._latest_video()
        if not v:
            self.log.append("⚠️ 还没有视频 (先「▶️ 跑一轮出视频」)")
            return
        try:
            from dataset_viewer import DatasetViewer   # 复用控制台的视频播放器? 目录里没有 → 系统播放器
            subprocess.Popen(["xdg-open", v], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log.append(f"🎬 播放: {v}")
        except Exception as e:
            self.log.append(f"❌ 播放失败: {e}")

    def open_vid_dir(self):
        os.makedirs(VID_DIR, exist_ok=True)
        subprocess.Popen(["xdg-open", VID_DIR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log.append(f"📂 {VID_DIR}")


class LiveViewWindow(QDialog):
    """🖥 INTACT 机器人实况窗 (画布可视化节点用)

    数据源优先级 (全部真实, 无帧就明说, 不拿假图充数):
      ① /tmp/intact_live_<robot>.jpg  — 常驻 worker 正在外推时的**实时帧** (有则最新优先)
      ② reports/intact_native/<robot>_*.mp4  — 本面板「▶️跑一轮」刚产出的 rollout 视频
      ③ reports/intact_official/<robot>/env_*.mp4 — 官方评测视频 (历史证据)
    顶部状态条显示: 机器人/环境/权重/步数/成功率/帧std (真图判据 >5)。
    """

    def __init__(self, robot: str = "", parent=None):
        super().__init__(parent)
        self.robot = robot or (read_state().get("robot") or "tworoom")
        self.setWindowTitle(f"🖥 INTACT 机器人实况 — {self.robot}")
        self.resize(900, 760)
        self.setStyleSheet(f"QDialog{{background:{C_BG}; border:2px solid {C_BLUE};}}")
        self._frames = []
        self._i = 0
        self._playing = True
        self._src = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)

        self.lbl_stat = QLabel()
        self.lbl_stat.setTextFormat(Qt.RichText)
        self.lbl_stat.setStyleSheet(f"background:{C_CARD}; border:1px solid {C_GREEN}66; border-radius:8px;"
                                    f" padding:8px; color:{C_WHITE};")
        lay.addWidget(self.lbl_stat)

        bar = QHBoxLayout()
        for txt, fn in (("▶️ 跑一轮 (原项目权重)", self.run_round),
                        ("⏸/▶️ 播放/暂停", self.toggle_play),
                        ("🔄 载入最新视频/实时帧", self.reload),
                        ("📂 视频目录", self.open_dir)):
            b = QPushButton(txt)
            b.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                            f" border-radius:4px; padding:6px 12px;")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)

        self.lbl_img = QLabel("(等待帧…)")
        self.lbl_img.setMinimumSize(600, 480)
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setStyleSheet(f"background:#000; color:{C_DIM}; border:1px solid {C_BORDER};")
        lay.addWidget(self.lbl_img, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        self.log.setStyleSheet(f"background:{C_BG2}; color:{C_DIM}; border:1px solid {C_BORDER};"
                               f" border-radius:6px; font-family:Consolas; font-size:11px;")
        lay.addWidget(self.log)

        from PyQt5.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / 10))          # 10fps = 原项目控制频率
        self._task = None
        self.reload()

    # ── 数据源 ──
    def _sources(self):
        out = []
        live = f"/tmp/intact_live_{self.robot}.jpg"
        if os.path.isfile(live):
            out.append(("live", live))
        for pat, tag in ((os.path.join(VID_DIR, f"{self.robot}_*.mp4"), "本面板 rollout"),
                         (os.path.join(ROOT, "reports", "intact_official", self.robot), "官方评测")):
            if pat.endswith(".mp4") or "*.mp4" in pat:
                fs = [p for p in __import__("glob").glob(pat)]
            else:
                fs = [os.path.join(pat, f) for f in os.listdir(pat)] if os.path.isdir(pat) else []
                fs = [f for f in fs if f.endswith(".mp4")]
            if fs:
                out.append((tag, max(fs, key=os.path.getmtime)))
        return out

    def reload(self):
        src = self._sources()
        if not src:
            self.log.append(f"⚠️ {self.robot}: 还没有视频 —— 先点「▶️ 跑一轮」")
            self._frames, self._i = [], 0
            return
        tag, path = src[0]
        if path == self._src:
            return
        import cv2
        cap = cv2.VideoCapture(path)
        fr = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            fr.append(f)
        cap.release()
        self._frames, self._i, self._src = fr, 0, path
        self.log.append(f"📼 载入 {tag}: {os.path.basename(path)} ({len(fr)} 帧)")

    # ── 播放 ──
    def _tick(self):
        st = {}
        try:
            st = json.load(open(f"/tmp/intact_live_{self.robot}.json", encoding="utf-8"))
        except Exception:
            pass
        self.lbl_stat.setText(
            f"🤖 <b>{self.robot}</b> · {st.get('env', ROBOT_ENV.get(self.robot, ''))} · "
            f"权重 {st.get('ckpt', ROBOT_CKPT.get(self.robot, ''))}<br>"
            f"<font color='{C_DIM}' size='2'>步 {st.get('step', '—')} · 成功率 {st.get('success_rate', '—')} · "
            f"动作 {st.get('action', '—')} · 帧std {st.get('frame_std', '—')} "
            f"{'(实时帧)' if st.get('ok') else '(播放录制)'}</font>")
        if not self._frames or not self._playing:
            return
        import cv2
        f = self._frames[self._i % len(self._frames)]
        self._i += 1
        rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        from PyQt5.QtGui import QImage, QPixmap
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        self.lbl_img.setPixmap(QPixmap.fromImage(img).scaled(
            self.lbl_img.width() - 6, self.lbl_img.height() - 6, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def toggle_play(self):
        self._playing = not self._playing
        self.log.append("▶️ 继续播放" if self._playing else "⏸ 暂停")

    def run_round(self):
        if self._task is not None and self._task.isRunning():
            self.log.append("⚠️ 已有一轮在跑")
            return
        self.log.append(f"▶️ 原项目权重跑一轮: {self.robot}")
        self._task = _Runner(self.robot, 2)
        self._task.line.connect(lambda s: self.log.append(s))
        self._task.done.connect(lambda res: (self.log.append(f"完成: {res.get('ok')} 成功率={res.get('success_rate')}"),
                                            self.reload()))
        self._task.start()

    def open_dir(self):
        os.makedirs(VID_DIR, exist_ok=True)
        subprocess.Popen(["xdg-open", VID_DIR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log.append(f"📂 {VID_DIR}")


ROBOT_ENV = {"reacher": "swm/ReacherDMControl-v0", "pusht": "swm/PushT-v1",
             "cube": "OGBench cube-single", "tworoom": "OGBench tworoom"}
ROBOT_CKPT = {k: f"recovery_delta_full_{k}_s3072" for k in ROBOT_ENV}


if __name__ == "__main__":                       # 单独调试: QT_QPA_PLATFORM=offscreen python ...
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = IntactRobotPanel()
    d.show()
    sys.exit(app.exec_())
