# -*- coding: utf-8 -*-
"""verification_dialog.py — 🧩 验证层 Feature/Test 节点 UI (2026-09-04 老倪)

画布两个节点:
  🧩 Feature 功能清单 → 本对话框 (清单 + 分类 + 导出 Excel)
  🧪 Test 用例执行    → 本对话框 (跑套件 + 结果 + 导出 Excel)

真源: src/lerobot/verification/verification_layer.py (FEATURES/FEATURE_META/t_F_*)
双击节点 = 打开本对话框 (非模态, _show_nonmodal), 不再只是打印日志。

功能 (老倪 2026-09-04):
  1. function list 区分基本功能/泛化功能 + 感知模型/世界模型标注 + 模型特点
  2. 按钮导出 Excel (清单 sheet + 结果 sheet, scp 上传 datadrive.world)
"""
import os
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QHeaderView, QAbstractItemView, QMessageBox)

_DARK = ("QDialog { background:#0d1117; color:#e6edf3; } "
         "QLabel { color:#e6edf3; } "
         "QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; "
         "gridline-color:#30363d; } "
         "QHeaderView::section { background:#21262d; color:#e6edf3; border:none; padding:4px; } "
         "QPushButton { background:#1f6feb; color:#fff; border:none; border-radius:5px; "
         "padding:8px 16px; font-size:13px; } "
         "QPushButton:hover { background:#388bfd; } "
         "QPushButton#b_export { background:#238636; } "
         "QPushButton#b_close { background:#30363d; }")

_SS = ("QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; "
       "gridline-color:#30363d; }")

_ESC = os.environ.get("ZMAX_VERIF_REPO")  # 可被测试注入 repo 根


def _repo_root():
    if _ESC:
        return _ESC
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "src", "lerobot")) and \
                os.path.isdir(os.path.join(d, "tools", "gui")):
            return d
        d = os.path.dirname(d)
    return d


