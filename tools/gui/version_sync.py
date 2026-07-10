"""
Z-MAX 版本管理与上游同步模块
显示版本状态、检查更新、安全同步 LeRobot 官方上游代码
"""
import os
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGroupBox, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont

# 颜色（与 studio.py 一致）
C_BG = "#0d1117"
C_BG2 = "#161b22"
C_CARD = "#1c2333"
C_BORDER = "#30363d"
C_WHITE = "#e6edf3"
C_GRAY = "#8b949e"
C_DIM = "#484f58"
C_GREEN = "#3fb950"
C_BLUE = "#58a6ff"
C_ORANGE = "#d29922"
C_RED = "#f85149"
C_CYAN = "#39d2c0"


def _run_git(args, cwd, timeout=30):
    """Helper: run git command"""
    try:
        r = subprocess.run(
            ['git'] + args, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1


class UpstreamCheckThread(QThread):
    """后台线程：检查上游更新"""
    result_ready = pyqtSignal(dict)

    def __init__(self, repo_path):
        super().__init__()
        self.repo_path = repo_path

    def run(self):
        try:
            # Fetch upstream + tags
            _run_git(['fetch', 'upstream', '--tags'], self.repo_path, timeout=30)

            # 最新 upstream tag
            latest_tag, _ = _run_git(['describe', '--tags', '--abbrev=0', 'upstream/main'], self.repo_path)

            # 当前 commit
            current_commit, _ = _run_git(['rev-parse', '--short', 'HEAD'], self.repo_path)

            # 落后 upstream 的 commit 数
            behind_str, _ = _run_git(['rev-list', '--count', 'HEAD..upstream/main'], self.repo_path)
            commits_behind = int(behind_str) if behind_str.isdigit() else 0

            # 超前 upstream 的 commit 数
            ahead_str, _ = _run_git(['rev-list', '--count', 'upstream/main..HEAD'], self.repo_path)
            commits_ahead = int(ahead_str) if ahead_str.isdigit() else 0

            # 最近 10 个 upstream 新增 commits
            new_log, _ = _run_git(['log', '--oneline', 'HEAD..upstream/main', '--max-count=10'], self.repo_path)
            new_commits = new_log.split('\n') if new_log else []

            # 可能被修改的 upstream 文件（检测冲突风险）
            # 只看我们改过的文件是否在上游也改了
            diff_out, _ = _run_git(['diff', '--name-only', 'upstream/main...HEAD'], self.repo_path)
            our_files = set(diff_out.split('\n')) if diff_out else set()

            diff_out2, _ = _run_git(['diff', '--name-only', 'HEAD...upstream/main'], self.repo_path)
            their_files = set(diff_out2.split('\n')) if diff_out2 else set()

            conflict_risk = our_files & their_files

            # 获取 upstream 最新发布信息
            all_tags, _ = _run_git(['tag', '-l', 'v*', '--sort=-v:refname'], self.repo_path)
            all_tag_list = [t for t in all_tags.split('\n') if t] if all_tags else []

            self.result_ready.emit({
                'success': True,
                'latest_tag': latest_tag if latest_tag and 'fatal' not in latest_tag else "unknown",
                'current_commit': current_commit,
                'commits_behind': commits_behind,
                'commits_ahead': commits_ahead,
                'new_commits': new_commits,
                'conflict_risk_files': sorted(conflict_risk),
                'all_tags': all_tag_list[:8],
            })
        except Exception as e:
            self.result_ready.emit({'success': False, 'error': str(e)})


class SyncThread(QThread):
    """后台线程：执行同步"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, repo_path):
        super().__init__()
        self.repo_path = repo_path

    def run(self):
        try:
            # 1. 检查工作区
            self.progress.emit("⏳ 检查工作区状态...")
            status, _ = _run_git(['status', '--porcelain'], self.repo_path)
            if status.strip():
                self.finished.emit(False, "工作区有未提交的更改，请先 git commit 或 git stash")
                return

            # 2. Merge upstream/main
            self.progress.emit("⏳ 正在合并 upstream/main...")
            output, code = _run_git(
                ['merge', 'upstream/main', '--no-edit',
                 '-m', 'Sync: merge upstream huggingface/lerobot'],
                self.repo_path, timeout=120
            )

            if code != 0:
                if 'CONFLICT' in output:
                    # 获取冲突文件
                    conflict_files, _ = _run_git(['diff', '--name-only', '--diff-filter=U'], self.repo_path)
                    self.finished.emit(False,
                        f"⚠️ 合并产生冲突，需手动解决:\n\n{conflict_files}\n\n"
                        f"步骤:\n"
                        f"  1. 编辑上述文件，解决冲突标记\n"
                        f"  2. git add <文件>\n"
                        f"  3. git commit\n"
                        f"  4. git push origin main")
                    return
                else:
                    self.finished.emit(False, f"合并失败: {output}")
                    return

            # 3. 成功
            self.progress.emit("✅ 合并成功")
            self.finished.emit(True, "已成功同步上游最新代码！")

        except Exception as e:
            self.finished.emit(False, f"同步异常: {str(e)}")


class VersionSyncWidget(QWidget):
    """版本同步管理界面"""

    def __init__(self, repo_path, parent=None):
        super().__init__(parent)
        self.repo_path = repo_path
        self._build_ui()
        self._load_version_info()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea{{border:none;}} QScrollBar{{background:transparent;}}")

        page = QWidget()
        page.setStyleSheet(f"background:{C_BG};")
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(28, 20, 28, 20)

        # === 标题 ===
        title_row = QHBoxLayout()
        t = QLabel("版本同步  Upstream Sync")
        t.setFont(QFont("Arial", 17, QFont.Bold))
        t.setStyleSheet(f"color:{C_WHITE}; border:none; background:transparent;")
        title_row.addWidget(t)
        title_row.addStretch()
        layout.addLayout(title_row)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C_BORDER};")
        layout.addWidget(sep)

        # === 版本信息 ===
        ver_group = self._make_group("版本信息", C_BLUE)
        ver_layout = QVBoxLayout()
        self.version_table = QTableWidget()
        self.version_table.setColumnCount(2)
        self.version_table.setHorizontalHeaderLabels(["项目", "值"])
        self.version_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.version_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.version_table.verticalHeader().setVisible(False)
        self.version_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.version_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.version_table.setStyleSheet(f"""
            QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER}; }}
            QTableWidget::item {{ padding:6px 10px; }}
            QTableWidget::item:selected {{ background:{C_BLUE}33; }}
            QHeaderView::section {{ background:{C_BG2}; color:{C_BLUE}; border:1px solid {C_BORDER}; padding:6px; font-weight:bold; font-size:12px; }}
        """)
        ver_layout.addWidget(self.version_table)
        ver_group.setLayout(ver_layout)
        layout.addWidget(ver_group)

        # === 上游状态 ===
        up_group = self._make_group("上游状态  (huggingface/lerobot)", C_CYAN)
        up_layout = QVBoxLayout()
        up_layout.setSpacing(10)

        self.status_label = QLabel("点击「检查更新」获取上游状态")
        self.status_label.setFont(QFont("Arial", 12))
        self.status_label.setStyleSheet(f"color:{C_DIM}; padding:12px; background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        up_layout.addWidget(self.status_label)

        check_btn = QPushButton("🔄  检查更新")
        check_btn.setFont(QFont("Arial", 12, QFont.Bold))
        check_btn.setStyleSheet(f"""
            QPushButton {{ background:{C_BLUE}; color:white; border:none; border-radius:6px; padding:10px 24px; }}
            QPushButton:hover {{ background:#79b8ff; }}
            QPushButton:disabled {{ background:{C_DIM}; }}
        """)
        check_btn.clicked.connect(self._check_upstream)
        up_layout.addWidget(check_btn)

        # 详情区 (默认隐藏)
        self.details_widget = QWidget()
        details_layout = QVBoxLayout()
        details_layout.setSpacing(8)

        # 新增 commits
        self.commits_text = QTextEdit()
        self.commits_text.setReadOnly(True)
        self.commits_text.setMaximumHeight(180)
        self.commits_text.setFont(QFont("Consolas", 9))
        self.commits_text.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px;")
        details_layout.addWidget(self.commits_text)

        # 冲突风险
        self.conflict_label = QLabel()
        self.conflict_label.setFont(QFont("Consolas", 9))
        self.conflict_label.setStyleSheet(f"color:{C_ORANGE}; padding:8px; background:{C_BG2}; border:1px solid {C_ORANGE}44; border-radius:4px;")
        self.conflict_label.setWordWrap(True)
        details_layout.addWidget(self.conflict_label)

        # 同步按钮
        self.sync_btn = QPushButton("⬇️  安全同步上游代码")
        self.sync_btn.setEnabled(False)
        self.sync_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.sync_btn.setStyleSheet(f"""
            QPushButton {{ background:{C_GREEN}; color:#0d1117; border:none; border-radius:6px; padding:10px 24px; }}
            QPushButton:hover {{ background:#56d364; }}
            QPushButton:disabled {{ background:{C_DIM}; color:{C_GRAY}; }}
        """)
        self.sync_btn.clicked.connect(self._sync_upstream)
        details_layout.addWidget(self.sync_btn)

        self.details_widget.setLayout(details_layout)
        self.details_widget.setVisible(False)
        up_layout.addWidget(self.details_widget)

        up_group.setLayout(up_layout)
        layout.addWidget(up_group)

        # === 日志 ===
        log_group = self._make_group("同步日志", C_GRAY)
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(f"background:#0a0e14; color:{C_GREEN}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px;")
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # 版本说明
        note = QLabel(
            "💡 版本号格式: LeRobot版本-zmax.自定义版本\n"
            "   例: 0.5.2-zmax.1.0.4 = LeRobot 0.5.2 + Z-MAX v1.0.4\n\n"
            "⚠️ 同步前确保所有本地更改已提交。同步使用 git merge，不会破坏自定义代码。"
        )
        note.setFont(QFont("Arial", 9))
        note.setStyleSheet(f"color:{C_DIM}; padding:8px; background:transparent; border:none;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        page.setLayout(layout)
        scroll.setWidget(page)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def _make_group(self, title, color):
        g = QGroupBox(title)
        g.setStyleSheet(f"""
            QGroupBox {{ color:{color}; font-weight:bold; background:{C_CARD}; border:1px solid {color}44; border-radius:8px; margin-top:12px; padding-top:16px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 6px; }}
        """)
        return g

    def _load_version_info(self):
        """加载版本信息"""
        try:
            # LeRobot 版本 from pyproject.toml
            pyproject = os.path.join(self.repo_path, 'pyproject.toml')
            lerobot_ver = "unknown"
            if os.path.exists(pyproject):
                with open(pyproject, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('version = "'):
                            lerobot_ver = line.strip().split('"')[1]
                            break

            # Z-MAX 自定义版本 (从侧边栏版本号)
            zmax_ver = "1.0.4"

            # 当前 commit
            commit, _ = _run_git(['rev-parse', '--short', 'HEAD'], self.repo_path)

            # 当前分支
            branch, _ = _run_git(['branch', '--show-current'], self.repo_path)

            # 最近的 tag
            tag, rc = _run_git(['describe', '--tags', '--always', '--abbrev=0'], self.repo_path)
            if rc != 0:
                tag = "N/A"

            # upstream 配置状态
            _, rc = _run_git(['remote', 'get-url', 'upstream'], self.repo_path)
            upstream_status = "✅ 已配置" if rc == 0 else "❌ 未配置"

            # 工作区状态
            dirty, _ = _run_git(['status', '--porcelain'], self.repo_path)
            ws_status = "✅ 干净" if not dirty.strip() else f"⚠️ 有 {len(dirty.strip().split(chr(10)))} 个未提交文件"

            self.version_table.setRowCount(8)
            items = [
                ("LeRobot 版本", lerobot_ver),
                ("Z-MAX 版本", f"zmax-{zmax_ver}"),
                ("完整版本标识", f"{lerobot_ver}-zmax.{zmax_ver}"),
                ("最近 Tag", tag),
                ("当前 Commit", commit),
                ("当前分支", branch),
                ("上游 Remote", upstream_status),
                ("工作区", ws_status),
            ]
            for i, (key, val) in enumerate(items):
                k = QTableWidgetItem(key)
                v = QTableWidgetItem(val)
                k.setFont(QFont("Arial", 10, QFont.Bold))
                v.setFont(QFont("Consolas", 10))
                self.version_table.setItem(i, 0, k)
                self.version_table.setItem(i, 1, v)

        except Exception as e:
            self._log(f"加载版本信息失败: {e}")

    def _check_upstream(self):
        self._log("🔄 开始检查上游更新...")
        self.status_label.setText("⏳ 正在获取上游信息...")
        self.status_label.setStyleSheet(f"color:{C_BLUE}; padding:12px; background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;")

        self.check_thread = UpstreamCheckThread(self.repo_path)
        self.check_thread.result_ready.connect(self._on_upstream_checked)
        self.check_thread.start()

    def _on_upstream_checked(self, result):
        if not result.get('success'):
            self.status_label.setText(f"❌ 检查失败: {result.get('error', 'unknown')}")
            self.status_label.setStyleSheet(f"color:{C_RED}; padding:12px; background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;")
            self._log(f"❌ 检查失败: {result.get('error')}")
            return

        behind = result['commits_behind']
        ahead = result['commits_ahead']
        latest = result['latest_tag']

        if behind == 0:
            self.status_label.setText(f"✅ 已是最新  |  上游最新 Release: {latest}  |  自定义提交: {ahead}")
            self.status_label.setStyleSheet(f"color:{C_GREEN}; font-size:12px; padding:12px; background:{C_BG}; border:1px solid {C_GREEN}44; border-radius:6px;")
            self._log(f"✅ 已是最新，无需同步")
            self.details_widget.setVisible(False)
            return

        self.status_label.setText(
            f"⚠️ 落后上游 {behind} 个提交  |  上游最新: {latest}  |  自定义提交: {ahead}"
        )
        self.status_label.setStyleSheet(f"color:{C_ORANGE}; font-size:12px; padding:12px; background:{C_BG}; border:1px solid {C_ORANGE}44; border-radius:6px;")

        # 显示新增 commits
        commits_text = "上游新增提交:\n" + "\n".join(f"  {c}" for c in result['new_commits'])
        self.commits_text.setPlainText(commits_text)

        # 冲突风险
        risk = result.get('conflict_risk_files', [])
        if risk:
            self.conflict_label.setText(
                f"⚠️ 以下 {len(risk)} 个文件上下游均有修改，同步时可能冲突:\n" +
                "\n".join(f"  • {f}" for f in risk[:6])
            )
            self.conflict_label.setVisible(True)
        else:
            self.conflict_label.setText("✅ 无冲突风险 - 你的自定义文件与上游无交叉")
            self.conflict_label.setStyleSheet(f"color:{C_GREEN}; padding:8px; background:{C_BG2}; border:1px solid {C_GREEN}44; border-radius:4px;")
            self.conflict_label.setVisible(True)

        self.details_widget.setVisible(True)
        self.sync_btn.setEnabled(True)
        self._log(f"📦 上游有 {behind} 个新提交可以同步")

    def _sync_upstream(self):
        reply = QMessageBox.question(
            self, "确认同步",
            "即将执行 git merge upstream/main\n\n"
            "这会合并上游所有新代码到你的分支。\n"
            "你的自定义代码 (smolvla_lew, gui, docs) 不会受影响。\n\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("⏳ 同步中...")
        self._log("🚀 开始同步上游更新...")

        self.sync_thread = SyncThread(self.repo_path)
        self.sync_thread.progress.connect(lambda msg: self._log(msg))
        self.sync_thread.finished.connect(self._on_sync_finished)
        self.sync_thread.start()

    def _on_sync_finished(self, success, message):
        self.sync_btn.setText("⬇️  安全同步上游代码")
        if success:
            self.status_label.setText(f"✅ {message}")
            self.status_label.setStyleSheet(f"color:{C_GREEN}; font-size:12px; padding:12px; background:{C_BG}; border:1px solid {C_GREEN}44; border-radius:6px;")
            self._log(f"✅ {message}")
            self.details_widget.setVisible(False)
            self._load_version_info()

            QMessageBox.information(self, "同步成功",
                "✅ 上游代码已成功同步!\n\n"
                "你的自定义代码完好无损:\n"
                "  • smolvla_lew 策略\n"
                "  • zmax_* 策略\n"
                "  • GUI 工具\n"
                "  • 项目文档\n\n"
                "请执行 git push origin main 推送到你的 GitHub。")
        else:
            self.status_label.setText(f"❌ {message[:80]}")
            self.status_label.setStyleSheet(f"color:{C_RED}; font-size:11px; padding:12px; background:{C_BG}; border:1px solid {C_RED}44; border-radius:6px;")
            self._log(f"❌ {message}")
            self.sync_btn.setEnabled(True)

            QMessageBox.warning(self, "同步失败", message)

    def _log(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {message}")
