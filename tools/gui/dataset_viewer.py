#!/usr/bin/env python3
"""
Z-MAX 数据集查看器
支持浏览 LeRobot 数据集的图片、视频、state/action 曲线
"""

import json
import glob
import os

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QListWidget, QTabWidget, QFrame, QScrollArea,
    QListWidgetItem, QGroupBox, QMessageBox, QWidget,
    QTextEdit, QComboBox, QCheckBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPixmap, QImage

# 颜色定义 (与 studio.py 一致)
C_BG = "#0d1117"
C_BG2 = "#161b22"
C_CARD = "#1c2333"
C_BLUE = "#58a6ff"
C_GREEN = "#3fb950"
C_WHITE = "#e6edf3"
C_DIM = "#484f58"
C_BORDER = "#30363d"


class DatasetViewer(QDialog):
    """数据集内容查看器"""

    def __init__(self, repo_id: str, cache_dir: str, parent=None, local_root=None, local_npz=None):
        super().__init__(parent)
        self.repo_id = repo_id
        self.cache_dir = cache_dir
        self.local_root = local_root  # 2026-08-07 老倪: metaworld_mt50 本地实际数据在 data/, 不在 HF 缓存
        self.local_npz = local_npz    # 2026-08-07: metaworld_act/train.npz (系统 python3 无 pandas, numpy 直接读)
        self.repo_cache = self._get_repo_cache_dir(repo_id, cache_dir)

        self.setWindowTitle(f"📊 数据集查看器 — {repo_id}")
        self.setFixedSize(1100, 700)
        self.setStyleSheet(f"QDialog{{background:{C_BG}; border:2px solid {C_BLUE};}}")

        self.info_dict = {}
        self.parquet_files = []
        self.video_files = []
        self.current_episode = 0
        self.current_frame = 0
        self.frames = []  # numpy arrays
        self._npz_cache = None  # 2026-08-07: npz 拖动滑块缓存 (不重复 np.load 28MB)
        self._npz_obs = None   # 提取到内存的观测数组 (翻帧提速)
        self._npz_st = None
        self._npz_ac = None

        self._build_ui()
        self._load_dataset_info()
        # 2026-08-07 老倪: 下一帧点不了 — 打开即自动加载第一帧 (maximum 就位, 不用手动点加载帧)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._load_video_frame)

    def _get_repo_cache_dir(self, repo_id, cache_dir):
        """找到 HuggingFace Hub 缓存目录"""
        repo_slug = repo_id.replace("/", "--")
        candidate = os.path.join(cache_dir, f"datasets--{repo_slug}")
        if os.path.exists(candidate):
            # 查找 snapshots 目录
            snapshots = glob.glob(os.path.join(candidate, "snapshots", "*"))
            if snapshots:
                # 返回最新的 snapshot (通常是第一个)
                return snapshots[0]
            # 如果没有 snapshots，检查 blob 目录下的直接文件
            blobs = glob.glob(os.path.join(candidate, "blobs", "*"))
            if blobs:
                return os.path.join(candidate, "blobs")
        return candidate

    def _build_ui(self):
        """构建界面"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # 顶部信息栏
        top = QFrame()
        top.setStyleSheet(f"background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px;")
        top_layout = QVBoxLayout()
        top_layout.setContentsMargins(12, 8, 12, 8)

        self.lbl_title = QLabel(f"📦 {self.repo_id}")
        self.lbl_title.setFont(QFont("Arial", 14, QFont.Bold))
        self.lbl_title.setStyleSheet(f"color:{C_BLUE}; background:transparent; border:none;")
        top_layout.addWidget(self.lbl_title)

        self.lbl_summary = QLabel("正在加载数据集信息...")
        self.lbl_summary.setFont(QFont("Consolas", 9))
        self.lbl_summary.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        self.lbl_summary.setWordWrap(True)
        top_layout.addWidget(self.lbl_summary)

        top.setLayout(top_layout)
        main_layout.addWidget(top)

        # Tab 切换
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background:{C_CARD}; color:{C_DIM}; padding:6px 20px;
                border:1px solid {C_BORDER}; border-radius:4px 4px 0 0; margin-right:2px;
            }}
            QTabBar::tab:selected {{ background:{C_BG2}; color:{C_BLUE}; border-bottom:2px solid {C_BLUE}; }}
        """)

        # Tab 1 - 图片
        self._build_image_tab()
        # Tab 2 - State/Action
        self._build_state_tab()
        # Tab 3 - 视频
        self._build_video_tab()
        # Tab 4 - 元数据
        self._build_metadata_tab()

        main_layout.addWidget(self.tabs)

        # 底部关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFont(QFont("Arial", 10, QFont.Bold))
        close_btn.setStyleSheet(f"background:{C_BLUE}; color:white; border:none; border-radius:6px; padding:8px 24px;")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        main_layout.addLayout(btn_row)

        self.setLayout(main_layout)

    def _build_image_tab(self):
        """图片浏览 Tab"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Episode 选择
        ep_row = QHBoxLayout()
        lbl = QLabel("Episode:")
        lbl.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        self.ep_slider = QSlider(Qt.Horizontal)
        self.ep_slider.setMinimum(0)
        self.ep_slider.setMaximum(0)
        self.ep_slider.setStyleSheet("QSlider::handle{background:#58a6ff; border-radius:4px;}")
        self.ep_slider.valueChanged.connect(self._on_episode_changed)
        self.ep_label = QLabel("0")
        self.ep_label.setStyleSheet(f"color:{C_BLUE}; background:transparent; border:none; font-weight:bold;")
        ep_row.addWidget(lbl)
        ep_row.addWidget(self.ep_slider)
        ep_row.addWidget(self.ep_label)
        layout.addLayout(ep_row)

        # Frame 选择
        frame_row = QHBoxLayout()
        lbl2 = QLabel("Frame:")
        lbl2.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setStyleSheet("QSlider::handle{background:#3fb950; border-radius:4px;}")
        self.frame_slider.valueChanged.connect(self._on_frame_changed)
        self.frame_label = QLabel("0")
        self.frame_label.setStyleSheet(f"color:{C_GREEN}; background:transparent; border:none; font-weight:bold;")
        frame_row.addWidget(lbl2)
        frame_row.addWidget(self.frame_slider)
        frame_row.addWidget(self.frame_label)
        layout.addLayout(frame_row)

        # 图片显示区
        self.lbl_image = QLabel("点击 '加载帧' 按钮查看图像")
        self.lbl_image.setFixedSize(640, 480)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setStyleSheet(f"background:{C_BG2}; color:{C_DIM}; border:1px solid {C_BORDER}; border-radius:4px; font-size:12px;")
        layout.addWidget(self.lbl_image, alignment=Qt.AlignCenter)

        # 按钮
        btn_row = QHBoxLayout()
        load_btn = QPushButton("🖼️ 加载帧")
        load_btn.setStyleSheet(f"background:{C_BLUE}; color:white; border:none; border-radius:4px; padding:6px 18px; font-weight:bold;")
        load_btn.clicked.connect(self._load_video_frame)
        btn_row.addWidget(load_btn)

        prev_btn = QPushButton("◀ 上一帧")
        next_btn = QPushButton("下一帧 ▶")
        prev_btn.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:6px 18px;")
        next_btn.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:6px 18px;")
        prev_btn.clicked.connect(lambda: self.frame_slider.setValue(max(0, self.frame_slider.value() - 1)))
        next_btn.clicked.connect(lambda: self.frame_slider.setValue(min(self.frame_slider.maximum(), self.frame_slider.value() + 1)))
        btn_row.addWidget(prev_btn)
        btn_row.addWidget(next_btn)
        layout.addLayout(btn_row)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "🖼️ 图片")

    def _build_state_tab(self):
        """State/Action 曲线 Tab"""
        tab = QWidget()
        layout = QVBoxLayout()

        self.state_text = QTextEdit()
        self.state_text.setReadOnly(True)
        self.state_text.setFont(QFont("Consolas", 10))
        self.state_text.setStyleSheet(f"background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px;")
        self.state_text.setText("选择 Episode 后点击 '加载数据' 查看 state/action 曲线")
        layout.addWidget(self.state_text)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("📈 加载数据")
        load_btn.setStyleSheet(f"background:{C_GREEN}; color:white; border:none; border-radius:4px; padding:6px 18px; font-weight:bold;")
        load_btn.clicked.connect(self._load_state_action_plot)
        btn_row.addWidget(load_btn)
        layout.addLayout(btn_row)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "📈 State/Action")

    def _build_video_tab(self):
        """视频信息 Tab"""
        tab = QWidget()
        layout = QVBoxLayout()

        self.video_list = QListWidget()
        self.video_list.setStyleSheet(f"""
            QListWidget {{ background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER}; }}
            QListWidget::item {{ padding:6px; border-bottom:1px solid {C_BORDER}; }}
            QListWidget::item:selected {{ background:{C_BLUE}33; color:{C_BLUE}; }}
        """)
        layout.addWidget(self.video_list)

        hint = QLabel("💡 提示: 双击视频文件可在系统播放器中打开")
        hint.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; padding:4px;")
        layout.addWidget(hint)

        self.video_list.itemDoubleClicked.connect(self._open_video_in_system_player)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "🎥 视频")

    def _build_metadata_tab(self):
        """元数据 Tab"""
        tab = QWidget()
        layout = QVBoxLayout()

        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setFont(QFont("Consolas", 10))
        self.meta_text.setStyleSheet(f"background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px;")
        layout.addWidget(self.meta_text)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "📋 元数据")

    def _load_dataset_info(self):
        """加载数据集信息"""
        try:
            # 查找 info.json
            info_path = self._find_file_in_cache("info.json")
            if info_path and os.path.exists(info_path):
                with open(info_path, 'r') as f:
                    self.info_dict = json.load(f)

                total_eps = self.info_dict.get("total_episodes", "?")
                total_frames = self.info_dict.get("total_frames", "?")
                fps = self.info_dict.get("fps", "?")
                robot = self.info_dict.get("robot_type", "?")

                # features
                features = self.info_dict.get("features", {})
                feat_keys = list(features.keys())
                feat_lines = []
                for k in feat_keys:
                    f = features[k]
                    feat_lines.append(f"  • {k}: dtype={f.get('dtype','?')}, shape={f.get('shape','?')}")

                self.lbl_summary.setText(
                    f"Episodes: {total_eps}  |  Frames: {total_frames}  |  FPS: {fps}  |  Robot: {robot}\n"
                    + "\n".join(feat_lines[:8])
                )

                # 更新 meta text
                self.meta_text.setPlainText(json.dumps(self.info_dict, indent=2, ensure_ascii=False))

                # 更新 episode 滑块
                try:
                    self.ep_slider.setMaximum(int(total_eps) - 1 if total_eps != "?" else 0)
                except:
                    self.ep_slider.setMaximum(9)
            else:
                self.lbl_summary.setText(f"⚠️ 未找到 info.json (缓存路径: {self.repo_cache})")

            # 查找视频文件
            self.video_files = self._find_files_in_cache("*.mp4") + \
                               self._find_files_in_cache("*.webm") + \
                               self._find_files_in_cache("*.avi")
            for vf in self.video_files:
                item = QListWidgetItem(f"🎥 {os.path.relpath(vf, self.local_root or self.repo_cache)}")
                item.setData(Qt.UserRole, vf)
                self.video_list.addItem(item)

            # 查找 parquet 文件
            self.parquet_files = self._find_files_in_cache("*.parquet")

            self.lbl_summary.setText(
                self.lbl_summary.text() +
                f"\n📁 视频文件: {len(self.video_files)}  |  Parquet: {len(self.parquet_files)}"
            )

        except Exception as e:
            self.lbl_summary.setText(f"❌ 加载失败: {e}")

    def _find_file_in_cache(self, filename):
        """在缓存目录中查找文件"""
        roots = [self.repo_cache]
        if self.local_root:  # 2026-08-07: 本地项目数据 (metaworld_mt50 在 data/)
            roots.append(self.local_root)
        for base in roots:
            for root, dirs, files in os.walk(base):
                if filename in files:
                    return os.path.join(root, filename)
        return None

    def _find_files_in_cache(self, pattern):
        """在缓存目录中查找匹配的文件"""
        results = []
        roots = [self.repo_cache]
        if self.local_root:
            roots.append(self.local_root)
        for base in roots:
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(pattern[1:]):
                        results.append(os.path.join(root, f))
        return sorted(results)

    def _on_episode_changed(self, val):
        self.current_episode = val
        self.ep_label.setText(str(val))
        # 重置帧滑块
        features = self.info_dict.get("features", {})
        image_shapes = [f.get("shape", [0])[-1] for k, f in features.items() if 'image' in k.lower() or 'video' in k.lower()]
        if image_shapes:
            max_frames = 300  # 默认
        else:
            max_frames = 100
        self.frame_slider.setMaximum(max_frames - 1)

    def _on_frame_changed(self, val):
        self.current_frame = val
        self.frame_label.setText(str(val))
        # 🐛 2026-08-07 老倪: 点不了下一帧 — 滑块变化只改数字不加载图 → 触发重新加载
        if self.video_files or self.parquet_files or self.local_npz:
            self._load_video_frame()

    def _load_video_frame(self):
        """从视频文件/parquet/npz/json 采集包中解码指定帧
        (2026-08-07 老倪: orin_live 是 json 采集包(无图像) → 显示包 meta + 帧状态/动作)"""
        if self.local_npz and os.path.exists(self.local_npz):
            self._load_npz_frame()
            return
        if self.local_root and not self.parquet_files and not self.video_files:
            import glob as _g
            if _g.glob(os.path.join(self.local_root, "*.json")):
                self._load_json_package()
                return
        if not self.video_files and self.parquet_files:
            self._load_parquet_frame()
            return
        ep = self.current_episode
        # 找到对应 episode 的视频
        video_path = None
        for vf in self.video_files:
            basename = os.path.basename(vf)
            # 文件名通常是 episode_000000.mp4
            if f"episode_{ep:06d}" in basename or f"episode_{ep:04d}" in basename:
                video_path = vf
                break

        if not video_path:
            # 尝试匹配 chunk
            chunk_idx = ep // 1000
            for vf in self.video_files:
                if f"chunk-{chunk_idx:03d}" in vf and "episode_" in vf:
                    video_path = vf
                    break

        if not video_path:
            if self.video_files:
                video_path = self.video_files[0]
                self.lbl_image.setText(f"⚠️ 未找到 episode_{ep:06d} 视频，显示第一个: {os.path.basename(video_path)}")
            else:
                self.lbl_image.setText("⚠️ 缓存中未找到视频文件\n请先下载数据集")
                return

        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = cap.read()
            cap.release()

            if ret:
                import numpy as np
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                bytes_per_line = ch * w
                q_img = QImage(rgb.data.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(q_img)
                self.lbl_image.setPixmap(pixmap.scaled(640, 480, Qt.KeepAspectRatio))
                self.lbl_image.setText("")  # 清除提示文字

                # 更新最大帧数
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if hasattr(cap, 'get') else 100
                if self.frame_slider.maximum() < 10:
                    self.frame_slider.setMaximum(total_frames - 1)
            else:
                self.lbl_image.setText(f"⚠️ 帧 {self.current_frame} 超出范围")
        except ImportError:
            self.lbl_image.setText("⚠️ 需要安装 opencv-python\npip install opencv-python")
        except Exception as e:
            self.lbl_image.setText(f"⚠️ 读取失败: {e}")

    def _load_parquet_frame(self):
        """2026-08-07 老倪: 本地数据无 mp4 → 从 npz (numpy 直读) 或 parquet 内嵌图像读帧"""
        if self.local_npz and os.path.exists(self.local_npz):
            self._load_npz_frame()
            return
        try:
            import pandas as _pd
            import numpy as _np
            import io as _io
            from PIL import Image as _PIL
            if not self.parquet_files:
                self.lbl_image.setText("⚠️ 无数据文件")
                return
            df = _pd.read_parquet(self.parquet_files[0])
            ep_df = df[df["episode_index"] == self.current_episode] if "episode_index" in df else df
            if len(ep_df) == 0:
                ep_df = df  # 单 episode / 无该 ep → 全量
            if self.current_frame >= len(ep_df):
                self.lbl_image.setText(f"⚠️ 帧 {self.current_frame} 超出 (该 episode 共 {len(ep_df)} 帧)")
                return
            img = ep_df.iloc[self.current_frame]["observation.image"]
            if isinstance(img, dict) and "bytes" in img:
                img = img["bytes"]
            if isinstance(img, bytes):
                pil = _PIL.open(_io.BytesIO(img)).convert("RGB")
                rgb = _np.asarray(pil)
                h, w, ch = rgb.shape
                q_img = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format_RGB888)
                self.lbl_image.setPixmap(QPixmap.fromImage(q_img).scaled(640, 480, Qt.KeepAspectRatio))
                self.lbl_image.setText("")
                if self.frame_slider.maximum() < 10:
                    self.frame_slider.setMaximum(max(0, len(ep_df) - 1))
            else:
                self.lbl_image.setText(f"⚠️ 图像字段格式: {type(img).__name__}")
        except Exception as e:
            self.lbl_image.setText(f"⚠️ parquet 读取失败: {e}")

    def _load_npz_frame(self):
        """2026-08-07: metaworld_act/train.npz 帧显示 (系统 python3 有 numpy, 无 pandas/pyarrow)"""
        try:
            import numpy as _np
            if self._npz_cache is None:
                self._npz_cache = _np.load(self.local_npz)
                # 🐛 2026-08-07 老倪: 翻帧慢 (1.5s/帧) — NpzFile 数组访问是 lazy 解压,
                #   每帧 d["observations"] 都重新解压 → 提取到内存 ndarray 一次
                self._npz_obs = _np.array(self._npz_cache["observations"])
                self._npz_st = self._npz_cache["states"] if "states" in self._npz_cache else None
                self._npz_ac = self._npz_cache["actions"] if "actions" in self._npz_cache else None
            obs = self._npz_obs
            n = len(obs)
            if self.current_frame >= n:
                self.lbl_image.setText(f"⚠️ 帧 {self.current_frame} 超出 (共 {n} 帧)")
                return
            arr = obs[self.current_frame]  # (3,H,W)
            if arr.ndim == 4 and arr.shape[0] == 1:
                arr = arr[0]
            rgb = (arr.transpose(1, 2, 0) * 255).astype(_np.uint8) if arr.shape[0] == 3 else arr
            # 2026-08-07 老倪: 插销数据(peg_v2/peg_lerobot)与视频同源需 180° 旋转;
            #   metaworld_act 是 MT50 官方数据(方向本来正确) → 不转
            if "peg" in (self.local_npz or ""):
                rgb = _np.rot90(rgb, k=2)
            h, w, ch = rgb.shape
            q_img = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format_RGB888)
            self.lbl_image.setPixmap(QPixmap.fromImage(q_img).scaled(640, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.lbl_image.setText("")
            if self.frame_slider.maximum() < 10:
                self.frame_slider.setMaximum(max(0, n - 1))
            st = self._npz_st[self.current_frame] if self._npz_st is not None else None
            ac = self._npz_ac[self.current_frame] if self._npz_ac is not None else None
            tip = f"帧 {self.current_frame}/{n} · 任务: {self._npz_cache['task_name'] if 'task_name' in self._npz_cache else '?'}"
            if st is not None:
                tip += f"\nstate {st.round(3).tolist()}"
            if ac is not None:
                tip += f"\naction {ac.round(3).tolist()}"
            self.lbl_image.setToolTip(tip)
        except Exception as e:
            self.lbl_image.setText(f"⚠️ npz 读取失败: {e}")

    def _load_json_package(self):
        """2026-08-07 老倪: orin 采集包 (json, 无图像) → 显示包 meta + 帧状态/动作"""
        try:
            import json as _j, glob as _g
            jsons = sorted(_g.glob(os.path.join(self.local_root, "*.json")))
            if not jsons:
                self.lbl_image.setText("⚠️ 无数据文件")
                return
            if self.current_episode >= len(jsons):
                self.current_episode = 0
            d = _j.load(open(jsons[self.current_episode], encoding="utf-8"))
            meta = d.get("meta", {})
            frames = d.get("frames", [])
            if not frames:
                self.lbl_image.setText(f"📦 包 {os.path.basename(jsons[self.current_episode])} 无帧数据")
                return
            if self.current_frame >= len(frames):
                self.current_frame = len(frames) - 1
            fr = frames[self.current_frame]
            st = fr.get("observation.state", [])
            ac = fr.get("action", [])
            txt = (f"📦 {os.path.basename(jsons[self.current_episode])}\n"
                   f"源: {meta.get('source', '?')} · 帧: {len(frames)} · 关节: {meta.get('n_joint', '?')}D\n\n"
                   f"帧 {self.current_frame}/{len(frames)}\n"
                   f"state: {str(st)[:84]}\n"
                   f"action: {str(ac)[:64]}")
            self.lbl_image.setPixmap(QPixmap())
            self.lbl_image.setText(txt)
            if self.frame_slider.maximum() < len(frames) - 1:
                self.frame_slider.setMaximum(max(0, len(frames) - 1))
            if self.ep_slider.maximum() < len(jsons) - 1:
                self.ep_slider.setMaximum(max(0, len(jsons) - 1))
        except Exception as e:
            self.lbl_image.setText(f"⚠️ json 读取失败: {e}")

    def _load_state_action_plot(self):
        """加载并显示 state/action 数据（文本形式）"""
        ep = self.current_episode
        try:
            # 尝试使用 pyarrow 读取 parquet
            try:
                import pyarrow.parquet as pq
            except ImportError:
                self.state_text.setText("⚠️ 需要安装 pyarrow\npip install pyarrow")
                return

            # 找到对应 episode 的 parquet
            pq_path = None
            for pf in self.parquet_files:
                basename = os.path.basename(pf)
                if f"episode_{ep:06d}" in basename or f"episode_{ep:04d}" in basename:
                    pq_path = pf
                    break

            if not pq_path and self.parquet_files:
                pq_path = self.parquet_files[0]

            if not pq_path:
                # 尝试合并的 parquet
                for pf in self.parquet_files:
                    pq_path = pf
                    break

            if not pq_path:
                self.state_text.setText("⚠️ 缓存中未找到 parquet 文件\n请先下载数据集")
                return

            table = pq.read_table(pq_path)
            schema = table.schema

            output = f"📊 Parquet: {os.path.relpath(pq_path, self.repo_cache)}\n"
            output += f"行数: {table.num_rows}  |  列数: {len(schema)}\n"
            output += "─" * 60 + "\n\n"

            for col_name in schema.names:
                col = table.column(col_name)
                dtype = str(schema.field(col_name).type)
                output += f"📌 {col_name} ({dtype})\n"

                # 显示前 5 个值
                values = col.to_pylist()[:5]
                for i, v in enumerate(values):
                    if isinstance(v, (list, bytes)):
                        if isinstance(v, bytes):
                            output += f"    [{i}]: <binary {len(v)} bytes>\n"
                        elif isinstance(v, list) and len(v) > 10:
                            output += f"    [{i}]: {v[:5]}... (len={len(v)})\n"
                        else:
                            output += f"    [{i}]: {v}\n"
                    else:
                        output += f"    [{i}]: {v}\n"
                output += "\n"

            self.state_text.setText(output)

        except Exception as e:
            self.state_text.setText(f"❌ 加载失败: {e}")

    def _open_video_in_system_player(self, item):
        """用系统播放器打开视频"""
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            import subprocess
            try:
                subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e))