def _verif_module():
    """加载验证层真源模块 (importlib 直载, 同 node_logic 策略)"""
    import importlib.util as _ilu
    path = os.path.join(_repo_root(), "src", "lerobot", "verification", "verification_layer.py")
    spec = _ilu.spec_from_file_location("lerobot.verification.verification_layer", path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def export_verif_excel(path=None, features=None, results=None):
    """FEATURES 清单 (+ 结果) → Excel, 返回 (本地路径, sheet 摘要)

    features: list_features() 的 dict 列表 (含 kind/role/spec 元数据)
    results:  {fid: (ok, detail)} 或 None — 有结果加「结果」列
    列: ID | 域 | 类别(基本/泛化) | 模型角色 | 模型特点 | 功能名称 | 层/位置 | 验证方式 | 结果
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    if path is None:
        path = os.path.join(_repo_root(), "reports", "state_space_features.xlsx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = openpyxl.Workbook()
    _HDR = PatternFill("solid", fgColor="1F6FEB")
    _HF = Font(color="FFFFFF", bold=True, size=11)

    # ── Sheet1 Feature 功能清单 ──
    ws = wb.active
    ws.title = "功能清单"
    cols = ["ID", "域", "类别", "模型角色", "功能名称", "模型特点", "层/位置", "验证方式"]
    if results:
        cols.append("测试结果")
    ws.append(cols)
    for c in ws[1]:
        c.fill, c.font = _HDR, _HF
    for f in (features or []):
        row = [f["id"], f["dom"], f["kind"], f["role"], f["name"], f["spec"],
               f["loc"], f["how"]]
        if results:
            _ok = results.get(f["id"])
            row.append("✅ PASS" if _ok and _ok[0] else
                       ("❌ FAIL" if _ok else ("⏭ SKIP" if f["test"] is None else "—")))
        ws.append(row)
    for i, w in enumerate((8, 10, 10, 12, 46, 60, 22, 14, 12), start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    # ── Sheet2 分类统计 ──
    ws2 = wb.create_sheet("分类统计")
    ws2.append(["维度", "类别", "数量"])
    for c in ws2[1]:
        c.fill, c.font = _HDR, _HF
    from collections import Counter
    for f in (features or []):
        pass
    kinds = Counter((f["kind"] for f in (features or [])))
    roles = Counter((f["role"] for f in (features or [])))
    for k, v in kinds.items():
        ws2.append(["功能类别", k or "(未标注)", v])
    for k, v in roles.items():
        ws2.append(["模型角色", k or "(未标注)", v])
    ws2.column_dimensions["A"].width = 12
    ws2.column_dimensions["B"].width = 20

    # ── Sheet3 测试结果明细 (有结果时) ──
    if results:
        ws3 = wb.create_sheet("测试明细")
        ws3.append(["ID", "结果", "证据"])
        for c in ws3[1]:
            c.fill, c.font = _HDR, _HF
        for fid, (ok, detail) in sorted(results.items()):
            ws3.append([fid, "PASS" if ok else "FAIL", str(detail)[:200]])
        ws3.column_dimensions["A"].width = 8
        ws3.column_dimensions["B"].width = 10
        ws3.column_dimensions["C"].width = 80

    wb.save(path)
    return path


class VerificationDialog(QDialog):
    """🧩 验证层 — Feature 清单 / Test 结果 (节点双击打开, 可导出 Excel)"""

    export_done = pyqtSignal(str)

    def __init__(self, mode="feature", parent=None, log=None):
        super().__init__(parent)
        self._mode = mode              # "feature" | "test"
        self._log = log or (lambda *a: None)
        self._mod = _verif_module()
        self.setWindowTitle("🧩 Feature 功能清单 · 验证层" if mode == "feature"
                            else "🧪 Test 用例执行 · 验证层")
        self.setStyleSheet(_DARK)
        self.setMinimumSize(1000, 560)
        self.resize(1180, 680)
        lay = QVBoxLayout(self)

        # 汇总行 (分类统计)
        _rows = self._mod.VerificationLayer(log=lambda *a: None).list_features()
        _k = {}
        _r = {}
        for f in _rows:
            _k[f["kind"]] = _k.get(f["kind"], 0) + 1
            _r[f["role"]] = _r.get(f["role"], 0) + 1
        _sum = (f"共 {len(_rows)} 项 · " +
                " ".join(f"{k} {v}" for k, v in sorted(_k.items()) if k) + " · " +
                " | ".join(f"{k} {v}" for k, v in sorted(_r.items()) if k))
        self.lbl_sum = QLabel(_sum)
        self.lbl_sum.setStyleSheet("color:#8b949e; font-size:12px; padding:2px;")
        lay.addWidget(self.lbl_sum)

        # 表格
        self.tbl = QTableWidget(0, 0)
        self.tbl.setStyleSheet(_SS)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setStyleSheet(_SS + "QTableWidget { alternate-background-color:#1c2128; }")
        lay.addWidget(self.tbl, 1)

        # 结果标签 + 按钮
        h = QHBoxLayout()
        self.lbl_res = QLabel("")
        self.lbl_res.setStyleSheet("color:#8b949e; font-size:12px;")
        self.lbl_res.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h.addWidget(self.lbl_res)
        h.addStretch()
        if mode == "feature":
            b_run = QPushButton("▶ 运行全部测试")
            b_run.setToolTip("后台跑验证层自动套件 (F-A01~F-F04, YOLO 慢用例跳过)")
            b_run.clicked.connect(self._run_tests)
            h.addWidget(b_run)
        b_export = QPushButton("导出 Excel")
        b_export.setObjectName("b_export")
        b_export.setToolTip("导出功能清单 Excel → 上传 datadrive.world (含分类/角色/特点列)")
        b_export.clicked.connect(self._export)
        b_close = QPushButton("关闭")
        b_close.setObjectName("b_close")
        b_close.clicked.connect(self.close)
        h.addWidget(b_export)
        h.addWidget(b_close)
        lay.addLayout(h)
        self.export_done.connect(self.lbl_res.setText)
        self._results = None
        self._load_rows()
        self._mode = mode

    # ── 表格填充 ──
    def _load_rows(self, results=None):
        self._results = results
        rows = self._mod.VerificationLayer(log=lambda *a: None).list_features()
        if results is None and self._mode == "feature":
            self._feature_rows = rows
        cols = ["ID", "域", "类别", "模型角色", "功能名称", "模型特点", "层/位置", "验证方式"]
        if results:
            cols.append("结果")
        self.tbl.setColumnCount(len(cols))
        self.tbl.setHorizontalHeaderLabels(cols)
        self.tbl.setRowCount(len(rows))
        for i, f in enumerate(rows):
            _vals = [f["id"], f["dom"], f["kind"], f["role"], f["name"], f["spec"],
                     f["loc"], f["how"]]
            if results:
                _ok = results.get(f["id"])
                _vals.append("✅ PASS" if _ok and _ok[0] else
                             ("❌ FAIL" if _ok else ("⏭ SKIP" if f["test"] is None else "—")))
            for j, v in enumerate(_vals):
                it = QTableWidgetItem(str(v))
                if f["id"].startswith("F-A"):
                    pass
                it.setForeground(Qt.white)
                self.tbl.setItem(i, j, it)
        # 类别列着色 (绿=泛化, 蓝=基本) — 单色原则: 仅类别列微区分
        for i, f in enumerate(rows):
            _kind = self.tbl.item(i, 2)
            if _kind:
                _kind.setForeground(Qt.green if f["kind"] == "泛化功能" else
                                    (Qt.cyan if f["kind"] == "基本功能" else Qt.gray))
            _role = self.tbl.item(i, 3)
            if _role and f["role"] in ("感知模型", "世界模型"):
                _role.setForeground(Qt.yellow)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        for j in range(self.tbl.columnCount()):
            if j not in (4, 5):
                self.tbl.resizeColumnToContents(j)
        self.tbl.setSortingEnabled(True)

    # ── 后台跑测试 (不冻结 GUI; 引擎快 <1s, YOLO 慢跳过) ──
    def _run_tests(self):
        self.lbl_res.setText("⏳ 后台运行自动测试套件… (引擎/六层/规划/元层/画布, YOLO 慢用例跳过)")
        import threading

        def _work():
            try:
                v = self._mod.VerificationLayer(log=lambda *a: None)
                ok = v.run_all(skip_slow=True)
                self._results = v.results
                self.export_done.emit(
                    f"✅ 套件完成: PASS {v.passed} · FAIL {v.failed} · SKIP {v.skipped}"
                    f"{' · 全绿' if ok else ' · 有失败(查看表格明细)'}")
            except Exception as e:
                self.export_done.emit(f"⚠️ 测试运行失败: {e}")
            # 回主线程刷新表格
            try:
                from PyQt5.QtCore import QTimer
                _res = self._results
                QTimer.singleShot(0, lambda: (self._load_rows(_res),
                                              self.lbl_res.setText(
                                                  f"✅ 结果已刷新 (PASS {sum(1 for x in _res.values() if x[0])}"
                                                  f" · FAIL {sum(1 for x in _res.values() if not x[0])})")))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    # ── 导出 Excel (后台线程 + scp 上传, 同 on_export_tasks 模式) ──
    def _export(self):
        self.lbl_res.setText("⏳ 正在导出 Excel 并上传 datadrive.world…")
        import threading

        def _work():
            try:
                rows = self._mod.VerificationLayer(log=lambda *a: None).list_features()
                path = export_verif_excel(features=rows, results=self._results)
                # scp 上传 ECS (用户可下载)
                import subprocess as _sp
                fname = os.path.basename(path)
                msg = f"✅ 已导出: {path}"
                try:
                    r = _sp.run(["sshpass", "-p", "Nix19789", "scp", "-o", "StrictHostKeyChecking=no",
                                 "-o", "ConnectTimeout=15", path,
                                 f"root@39.102.211.79:/www/wwwroot/datadrive.world/{fname}"],
                                capture_output=True, timeout=60)
                    if r.returncode == 0:
                        _sp.run(["sshpass", "-p", "Nix19789", "ssh", "-o", "StrictHostKeyChecking=no",
                                 "-o", "ConnectTimeout=15", "root@39.102.211.79",
                                 f"chmod 644 /www/wwwroot/datadrive.world/{fname}"],
                                capture_output=True, timeout=30)
                        msg = (f'✅ 已导出并上传: <a href="http://datadrive.world/{fname}" '
                               f'style="color:#58a6ff;">http://datadrive.world/{fname}</a>')
                except Exception as _e:
                    msg += f" (上传失败: {_e})"
            except Exception as _e:
                msg = f"⚠️ 导出失败: {_e}"
            self.export_done.emit(msg)

        threading.Thread(target=_work, daemon=True).start()


def _mb(parent, title, text, kind="info"):
    mb = QMessageBox(parent)
    mb.setWindowTitle(title)
    mb.setText(text)
    mb.setStyleSheet(_DARK)
    if kind == "warn":
        mb.setIcon(QMessageBox.Warning)
    mb.exec_()


if __name__ == "__main__":
    import sys as _s
    from PyQt5.QtWidgets import QApplication
    app = QApplication(_s.argv)
    d = VerificationDialog(mode=_s.argv[1] if len(_s.argv) > 1 else "feature")
    d.show()
    _s.exit(app.exec_())
