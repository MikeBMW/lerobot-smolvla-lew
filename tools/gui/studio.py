#!/usr/bin/env python3
"""
XSpace Studio — 集成化开发界面
Z-MAX 多模态动作专家 · System 0 / Sys-11 / Sys-12 / System 2

基于 Z-MAX 三层解耦架构设计:
  System 0 (L2基石)  → 硬件工具箱
  Sys-11 (动作系统)  → 训练控制台 + 配置中心
  Sys-12 (引导系统)  → 评估分析 + 实时监控
  System 2 (L4大脑)  → 数据集管理
"""

import sys
import subprocess  # 新增：用于执行git命令同步代码到GitHub
import os  # 新增：用于获取工作目录和HOME路径
import json
import glob
import time  # 硬件工具箱日志时间戳
import math  # 离线仿真正弦波
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout, QSizePolicy,
    QGraphicsDropShadowEffect, QScrollArea, QStackedWidget,
    QSplitter, QTextEdit, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QProgressBar,
    QTabWidget, QAction, QMenu, QInputDialog, QMessageBox,
    QRadioButton, QButtonGroup,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSlider, QListWidget, QDialog,  # DatasetModule viewer
    QTreeWidget, QTreeWidgetItem,  # 硬件工具箱设备树
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QTimer, QUrl, QDateTime, QThread  # QThread 用于 Rerun 后台线程
from PyQt5.QtGui import (
    QFont, QColor, QCursor, QPainter, QLinearGradient, QBrush,
    QPainterPath, QPen, QDesktopServices, QPixmap  # 新增 QCursor, QDesktopServices, QPixmap
)

# Z-MAX 版本同步模块
from version_sync import VersionSyncWidget

# 硬件仿真引擎 (System 0 硬件工具箱)
from hardware_simulator import HardwareSimulator, Z700_JOINTS, Z700_CAMERAS, Z700_ROS2_NODES, get_simulator
from hardware_simulator import HardwareDiscoveryThread
from hardware_simulator import ReplayEngine, ReplayThread


# ============================================================
# 通用工具函数
# ============================================================
def open_ppt_with_libreoffice(ppt_path):
    """
    使用LibreOffice打开PPT文件，绕过用户配置目录权限问题
    通过创建临时用户安装目录解决 LibreOffice 权限错误
    """
    import os
    import subprocess
    
    # 检查文件是否存在
    if not os.path.exists(ppt_path):
        print(f"[ERROR] PPT文件不存在: {ppt_path}")
        return
    
    # 创建临时LibreOffice用户配置目录
    lo_user_dir = "/tmp/lo_user_ppt"
    os.makedirs(lo_user_dir, exist_ok=True)
    
    try:
        # WSL: 将 Linux 路径转为 Windows 路径
        try:
            r = subprocess.run(["wslpath", "-w", ppt_path], capture_output=True, text=True, timeout=2)
            if r.stdout.strip():
                ppt_path = r.stdout.strip()
        except:
            pass
        
        cmd = ["soffice", f"-env:UserInstallation=file://{lo_user_dir}", "--norestore", ppt_path]
        subprocess.Popen(cmd, start_new_session=True)
        print(f"[OK] LibreOffice已启动，打开文件: {ppt_path}")
    except Exception as e:
        print(f"[ERROR] 启动LibreOffice失败: {e}")


# ============================================================
# 全局颜色
# ============================================================
C_BG        = "#0d1117"
C_BG2       = "#161b22"
C_CARD      = "#1c2333"
C_HOVER     = "#252d3a"
C_BLUE      = "#58a6ff"
C_GREEN     = "#3fb950"
C_ORANGE    = "#d29922"
C_RED       = "#f85149"
C_PURPLE    = "#bc8cff"
C_CYAN      = "#39d2c0"
C_YELLOW    = "#e3b341"
C_WHITE     = "#e6edf3"
C_GRAY      = "#8b949e"
C_DIM       = "#484f58"
C_BORDER    = "#30363d"

# Z-MAX系统层级颜色
SYS0_COLOR  = C_ORANGE   # 基石层
SYS11_COLOR = C_BLUE     # 动作系统
SYS12_COLOR = C_PURPLE   # 引导系统
SYS2_COLOR  = C_GREEN    # L4大脑


# ============================================================
# 通用样式辅助
# ============================================================
def card_style(bg=C_CARD, border=C_BORDER, radius=12, pad=16):
    return f"background:{bg}; border:1px solid {border}; border-radius:{radius}px; padding:{pad}px;"


# ============================================================
# 系统层级状态卡片 (侧边栏用)
# ============================================================
class SystemLayerCard(QFrame):
    """Z-MAX 系统层级状态卡片"""
    clicked = pyqtSignal(str)

    def __init__(self, layer_id, label, subtitle, color, components, parent=None):
        super().__init__(parent)
        self.layer_id = layer_id
        self.color = color
        # 不设置固定高度，让内容自适应
        self.setCursor(Qt.PointingHandCursor)
        self._build(label, subtitle, components)

    def _build(self, label, subtitle, components):
        self.setStyleSheet(f"""
            SystemLayerCard {{
                background:{C_CARD};
                border:2px solid {self.color};
                border-radius:8px;
            }}
        """)

        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(12, 8, 12, 8)

        # 层级标识
        head = QHBoxLayout()
        dot = QLabel("●")
        dot.setFont(QFont("Arial", 8))
        dot.setStyleSheet(f"color:{self.color}; background:transparent; border:none;")
        head.addWidget(dot)
        title = QLabel(label)
        title.setFont(QFont("Arial", 12, QFont.Bold))
        title.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:0;")
        head.addWidget(title)
        head.addStretch()
        layout.addLayout(head)

        # 副标题
        sub = QLabel(subtitle)
        sub.setFont(QFont("Arial", 9))
        sub.setStyleSheet(f"color:{self.color}; background:transparent; border:none; margin:0; padding:0;")
        layout.addWidget(sub)

        # 组件列表
        comp = QLabel(components)
        comp.setFont(QFont("Consolas", 9))
        comp.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:0;")
        comp.setWordWrap(True)
        layout.addWidget(comp)

        self.setLayout(layout)

    def enterEvent(self, e):
        self.setStyleSheet(f"""
            SystemLayerCard {{
                background:{C_HOVER};
                border:2px solid {self.color};
                border-radius:8px;
            }}
        """)

    def leaveEvent(self, e):
        self.setStyleSheet(f"""
            SystemLayerCard {{
                background:{C_CARD};
                border:2px solid {self.color};
                border-radius:8px;
            }}
        """)

    def mousePressEvent(self, e):
        self.clicked.emit(self.layer_id)


# ============================================================
# 侧边栏: Z-MAX 系统架构
# ============================================================
class SystemSidebar(QFrame):
    layer_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setStyleSheet(f"background:{C_BG2}; border-right:1px solid {C_BORDER};")
        self._build()

    def _build(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(12, 16, 12, 16)

        # 标题
        logo_row = QHBoxLayout()
        icon = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        pixmap = QPixmap(icon_path)
        icon.setPixmap(pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon.setStyleSheet("background:transparent; border:none; margin:0;")
        logo_row.addWidget(icon)
        title = QLabel("XSpace Studio")  # 改名：LeRobot Studio → XSpace Studio
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:2px 0;")
        logo_row.addWidget(title)
        layout.addLayout(logo_row)

        # 返回按钮
        home_btn = QPushButton("← 返回首页")
        home_btn.setFont(QFont("Arial", 10))
        home_btn.setStyleSheet(f"""
            QPushButton {{ background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px; margin:0; }}
            QPushButton:hover {{ color:{C_WHITE}; border-color:{C_BLUE}; }}
        """)
        home_btn.clicked.connect(lambda: self.layer_clicked.emit("home"))
        layout.addWidget(home_btn)

        layout.addSpacing(8)

        sep_label = QLabel("模块库")  # 改名：Z-MAX 系统架构 → 模块库，后续支持拖拽到主窗口
        sep_label.setFont(QFont("Arial", 10, QFont.Bold))
        sep_label.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0; padding:4px 0;")
        layout.addWidget(sep_label)

        # System 2
        self.sys2 = SystemLayerCard(
            "sys2", "System 2", "L4级大脑 · 5G/有线",
            SYS2_COLOR, "云端智能体 · 任务拆解\n动态调度Sys-11/Sys-12"
        )
        self.sys2.clicked.connect(self.layer_clicked.emit)
        layout.addWidget(self.sys2)

        # Sys-12
        self.sys12 = SystemLayerCard(
            "sys12", "Sys-12 引导系统", "引导 · LeWorldModel · 15M",
            SYS12_COLOR, "3D空间推理 · 10-20Hz\n目标位姿引导 · Jetson Orin"
        )
        self.sys12.clicked.connect(self.layer_clicked.emit)
        layout.addWidget(self.sys12)

        # Sys-11
        self.sys11 = SystemLayerCard(
            "sys11", "Sys-11 动作系统", "动作 · SmolVLA · 500M",
            SYS11_COLOR, "端到端VLA · 100Hz+\n精细力控 · 实时Linux"
        )
        self.sys11.clicked.connect(self.layer_clicked.emit)
        layout.addWidget(self.sys11)

        # System 0
        self.sys0 = SystemLayerCard(
            "sys0", "System 0", "L2基石 · EtherCAT",
            SYS0_COLOR, "安全层 · HAL驱动层\n运动学正逆解 · 急停"
        )
        self.sys0.clicked.connect(self.layer_clicked.emit)
        layout.addWidget(self.sys0)

        layout.addStretch()

        # 底部信息
        info = QLabel("0.5.2-zmax.1.0.1\nLeRobot · Z-MAX")
        info.setFont(QFont("Consolas", 8))
        info.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        self.setLayout(layout)


# ============================================================
# 首页模块卡片
# ============================================================
class ModuleCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, mid, icon, title, subtitle, desc, sys_label, color, parent=None):
        super().__init__(parent)
        self.mid = mid
        self.color = color
        self.setFixedHeight(230)  # 增大：行间距 5→14 后需要更多空间，避免标题白色字显示不全
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._build(icon, title, subtitle, desc, sys_label)

    def _build(self, icon, title, subtitle, desc, sys_label):
        self.setStyleSheet(card_style(C_CARD, C_BORDER, 12, 20))
        layout = QVBoxLayout()
        layout.setSpacing(14)  # 增大：原为5，功能卡内容行间距太小
        layout.setContentsMargins(16, 14, 16, 14)

        # 顶行
        top = QHBoxLayout()
        ic = QLabel(icon)
        ic.setFont(QFont("Segoe UI Emoji", 22))
        ic.setStyleSheet(f"color:{self.color}; background:transparent; border:none; margin:0;")
        top.addWidget(ic)
        top.addStretch()
        badge = QLabel(sys_label)
        badge.setFont(QFont("Consolas", 8, QFont.Bold))
        badge.setStyleSheet(f"color:white; background:{self.color}55; border:1px solid {self.color}aa; border-radius:4px; padding:3px 8px; margin:0;")  # 高对比度方案：纯白文字 + 半透明彩底，确保所有系统层级的badge都清晰可读
        top.addWidget(badge)
        layout.addLayout(top)

        t = QLabel(title)
        t.setFont(QFont("Arial", 14, QFont.Bold))
        t.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:2px 0;")
        layout.addWidget(t)

        s = QLabel(subtitle)
        s.setFont(QFont("Arial", 9))
        s.setStyleSheet(f"color:{self.color}; background:transparent; border:none; margin:0; padding:0;")
        layout.addWidget(s)

        d = QLabel(desc)
        d.setFont(QFont("Arial", 9))
        d.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:0;")
        d.setWordWrap(True)
        layout.addWidget(d)

        layout.addStretch()

        arrow = QLabel("点击进入 →")
        arrow.setFont(QFont("Arial", 9))
        arrow.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0; padding:0;")
        layout.addWidget(arrow)

        self.setLayout(layout)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(16); shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)

    def enterEvent(self, e):
        self.setStyleSheet(card_style(C_HOVER, self.color, 12, 20))

    def leaveEvent(self, e):
        self.setStyleSheet(card_style(C_CARD, C_BORDER, 12, 20))

    def mousePressEvent(self, e):
        self.clicked.emit(self.mid)


# ============================================================
# 系统架构流程条（垂直分层：Sys0底层 → Sys11+12中层并列 → Sys2顶层）
# ============================================================
class ArchFlowBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:8px;")
        self._build()

    def _build(self):
        root = QVBoxLayout()
        root.setSpacing(0)
        root.setContentsMargins(20, 14, 20, 24)

        # 标题放在最上面
        caption = QLabel("Z-MAX 三层解耦架构")
        caption.setFont(QFont("Arial", 10, QFont.Bold))
        caption.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:0 0 8px 0;")
        caption.setAlignment(Qt.AlignCenter)
        root.addWidget(caption)

        # ---- Layer 3: System 2 (顶层) ----
        self._add_layer_box(root, "☁️", "System 2", "L4大脑 · 云端智能体 · 任务拆解与调度", SYS2_COLOR)

        # ---- 箭头 ↓ 到中间层 ----
        self._add_arrow(root, "↕")

        # ---- Layer 2: Sys-11 + Sys-12 并列 (中间层) ----
        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)

        # Sys-11 左（自适应宽度）
        mid_row.addWidget(self._make_stage_box(
            "🧠", "SYS-11 动作系统", "L3 VLA多模态 · SmolVLA 500M", SYS11_COLOR), 1)
        # 双向箭头
        link = QLabel("⟷")
        link.setFont(QFont("Arial", 18))
        link.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0;")
        link.setAlignment(Qt.AlignCenter)
        mid_row.addWidget(link)
        # Sys-12 右（自适应宽度）
        mid_row.addWidget(self._make_stage_box(
            "🌐", "SYS-12 引导系统", "L4 世界模型 · LeWorldModel 15M", SYS12_COLOR), 1)

        mid_container = QWidget()
        mid_container.setStyleSheet("background:transparent; border:none;")
        mid_container.setFixedHeight(88)
        mid_container.setLayout(mid_row)
        root.addWidget(mid_container)

        # ---- 箭头 ↓ 到底层 ----
        self._add_arrow(root, "↕")

        # ---- Layer 1: System 0 (底层) ----
        self._add_layer_box(root, "⚙️", "System 0", "L2基石 · EtherCAT · 安全层 · HAL驱动", SYS0_COLOR)

        self.setLayout(root)

    def _add_layer_box(self, parent_layout, icon, name, desc, color):
        """添加一个全宽层级框"""
        box = QFrame()
        box.setFixedHeight(52)
        box.setStyleSheet(f"background:{C_CARD}; border:1px solid {color}88; border-radius:8px;")
        bl = QHBoxLayout()
        bl.setSpacing(12)
        bl.setContentsMargins(14, 6, 14, 6)

        ic = QLabel(icon)
        ic.setFont(QFont("Segoe UI Emoji", 18))
        ic.setStyleSheet(f"color:{color}; background:transparent; border:none; margin:0;")
        bl.addWidget(ic)

        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Arial", 13, QFont.Bold))
        name_lbl.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:2px 0;")
        bl.addWidget(name_lbl)

        bl.addSpacing(12)

        desc_lbl = QLabel(desc)
        desc_lbl.setFont(QFont("Arial", 10))
        desc_lbl.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:2px 0;")
        bl.addWidget(desc_lbl)

        bl.addStretch()

        box.setLayout(bl)
        parent_layout.addWidget(box)

    def _add_arrow(self, parent_layout, symbol):
        """添加垂直连接箭头"""
        arrow = QLabel(symbol)
        arrow.setFont(QFont("Arial", 16, QFont.Bold))
        arrow.setFixedHeight(22)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0;")
        parent_layout.addWidget(arrow)

    def _make_stage_box(self, icon_text, title, subtitle, color):
        """创建中间层的并排框（自适应宽度）"""
        box = QFrame()
        box.setStyleSheet(f"background:{C_CARD}; border:1px solid {color}88; border-radius:8px;")

        bl = QHBoxLayout()
        bl.setSpacing(12)
        bl.setContentsMargins(14, 12, 14, 12)

        ic = QLabel(icon_text)
        ic.setFont(QFont("Segoe UI Emoji", 18))
        ic.setStyleSheet(f"color:{color}; background:transparent; border:none; margin:0;")
        ic.setAlignment(Qt.AlignVCenter)
        bl.addWidget(ic)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(14)  # 行间距加大
        text_layout.setContentsMargins(0, 4, 0, 4)  # 上下边距加大
        
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Arial", 11, QFont.Bold))
        title_lbl.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:3px 0;")
        title_lbl.setFixedHeight(28)  # 增加高度
        text_layout.addWidget(title_lbl)
        
        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setFont(QFont("Arial", 9))
        subtitle_lbl.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:3px 0;")
        subtitle_lbl.setFixedHeight(22)  # 增加高度
        text_layout.addWidget(subtitle_lbl)

        bl.addLayout(text_layout, 1)
        box.setLayout(bl)
        return box


# ============================================================
# 产品迭代路线图 (Product Roadmap) — 可点击查看配置
# ============================================================
class PhaseCardButton(QFrame):
    """可点击的迭代阶段卡片"""
    clicked = pyqtSignal(dict)

    def __init__(self, phase_data, parent=None):
        super().__init__(parent)
        self.phase_data = phase_data
        self.color = phase_data["color"]
        self.setCursor(Qt.PointingHandCursor)
        self._build(phase_data)

    def _build(self, p):
        self.setStyleSheet(f"""
            PhaseCardButton {{
                background:{C_CARD};
                border:2px solid {self.color}66;
                border-radius:8px;
            }}
            PhaseCardButton:hover {{
                background:{C_HOVER};
                border:2px solid {self.color};
            }}
        """)

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(12, 10, 12, 10)

        # Phase 标识 + 时间
        header = QHBoxLayout()
        phase_lbl = QLabel(p["phase"])
        phase_lbl.setFont(QFont("Consolas", 8, QFont.Bold))
        phase_lbl.setStyleSheet(f"color:{self.color}; background:{self.color}22; border:1px solid {self.color}44; border-radius:3px; padding:2px 6px;")
        header.addWidget(phase_lbl)
        header.addStretch()
        time_lbl = QLabel(p["time"])
        time_lbl.setFont(QFont("Consolas", 8))
        time_lbl.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0;")
        header.addWidget(time_lbl)
        layout.addLayout(header)

        # 标题
        title = QLabel(p["title"])
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:2px 0;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # 维度标签
        dim_lbl = QLabel(p["dims"])
        dim_lbl.setFont(QFont("Arial", 9))
        dim_lbl.setStyleSheet(f"color:{self.color}; background:transparent; border:none; margin:0; padding:0;")
        layout.addWidget(dim_lbl)

        # 描述
        desc_lbl = QLabel(p["desc"])
        desc_lbl.setFont(QFont("Arial", 9))
        desc_lbl.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:2px 0;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # KPI
        kpi_lbl = QLabel(p["kpi"])
        kpi_lbl.setFont(QFont("Consolas", 13, QFont.Bold))
        kpi_lbl.setStyleSheet(f"color:{self.color}; background:transparent; border:none; margin:0; padding:4px 0;")
        kpi_lbl.setAlignment(Qt.AlignRight)
        layout.addWidget(kpi_lbl)

        # 文件夹路径提示
        path_lbl = QLabel(f"📁 {p['folder']}")
        path_lbl.setFont(QFont("Consolas", 7))
        path_lbl.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0; padding:2px 0;")
        layout.addWidget(path_lbl)

        self.setLayout(layout)

    def enterEvent(self, e):
        self.setStyleSheet(f"""
            PhaseCardButton {{
                background:{C_HOVER};
                border:2px solid {self.color};
                border-radius:8px;
            }}
        """)

    def leaveEvent(self, e):
        self.setStyleSheet(f"""
            PhaseCardButton {{
                background:{C_CARD};
                border:2px solid {self.color}66;
                border-radius:8px;
            }}
        """)

    def mousePressEvent(self, e):
        self.clicked.emit(self.phase_data)


class ProductRoadmapWidget(QFrame):
    """Z-MAX 产品迭代路线图：System1 → Sys-11 → Sys-12 → System2"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        # 获取 policies 目录相对路径
        self._policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "src", "lerobot", "policies"
        )
        self._build()

    def _build(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # 维度说明
        dim_bar = QHBoxLayout()
        dim_bar.setSpacing(16)
        dims = [
            ("Z", "潜空间", SYS12_COLOR),
            ("M", "多模态", C_CYAN),
            ("A", "Action", SYS11_COLOR),
            ("X", "eXpert", SYS2_COLOR),
        ]
        for letter, meaning, color in dims:
            tag = QLabel(f"{letter} = {meaning}")
            tag.setFont(QFont("Arial", 9, QFont.Bold))
            tag.setStyleSheet(f"color:{color}; background:{color}18; border:1px solid {color}55; border-radius:4px; padding:3px 10px;")
            dim_bar.addWidget(tag)
        dim_bar.addStretch()
        layout.addLayout(dim_bar)

        # 四个迭代阶段 - 横向可点击卡片
        phases_row = QHBoxLayout()
        phases_row.setSpacing(6)

        phases = [
            {
                "phase": "Phase 0",
                "title": "System0 · 原子功能",
                "time": "2026 Q3",
                "dims": "A 标准接口",
                "desc": "人工编排原子功能\n流程验证·数据采集基线",
                "color": SYS0_COLOR,
                "kpi": "L2基线",
                "folder": "zmax_sys1",
                "config_file": "configuration_zmax_sys1.py",
            },
            {
                "phase": "Phase 1",
                "title": "系统1 · VTLA端到端",
                "time": "2026 Q4",
                "dims": "M + A",
                "desc": "自研VTLA多模态模型\n感知→动作端到端执行",
                "color": C_CYAN,
                "kpi": "±0.02mm",
                "folder": "zmax_sys1",
                "config_file": "configuration_zmax_sys1.py",
            },
            {
                "phase": "Phase 2",
                "title": "Sys-11 · Z潜空间泛化",
                "time": "2026 Q4",
                "dims": "Z 潜空间",
                "desc": "动作特征压缩泛化\n一脑多能 · 端侧部署",
                "color": SYS11_COLOR,
                "kpi": "<10ms",
                "folder": "zmax_sys11",
                "config_file": "configuration_zmax_sys11.py",
            },
            {
                "phase": "Phase 3",
                "title": "Sys-12 · 精细感知闭环",
                "time": "2027 Q1-Q2",
                "dims": "X + Z 扩展",
                "desc": "场景引导模型\n全域认知闭环",
                "color": SYS12_COLOR,
                "kpi": "99.2%",
                "folder": "zmax_sys12",
                "config_file": "configuration_zmax_sys12.py",
            },
            {
                "phase": "Phase 4",
                "title": "全域认知 · 全系统",
                "time": "2027+",
                "dims": "Z·M·A·X 全域",
                "desc": "多产线规模化复制\nL4全自主闭环",
                "color": SYS2_COLOR,
                "kpi": "7×24h",
                "folder": "zmax_system2",
                "config_file": "configuration_zmax_system2.py",
            },
        ]

        for i, p in enumerate(phases):
            card = PhaseCardButton(p)
            card.clicked.connect(self._on_phase_clicked)
            phases_row.addWidget(card, 1)

            if i < len(phases) - 1:
                arrow = QLabel("→")
                arrow.setFont(QFont("Arial", 16, QFont.Bold))
                arrow.setFixedWidth(20)
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; margin:0;")
                phases_row.addWidget(arrow)

        layout.addLayout(phases_row)
        self.setLayout(layout)

    def _read_config_file(self, folder, config_file):
        """读取配置文件内容"""
        config_path = os.path.join(self._policies_dir, folder, config_file)
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return f.read()
        alt_path = os.path.expanduser(f"~/xspace/lerobot-smolvla-lew/src/lerobot/policies/{folder}/{config_file}")
        if os.path.exists(alt_path):
            with open(alt_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def _list_folder_files(self, folder):
        """列出策略文件夹内文件"""
        folder_path = os.path.join(self._policies_dir, folder)
        if not os.path.isdir(folder_path):
            folder_path = os.path.expanduser(f"~/xspace/lerobot-smolvla-lew/src/lerobot/policies/{folder}")
        if os.path.isdir(folder_path):
            return sorted([f for f in os.listdir(folder_path) if not f.startswith('__') and not f.startswith('.')])
        return []

    def _parse_config_params(self, content):
        """从配置文件内容中解析参数（dataclass 字段）"""
        import re
        params = []
        current_section = "基础配置"
        for line in content.split('\n'):
            stripped = line.strip()
            # 检测分组注释: # === xxx === 或 # --- xxx ---
            sec_match = re.match(r'^#\s*[=\-]+\s*(.+?)\s*[=\-]*$', stripped)
            if sec_match:
                current_section = sec_match.group(1).strip()
                continue
            # 检测参数: name: type = value
            param_match = re.match(r'^(\w+)\s*:\s*(.+?)\s*=\s*(.+?)(?:\s*#.*)?$', stripped)
            if param_match:
                name, ptype, pval = param_match.group(1), param_match.group(2), param_match.group(3)
                # 清理默认值
                pval = pval.strip().rstrip(',')
                comment_match = re.search(r'#\s*(.+?)$', line)
                comment = comment_match.group(1) if comment_match else ""
                params.append((current_section, name, ptype, pval, comment))
        return params

    def _on_phase_clicked(self, phase_data):
        """点击阶段卡片 → 弹出暗色自定义弹窗，参数可视化表格"""
        from PyQt5.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QHeaderView
        from PyQt5.QtGui import QBrush

        folder = phase_data["folder"]
        config_file = phase_data["config_file"]
        color = phase_data["color"]

        # 读取配置
        content = self._read_config_file(folder, config_file)
        files = self._list_folder_files(folder)

        # 创建自定义暗色弹窗
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{phase_data['phase']} — {phase_data['title']} [{folder}/]")
        dialog.setFixedSize(780, 620)
        dialog.setStyleSheet(f"""
            QDialog {{
                background: #0d1117;
                border: 2px solid {color};
                border-radius: 8px;
            }}
        """)

        dlg_layout = QVBoxLayout()
        dlg_layout.setSpacing(8)
        dlg_layout.setContentsMargins(16, 12, 16, 12)

        # === 标题栏 ===
        title_row = QHBoxLayout()
        title_lbl = QLabel(f"{phase_data['phase']}: {phase_data['title']}")
        title_lbl.setFont(QFont("Arial", 15, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {C_WHITE}; background: transparent; border: none;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        # KPI badge
        kpi_badge = QLabel(f"⚡ {phase_data['kpi']}")
        kpi_badge.setFont(QFont("Consolas", 12, QFont.Bold))
        kpi_badge.setStyleSheet(f"color: {color}; background: {color}22; border: 1px solid {color}66; border-radius: 6px; padding: 4px 12px;")
        title_row.addWidget(kpi_badge)

        dim_badge = QLabel(phase_data["dims"])
        dim_badge.setFont(QFont("Arial", 10, QFont.Bold))
        dim_badge.setStyleSheet(f"color: {C_WHITE}; background: {color}44; border: 1px solid {color}88; border-radius: 6px; padding: 4px 10px;")
        title_row.addWidget(dim_badge)
        dlg_layout.addLayout(title_row)

        # === 文件列表 ===
        files_frame = QFrame()
        files_frame.setStyleSheet(f"background: {C_BG2}; border: 1px solid {C_BORDER}; border-radius: 6px;")
        fl = QHBoxLayout()
        fl.setContentsMargins(10, 6, 10, 6)
        fl.addWidget(QLabel(f"📁 {folder}/"))
        for fn in files:
            tag = QLabel(fn)
            tag.setFont(QFont("Consolas", 9))
            tag.setStyleSheet(f"color: {C_GRAY}; background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 3px; padding: 2px 8px;")
            fl.addWidget(tag)
        fl.addStretch()
        files_frame.setLayout(fl)
        dlg_layout.addWidget(files_frame)

        # === 参数可视化表格 ===
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{ background: {C_BG}; border: 1px solid {C_BORDER}; border-radius: 6px; }}
            QTabBar::tab {{ background: {C_CARD}; color: {C_GRAY}; padding: 6px 16px; border: 1px solid {C_BORDER}; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
            QTabBar::tab:selected {{ background: {C_BG2}; color: {C_WHITE}; border-bottom: 2px solid {color}; }}
        """)

        if content:
            params = self._parse_config_params(content)

            # --- Tab 1: 参数表格 ---
            table = QTableWidget()
            table.setStyleSheet(f"""
                QTableWidget {{ background: {C_BG}; color: {C_WHITE}; border: none; gridline-color: {C_BORDER}; }}
                QTableWidget::item {{ padding: 4px 8px; }}
                QTableWidget::item:selected {{ background: {color}33; }}
                QHeaderView::section {{ background: {C_BG2}; color: {color}; border: 1px solid {C_BORDER}; padding: 4px 8px; font-weight: bold; }}
                QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}
                QScrollBar::handle:vertical {{ background: {C_DIM}; border-radius: 4px; }}
            """)
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(["分类", "参数名", "类型", "值", "说明"])
            table.setRowCount(len(params))

            prev_section = ""
            for row, (section, name, ptype, pval, comment) in enumerate(params):
                items = [
                    (section if section != prev_section else "", f"color: {color};"),
                    (name, f"color: {C_WHITE}; font-family: Consolas; font-weight: bold;"),
                    (ptype, f"color: {C_CYAN}; font-family: Consolas;"),
                    (pval, f"color: {C_GREEN}; font-family: Consolas; font-weight: bold;"),
                    (comment, f"color: {C_GRAY}; font-size: 9pt;"),
                ]
                for col, (text, style) in enumerate(items):
                    item = QTableWidgetItem(str(text))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    # 设置样式
                    if col <= 1:
                        item.setFont(QFont("Consolas" if col == 1 else "Arial", 9 if col > 0 else 8))
                    elif col == 2:
                        item.setFont(QFont("Consolas", 8))
                    elif col == 3:
                        item.setFont(QFont("Consolas", 9, QFont.Bold))
                    elif col == 4:
                        item.setFont(QFont("Arial", 8))

                    # 颜色
                    if col == 0 and text:
                        item.setForeground(QBrush(QColor(color)))
                    elif col == 1:
                        item.setForeground(QBrush(QColor(C_WHITE)))
                    elif col == 2:
                        item.setForeground(QBrush(QColor(C_CYAN)))
                    elif col == 3:
                        item.setForeground(QBrush(QColor(C_GREEN)))
                    elif col == 4:
                        item.setForeground(QBrush(QColor(C_GRAY)))

                    table.setItem(row, col, item)

                prev_section = section

            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
            table.verticalHeader().setVisible(False)
            tab_widget.addTab(table, f"📊 参数表格 ({len(params)})")

            # --- Tab 2: 源码 ---
            code_view = QTextEdit()
            code_view.setReadOnly(True)
            code_view.setFont(QFont("Consolas", 9))
            code_view.setStyleSheet(f"""
                QTextEdit {{ background: #0a0e14; color: {C_WHITE}; border: none; }}
                QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}
                QScrollBar::handle:vertical {{ background: {C_DIM}; border-radius: 4px; }}
            """)
            code_view.setPlainText(content)
            tab_widget.addTab(code_view, "📝 源码")

        else:
            err_lbl = QLabel("⚠️ 配置文件未找到")
            err_lbl.setFont(QFont("Arial", 12))
            err_lbl.setStyleSheet(f"color: {C_RED}; background: {C_CARD}; padding: 20px; border-radius: 8px;")
            err_lbl.setAlignment(Qt.AlignCenter)
            tab_widget.addTab(err_lbl, "错误")

        dlg_layout.addWidget(tab_widget)

        # === 底部按钮 ===
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFont(QFont("Arial", 10, QFont.Bold))
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: {color}; color: white; border: none; border-radius: 6px; padding: 8px 24px; }}
            QPushButton:hover {{ opacity: 0.8; }}
        """)
        close_btn.clicked.connect(dialog.close)
        btn_row.addWidget(close_btn)
        dlg_layout.addLayout(btn_row)

        dialog.setLayout(dlg_layout)
        dialog.exec_()


# ============================================================
# 首页页面
# ============================================================
class HomeWidget(QWidget):
    module_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG};")
        self._build()

    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        scroll.setStyleSheet(scroll.styleSheet() + "QScrollBar{background:transparent;}")

        page = QWidget()
        page.setStyleSheet(f"background:{C_BG};")
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(32, 24, 32, 24)

        # --- Hero ---
        hero = self._hero()
        layout.addWidget(hero)

        # --- 架构流程 ---
        lbl1 = QLabel("系统架构  Architecture")
        lbl1.setFont(QFont("Arial", 11, QFont.Bold))
        lbl1.setStyleSheet(f"color:{C_GRAY};")
        layout.addWidget(lbl1)
        layout.addWidget(ArchFlowBar())

        # --- 产品迭代路线图 ---
        lbl_roadmap = QLabel("产品迭代  Roadmap")
        lbl_roadmap.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_roadmap.setStyleSheet(f"color:{C_GRAY};")
        layout.addWidget(lbl_roadmap)
        layout.addWidget(ProductRoadmapWidget())

        # --- 模块卡片 ---
        lbl2 = QLabel("功能模块  Modules")
        lbl2.setFont(QFont("Arial", 11, QFont.Bold))
        lbl2.setStyleSheet(f"color:{C_GRAY};")
        layout.addWidget(lbl2)
        layout.addWidget(self._modules_grid())

        # --- 状态统计 ---
        lbl3 = QLabel("项目状态  Status")
        lbl3.setFont(QFont("Arial", 11, QFont.Bold))
        lbl3.setStyleSheet(f"color:{C_GRAY};")
        layout.addWidget(lbl3)
        layout.addWidget(self._stats_bar())

        layout.addStretch()
        page.setLayout(layout)
        scroll.setWidget(page)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def _hero(self):
        frame = QFrame()
        frame.setStyleSheet(card_style(C_BG2, C_BORDER, 12, 0))
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        row = QHBoxLayout()
        # 首页大logo，跟标题"Z-MAX"20pt字号匹配  # 新增：首页hero区域logo
        hero_icon = QLabel()  # 新增：首页hero区域logo
        hero_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")  # 新增：首页hero区域logo
        hero_pixmap = QPixmap(hero_icon_path)  # 新增：首页hero区域logo
        hero_icon.setPixmap(hero_pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))  # 新增：48x48匹配20pt字号
        hero_icon.setStyleSheet("background:transparent; border:none; margin:0; padding:4px 0;")  # 新增：首页hero区域logo
        row.addWidget(hero_icon)  # 新增：首页hero区域logo
        t = QLabel("Z-MAX 多模态动作专家")
        t.setFont(QFont("Arial", 20, QFont.Bold))
        t.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none; margin:0; padding:4px 0;")
        row.addWidget(t)
        row.addStretch()
        b = QPushButton("● smolvla_lew")  # 改为按钮，点击打开 GitHub 仓库
        b.setFont(QFont("Arial", 9, QFont.Bold))
        b.setStyleSheet(f"background:{SYS12_COLOR}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/MikeBMW/lerobot-smolvla-lew.git")))  # 打开GitHub链接
        row.addWidget(b)

        # 同步按钮：将本地GUI代码推送到GitHub  # 新增同步按钮
        sync_btn = QPushButton("🔄 同步到GitHub")  # 新增同步按钮
        sync_btn.setFont(QFont("Arial", 9, QFont.Bold))
        sync_btn.setStyleSheet(f"background:{C_GREEN}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        sync_btn.setCursor(Qt.PointingHandCursor)
        sync_btn.clicked.connect(self._sync_to_github)  # 调用同步方法
        row.addWidget(sync_btn)  # 新增同步按钮

        # ====== 版本同步按钮（快速跳转到版本管理页面） ======
        ver_btn = QPushButton("📦 版本同步")
        ver_btn.setFont(QFont("Arial", 9, QFont.Bold))
        ver_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        ver_btn.setCursor(Qt.PointingHandCursor)
        ver_btn.setToolTip("检查 LeRobot 上游更新 · 安全同步 · 版本管理")
        ver_btn.clicked.connect(lambda: self.module_clicked.emit("version"))
        row.addWidget(ver_btn)

        # ====== 新增：解决方案文档按钮（保留Markdown按钮） ======
        doc_btn = QPushButton("📋 解决方案v1.0.4")
        doc_btn.setFont(QFont("Arial", 9, QFont.Bold))
        doc_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        doc_btn.setCursor(Qt.PointingHandCursor)
        doc_btn.setToolTip("打开产品解决方案文档 (Markdown)")
        doc_btn.clicked.connect(self._open_spec_doc)
        row.addWidget(doc_btn)

        # ====== 新增：PPT汇报按钮 ======
        doc_btn = QPushButton("📊 PPT汇报")
        doc_btn.setFont(QFont("Arial", 9, QFont.Bold))
        doc_btn.setStyleSheet(f"background:{C_ORANGE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        doc_btn.setCursor(Qt.PointingHandCursor)
        doc_btn.setToolTip("打开管理层汇报PPT (8页幻灯片)")
        doc_btn.clicked.connect(lambda: open_ppt_with_libreoffice(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'BRAND-品牌注册材料.pptx')))
        row.addWidget(doc_btn)

        # ====== 分享按钮 ======
        share_btn = QPushButton("📱 分享")
        share_btn.setFont(QFont("Arial", 9, QFont.Bold))
        share_btn.setStyleSheet(f"background:{C_PURPLE}; color:white; border-radius:10px; padding:4px 12px; margin:0; cursor:pointer;")
        share_btn.setCursor(Qt.PointingHandCursor)
        share_btn.setToolTip("生成二维码 · 扫码查看Z-MAX项目")
        share_btn.clicked.connect(self._show_share_qr)
        row.addWidget(share_btn)

        layout.addLayout(row)

        desc = QLabel("高速光模块精细操作具身机器人 · L4级全自主 · 1ms实时控制 · 三层解耦架构")
        desc.setFont(QFont("Arial", 11))
        desc.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:2px 0;")
        layout.addWidget(desc)

        # KPI
        kpi = QHBoxLayout()
        kpi.setSpacing(36)
        for val, lbl, clr in [
            ("±0.02mm", "定位精度·Sys-11", SYS11_COLOR),
            ("99.2%", "连续成功率", C_GREEN),
            ("<10ms", "推理延迟·Sys-11", SYS11_COLOR),
            ("15M", "LeWorldModel·Sys-12", SYS12_COLOR),
            ("1ms", "控制周期·Sys-0", SYS0_COLOR),
        ]:
            col = QVBoxLayout(); col.setSpacing(1)
            v = QLabel(val)
            v.setFont(QFont("Arial", 16, QFont.Bold))
            v.setStyleSheet(f"color:{clr}; background:transparent; border:none;")
            col.addWidget(v)
            l = QLabel(lbl)
            l.setFont(QFont("Arial", 8))
            l.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none;")
            col.addWidget(l)
            kpi.addLayout(col)
        kpi.addStretch()
        layout.addLayout(kpi)

        frame.setLayout(layout)
        return frame

    def _modules_grid(self):
        grid = QGridLayout()
        grid.setSpacing(12)
        modules = [
            ("dataset",  "📊", "数据集管理",   "System 2 · L4大脑",   "任务规划 · 数据飞轮\n.lrobot格式 · HF Datasets", SYS2_COLOR),
            ("training", "🏋️", "训练控制台",   "Sys-11 · 动作系统",   "SmolVLA 500M + DiT-B\n端到端VLA训练",            SYS11_COLOR),
            ("evaluation","✅", "评估分析",     "Sys-12 · 引导系统",   "LeWorldModel验证\n动作回放 · 成功率分析",        SYS12_COLOR),
            ("hardware", "🔧", "硬件工具箱",   "System 0 · L2基石",   "电机·相机·力控·急停\nEtherCAT驱动 · HAL层",     SYS0_COLOR),
            ("config",   "⚙️", "配置中心",     "Sys-11 + Sys-12",     "SmolVLALewConfig\n三层参数可视化编辑",          SYS11_COLOR),
            ("monitor",  "📈", "实时监控",     "Sys-11 + Sys-12",     "训练曲线 · GPU状态\n推理延迟 · 力控曲线",        SYS12_COLOR),
            ("plugging", "🤖", "插拔场景",     "Z700 · 双臂协同",     "Z700轮式双臂 · VTLA插拔\nROI量化 · 力控闭环",     ROI_ACCENT),
            ("version",  "🔄", "版本同步",     "LeRobot · 上游管理",  "检查上游更新 · 安全同步\n版本状态 · 冲突检测",  C_ORANGE),
        ]
        for i, (mid, icon, title, syslbl, desc, color) in enumerate(modules):
            card = ModuleCard(mid, icon, title, syslbl, desc, syslbl.split("·")[0].strip(), color)
            card.clicked.connect(self.module_clicked.emit)
            grid.addWidget(card, i // 3, i % 3)
        container = QWidget()
        container.setStyleSheet("background:transparent;")
        container.setLayout(grid)
        return container

    def _stats_bar(self):
        f = QFrame()
        f.setFixedHeight(64)
        f.setStyleSheet(card_style(C_BG2, C_BORDER, 8, 0))
        layout = QHBoxLayout()
        layout.setSpacing(36)
        layout.setContentsMargins(20, 8, 20, 8)
        for lbl, val in [("策略", "19"), ("脚本", "20"), ("数据集", "2"),
                         ("Checkpoints", "3"), ("训练进度", "L3 POC")]:
            col = QVBoxLayout(); col.setSpacing(1)
            l = QLabel(lbl); l.setFont(QFont("Arial", 8))
            l.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none;")
            col.addWidget(l)
            v = QLabel(val); v.setFont(QFont("Arial", 11, QFont.Bold))
            v.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
            col.addWidget(v)
            layout.addLayout(col)
        layout.addStretch()
        f.setLayout(layout)
        return f

    def _sync_to_github(self):  # 新增：同步GUI代码到GitHub的方法
        """将本地 tools/gui/ 目录的代码推送到 GitHub 仓库"""
        repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 定位到仓库根目录（gui→tools→repo_root）

        try:
            # 第一步：git add
            r = subprocess.run(["git", "add", "tools/gui/"],
                               capture_output=True, text=True, cwd=repo_dir, timeout=30)
            if r.returncode != 0:
                QMessageBox.warning(self, "同步失败", f"git add 出错:\n{r.stderr}")
                return

            # 第二步：检查是否有变更需要提交
            r = subprocess.run(["git", "status", "--porcelain", "tools/gui/"],
                               capture_output=True, text=True, cwd=repo_dir, timeout=30)
            if not r.stdout.strip():
                QMessageBox.information(self, "无需同步", "本地 GUI 代码无变更，不需要推送。")
                return

            # 第三步：git commit
            r = subprocess.run(["git", "commit", "-m", "sync: 同步GUI界面代码更新"],
                               capture_output=True, text=True, cwd=repo_dir, timeout=30)
            if r.returncode != 0:
                QMessageBox.warning(self, "同步失败", f"git commit 出错:\n{r.stderr}")
                return

            # 第四步：git push（尝试直接推送）
            r = subprocess.run(["git", "push", "origin", "main"],
                               capture_output=True, text=True, cwd=repo_dir, timeout=60)

            if r.returncode != 0:
                # 推送失败（通常是认证问题），弹出token输入框
                token, ok = QInputDialog.getText(
                    self, "GitHub Token",
                    "需要 GitHub Personal Access Token 才能推送。\n"
                    "请访问 https://github.com/settings/tokens 生成 token\n\n"
                    "输入 token（会自动保存供下次使用）:",
                    QLineEdit.Password
                )
                if ok and token.strip():
                    # 保存 token 到 ~/.git-credentials
                    cred_file = os.path.expanduser("~/.git-credentials")
                    with open(cred_file, "w") as f:
                        f.write(f"https://MikeBMW:{token.strip()}@github.com\n")
                    # 配置 credential helper
                    subprocess.run(["git", "config", "credential.helper", "store"],
                                   capture_output=True, cwd=repo_dir, timeout=10)
                    # 重试推送
                    r = subprocess.run(["git", "push", "origin", "main"],
                                       capture_output=True, text=True, cwd=repo_dir, timeout=60)
                    if r.returncode != 0:
                        QMessageBox.warning(self, "推送失败", f"推送仍然失败:\n{r.stderr}")
                        return

                else:
                    return  # 用户取消了

            QMessageBox.information(self, "同步成功",
                                    "✅ GUI 代码已成功推送到 GitHub!\n\n"
                                    "https://github.com/MikeBMW/lerobot-smolvla-lew")

        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "同步超时", "Git 操作超时，请检查网络连接。")
        except Exception as e:
            QMessageBox.warning(self, "同步异常", f"发生异常:\n{str(e)}")

    def _open_spec_doc(self):
        """打开解决方案文档 v1.0.4"""
        try:
            # 从当前文件位置向上两级到项目根目录，然后进入 docs 目录
            doc_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'docs', 'L2-Z-MAX解决方案-v1.0.4.md')
            # WSL: 复制到 Windows 临时目录再打开
            import shutil
            tmp_name = f"zmax_spec_{os.path.basename(doc_path)}"
            tmp_dir = "/mnt/c/Users/Admin/AppData/Local/Temp"
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, tmp_name)
            shutil.copy2(doc_path, tmp_path)
            win_path = tmp_path.replace("/mnt/c", "C:").replace("/", "\\")
            subprocess.run(["explorer.exe", win_path], check=True, timeout=5)
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"无法打开文档:\n{str(e)}")

    def _show_share_qr(self):
        """分享 — 飞书/微信远程对话配置入口"""
        from PyQt5.QtGui import QPixmap
        import qrcode, io, os
        
        # 检查 gateway 状态
        import subprocess
        gw_status = "未配置"
        try:
            r = subprocess.run(["hermes", "gateway", "status"], 
                capture_output=True, text=True, timeout=3)
            if "running" in r.stdout.lower():
                gw_status = "🟢 运行中"
            elif "installed" in r.stdout.lower():
                gw_status = "⏸ 已安装"
        except:
            pass
        
        # 二维码: 指向帮助页面
        qr_url = "https://hermes-agent.nousresearch.com/docs/user-guide/messaging/"
        
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        
        dlg = QDialog(self)
        dlg.setWindowTitle("📱 远程对话 · 飞书 / 微信")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(f"background:{C_BG};")
        dl = QVBoxLayout()
        dl.setSpacing(10)
        
        title = QLabel("📱 Z-MAX 远程对话")
        title.setFont(QFont("Arial", 15, QFont.Bold))
        title.setStyleSheet(f"color:{C_WHITE};")
        title.setAlignment(Qt.AlignCenter)
        dl.addWidget(title)
        
        status = QLabel(f"Gateway: {gw_status}")
        status.setStyleSheet(f"color:{C_GREEN if '运行' in gw_status else C_GRAY}; font-size:11px;")
        status.setAlignment(Qt.AlignCenter)
        dl.addWidget(status)
        
        # 说明
        guide = QLabel(
            "<b>让管理员通过飞书/微信远程与你对话</b><br><br>"
            "<b>步骤:</b><br>"
            "1. 终端运行: <code>hermes gateway setup</code><br>"
            "2. 选择 飞书(Feishu) 或 微信(Weixin)<br>"
            "3. 按提示填入 App ID / Secret<br>"
            "4. 运行: <code>hermes gateway run</code><br>"
            "5. 扫码下方二维码查看详细文档"
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(f"color:{C_WHITE}; font-size:10px; padding:8px; background:{C_BG2}; border-radius:4px;")
        dl.addWidget(guide)
        
        # 二维码
        qr_label = QLabel()
        qr_label.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio))
        qr_label.setAlignment(Qt.AlignCenter)
        dl.addWidget(qr_label)
        
        qr_hint = QLabel("扫码查看 Hermes Gateway 配置文档")
        qr_hint.setStyleSheet(f"color:{C_GRAY}; font-size:9px;")
        qr_hint.setAlignment(Qt.AlignCenter)
        dl.addWidget(qr_hint)
        
        # 按钮行
        btn_row = QHBoxLayout()
        
        setup_btn = QPushButton("⚙ 终端配置")
        setup_btn.setStyleSheet(f"background:{C_BLUE}; color:white; border:none; border-radius:4px; padding:8px 16px; font-weight:bold;")
        setup_btn.clicked.connect(lambda: [dlg.accept(), os.system("x-terminal-emulator -e 'hermes gateway setup' 2>/dev/null &")])
        btn_row.addWidget(setup_btn)
        
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(f"background:{C_DIM}; color:{C_GRAY}; border:none; border-radius:4px; padding:8px 16px;")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        dl.addLayout(btn_row)
        
        dlg.setLayout(dl)
        dlg.exec_()


# ============================================================
# 子模块基类
# ============================================================
class SubModuleWidget(QWidget):
    """子模块通用容器：标题 + 系统层级标识 + 内容区"""

    def __init__(self, title, sys_layers, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG};")
        self._title = title
        self._sys_layers = sys_layers  # [(label, color), ...]

    def _build_shell(self, content_widget):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 16, 24, 16)

        # 标题行
        head = QHBoxLayout()
        t = QLabel(self._title)
        t.setFont(QFont("Arial", 17, QFont.Bold))
        t.setStyleSheet(f"color:{C_WHITE}; border:none; background:transparent; margin:0; padding:4px 0;")
        head.addWidget(t)
        head.addStretch()

        # 系统层级标签（仅展示标识，不可点击）
        for lbl, clr in self._sys_layers:
            tag = QLabel(f"● {lbl}")
            tag.setFont(QFont("Arial", 10, QFont.Bold))
            tag.setStyleSheet(f"color:{clr}; background:{clr}22; border:1px solid {clr}44; border-radius:4px; padding:4px 10px; margin:0;")
            tag.setToolTip(f"所属系统层级: {lbl}")
            head.addWidget(tag)

        layout.addLayout(head)

        # 分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C_BORDER};")
        layout.addWidget(sep)

        layout.addWidget(content_widget)
        self.setLayout(layout)


# ============================================================
# 6个子模块
# ============================================================
class DatasetModule(SubModuleWidget):
    """数据集管理 — 支持 HuggingFace LeRobot 数据集浏览、下载、管理"""

    # 主要机器人开源数据集
    DATASETS = [
        {
            "repo_id": "lerobot/pusht",
            "name": "PushT",
            "robot": "Desk arm + gripper",
            "tasks": 1,
            "desc": "桌面推T块到目标位姿，经典IL基准",
            "tags": ["manipulation", "pushing", "benchmark"],
        },
        {
            "repo_id": "lerobot/xarm_lift_medium",
            "name": "xArm Lift",
            "robot": "xArm (6-DoF)",
            "tasks": 1,
            "desc": "xArm抓取并提升物体，中等难度",
            "tags": ["manipulation", "grasping"],
        },
        {
            "repo_id": "lerobot/xarm_lift_medium_image",
            "name": "xArm Lift (Image)",
            "robot": "xArm (6-DoF)",
            "tasks": 1,
            "desc": "xArm提升物体（仅图像输入，无本体状态）",
            "tags": ["manipulation", "vision-only"],
        },
        {
            "repo_id": "lerobot/aloha_sim_transfer_cube_human",
            "name": "ALOHA Sim Transfer Cube",
            "robot": "ALOHA (bimanual sim)",
            "tasks": 1,
            "desc": "双臂ALOHA仿真传递方块，sim-to-real基准",
            "tags": ["bimanual", "sim2real", "ALOHA"],
        },
        {
            "repo_id": "lerobot/aloha_sim_insertion_human",
            "name": "ALOHA Sim Insertion",
            "robot": "ALOHA (bimanual sim)",
            "tasks": 1,
            "desc": "双臂ALOHA仿真插入任务，sim-to-real基准",
            "tags": ["bimanual", "sim2real", "insertion"],
        },
        {
            "repo_id": "lerobot/koch_bimanual_folding",
            "name": "Koch Bimanual Folding",
            "robot": "Koch (bimanual real)",
            "tasks": 1,
            "desc": "双臂Koch折叠衣物，真实机器人数据",
            "tags": ["bimanual", "folding", "real-robot"],
        },
        {
            "repo_id": "lerobot/so100_pick_place",
            "name": "SO-100 Pick Place",
            "robot": "SO-100 (low-cost arm)",
            "tasks": 1,
            "desc": "低成本机械臂抓取放置，适合入门学习",
            "tags": ["low-cost", "pick-place", "education"],
        },
        {
            "repo_id": "lerobot/utokyo_pr2_tabletop_manipulation",
            "name": "PR2 Tabletop",
            "robot": "PR2 (full humanoid)",
            "tasks": 1,
            "desc": "PR2机器人在桌面上的操作任务",
            "tags": ["humanoid", "tabletop"],
        },
        {
            "repo_id": "lerobot/cmu_franka_exploration_dataset",
            "name": "CMU Franka Exploration",
            "robot": "Franka Emika Panda",
            "tasks": 1,
            "desc": "Franka机械臂探索数据集，CMU实验室",
            "tags": ["exploration", "franka"],
        },
        {
            "repo_id": "lerobot/nyu_rot_dataset",
            "name": "NYU Rot",
            "robot": "Rotatable fixture",
            "tasks": 1,
            "desc": "NYU旋转操作数据集，研究基准",
            "tags": ["research", "rotation"],
        },
        {
            "repo_id": "lerobot/metaworld_mt50",
            "name": "MetaWorld MT50",
            "robot": "Sawyer (sim)",
            "tasks": 50,
            "desc": "MetaWorld 50种桌面任务，多任务学习基准",
            "tags": ["multi-task", "meta-learning", "benchmark"],
        },
        {
            "repo_id": "lerobot/asu_table_top",
            "name": "ASU Table Top",
            "robot": "xArm (sim)",
            "tasks": 2,
            "desc": "ASU桌面操作数据集，含2种任务",
            "tags": ["tabletop", "research"],
        },
    ]

    def __init__(self):
        super().__init__("数据集管理", [("System 2", SYS2_COLOR)])
        body = QWidget()
        bl = QVBoxLayout()
        bl.setSpacing(10)

        # === 顶部信息栏 ===
        top_bar = QFrame()
        top_bar.setStyleSheet(f"background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:8px;")
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(14, 8, 14, 8)

        self._cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        cache_size = self._get_cache_size()

        cache_label = QLabel(f"本地缓存: {cache_size}  |  路径: {self._cache_dir}")
        cache_label.setFont(QFont("Consolas", 9))
        cache_label.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        top_layout.addWidget(cache_label)
        top_layout.addStretch()

        refresh_btn = QPushButton("🔄 刷新缓存状态")
        refresh_btn.setFont(QFont("Arial", 9))
        refresh_btn.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 12px;")
        refresh_btn.clicked.connect(self._refresh_cache_status)
        top_layout.addWidget(refresh_btn)

        clean_btn = QPushButton("🗑 清理全部缓存")
        clean_btn.setFont(QFont("Arial", 9))
        clean_btn.setStyleSheet(f"background:{C_RED}33; color:{C_RED}; border:1px solid {C_RED}55; border-radius:4px; padding:4px 12px;")
        clean_btn.clicked.connect(self._clean_all_cache)
        top_layout.addWidget(clean_btn)

        top_bar.setLayout(top_layout)
        bl.addWidget(top_bar)

        # === 数据集列表 ===
        list_label = QLabel(f"开源机器人数据集 ({len(self.DATASETS)}个)")
        list_label.setFont(QFont("Arial", 11, QFont.Bold))
        list_label.setStyleSheet(f"color:{SYS2_COLOR}; background:transparent; border:none; margin:0;")
        bl.addWidget(list_label)

        # 使用表格展示数据集
        from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(["名称", "repo_id", "机器人", "任务数", "缓存", "描述", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self._table.horizontalHeader().resizeSection(6, 480)  # 操作列(四个文字按钮，间距24px)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(60)  # 行高给按钮足够空间
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setStyleSheet(f"""
            QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER}; }}
            QTableWidget::item {{ padding:6px 8px; }}
            QTableWidget::item:selected {{ background:{SYS2_COLOR}33; }}
            QHeaderView::section {{ background:{C_BG2}; color:{SYS2_COLOR}; border:1px solid {C_BORDER}; padding:6px; font-weight:bold; }}
        """)

        self._populate_table()
        bl.addWidget(self._table)

        body.setLayout(bl)
        self._build_shell(body)

    def _populate_table(self):
        """填充数据集表格"""
        from PyQt5.QtWidgets import QHeaderView
        self._table.setRowCount(len(self.DATASETS))

        for i, ds in enumerate(self.DATASETS):
            # 名称
            name_item = QTableWidgetItem(ds["name"])
            name_item.setFont(QFont("Arial", 10, QFont.Bold))
            name_item.setForeground(QBrush(QColor(SYS2_COLOR)))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 0, name_item)

            # repo_id
            repo_item = QTableWidgetItem(ds["repo_id"])
            repo_item.setFont(QFont("Consolas", 9))
            repo_item.setForeground(QBrush(QColor(C_GRAY)))
            repo_item.setFlags(repo_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 1, repo_item)

            # 机器人
            robot_item = QTableWidgetItem(ds["robot"])
            robot_item.setFont(QFont("Arial", 9))
            robot_item.setForeground(QBrush(QColor(C_WHITE)))
            robot_item.setFlags(robot_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 2, robot_item)

            # 任务数
            task_item = QTableWidgetItem(str(ds["tasks"]))
            task_item.setFont(QFont("Consolas", 10, QFont.Bold))
            task_item.setForeground(QBrush(QColor(C_GREEN)))
            task_item.setTextAlignment(Qt.AlignCenter)
            task_item.setFlags(task_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 3, task_item)

            # 缓存状态
            cached = self._is_cached(ds["repo_id"])
            cache_item = QTableWidgetItem("✅ 已缓存" if cached else "—")
            cache_item.setFont(QFont("Consolas", 9))
            cache_item.setForeground(QBrush(QColor(C_GREEN) if cached else QColor(C_DIM)))
            cache_item.setTextAlignment(Qt.AlignCenter)
            cache_item.setFlags(cache_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 4, cache_item)

            # 描述
            desc_item = QTableWidgetItem(ds["desc"])
            desc_item.setFont(QFont("Arial", 9))
            desc_item.setForeground(QBrush(QColor(C_GRAY)))
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 5, desc_item)

            # 操作按钮容器
            btn_container = QWidget()
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(12, 8, 12, 8)
            btn_layout.setSpacing(24)  # 增大按钮间距

            info_btn = QPushButton("信息")
            info_btn.setFixedHeight(36)
            info_btn.setToolTip("查看数据集元信息 (episodes/frames/features)")
            info_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_CARD};
                    color: {SYS2_COLOR};
                    border: 1px solid {SYS2_COLOR}88;
                    border-radius: 6px;
                    padding: 0px 18px;
                    font-size: 12px;
                    font-weight: bold;
                    font-family: 'Microsoft YaHei', 'PingFang SC', 'Arial';
                    min-width: 60px;
                }}
                QPushButton:hover {{
                    background: {SYS2_COLOR}33;
                }}
            """)
            info_btn.clicked.connect(self._mk_info_func(ds))
            btn_layout.addWidget(info_btn)

            dl_btn = QPushButton("下载")
            dl_btn.setFixedHeight(36)
            dl_btn.setToolTip("下载前N个episodes (用户指定数量)")
            dl_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_CARD};
                    color: {C_GREEN};
                    border: 1px solid {C_GREEN}88;
                    border-radius: 6px;
                    padding: 0px 18px;
                    font-size: 12px;
                    font-weight: bold;
                    font-family: 'Microsoft YaHei', 'PingFang SC', 'Arial';
                    min-width: 60px;
                }}
                QPushButton:hover {{
                    background: {C_GREEN}33;
                }}
            """)
            dl_btn.clicked.connect(self._mk_download_func(ds))
            btn_layout.addWidget(dl_btn)

            # 手动下载按钮
            manual_btn = QPushButton("📥 手动")
            manual_btn.setFixedHeight(36)
            manual_btn.setToolTip("网络不通时：复制链接到浏览器下载，放到指定目录")
            manual_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_CARD};
                    color: {C_ORANGE};
                    border: 1px solid {C_ORANGE}88;
                    border-radius: 6px;
                    padding: 0px 14px;
                    font-size: 11px;
                    font-weight: bold;
                    font-family: 'Microsoft YaHei', 'PingFang SC', 'Arial';
                    min-width: 56px;
                }}
                QPushButton:hover {{
                    background: {C_ORANGE}33;
                }}
            """)
            manual_btn.clicked.connect(self._mk_manual_dl_func(ds))
            btn_layout.addWidget(manual_btn)

            del_btn = QPushButton("删除")
            del_btn.setFixedHeight(36)
            del_btn.setToolTip("删除本地缓存 (释放磁盘空间)")
            del_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_CARD};
                    color: {C_RED};
                    border: 1px solid {C_RED}88;
                    border-radius: 6px;
                    padding: 0px 18px;
                    font-size: 12px;
                    font-weight: bold;
                    font-family: 'Microsoft YaHei', 'PingFang SC', 'Arial';
                    min-width: 60px;
                }}
                QPushButton:hover {{
                    background: {C_RED}33;
                }}
            """)
            del_btn.clicked.connect(self._mk_delete_func(ds))
            btn_layout.addWidget(del_btn)

            view_btn = QPushButton("查看")
            view_btn.setFixedHeight(36)
            view_btn.setToolTip("浏览数据集内容 (图片/视频/state曲线)")
            view_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_CARD};
                    color: {C_ORANGE};
                    border: 1px solid {C_ORANGE}88;
                    border-radius: 6px;
                    padding: 0px 18px;
                    font-size: 12px;
                    font-weight: bold;
                    font-family: 'Microsoft YaHei', 'PingFang SC', 'Arial';
                    min-width: 60px;
                }}
                QPushButton:hover {{
                    background: {C_ORANGE}33;
                }}
            """)
            view_btn.clicked.connect(lambda checked=False, ds=ds: self._on_view_dataset(ds))
            btn_layout.addWidget(view_btn)

            btn_container.setLayout(btn_layout)
            self._table.setCellWidget(i, 6, btn_container)

    def _get_cache_dir_for_repo(self, repo_id):
        """获取数据集本地缓存路径 (LeRobot/HuggingFace datasets 格式)"""
        repo_slug = repo_id.replace("/", "___")
        # LeRobot datasets 缓存在 ~/.cache/huggingface/datasets/
        return os.path.expanduser(f"~/.cache/huggingface/datasets/{repo_slug}")

    def _is_cached(self, repo_id):
        """检查数据集是否已缓存"""
        path = self._get_cache_dir_for_repo(repo_id)
        if not os.path.exists(path):
            return False
        # 检查是否有实际数据文件
        import glob
        parquet_files = glob.glob(os.path.join(path, "**", "*.parquet"), recursive=True)
        return len(parquet_files) > 0

    def _get_cache_size(self):
        """获取全部缓存目录大小"""
        if not os.path.exists(self._cache_dir):
            return "0 B"
        total = 0
        for dirpath, dirnames, filenames in os.walk(self._cache_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        for unit in ['B', 'KB', 'MB', 'GB']:
            if total < 1024:
                return f"{total:.1f} {unit}"
            total /= 1024
        return f"{total:.1f} TB"

    def _refresh_cache_status(self):
        """刷新表格中的缓存状态"""
        for i, ds in enumerate(self.DATASETS):
            cached = self._is_cached(ds["repo_id"])
            item = self._table.item(i, 4)
            if item:
                item.setText("✅ 已缓存" if cached else "—")
                item.setForeground(QBrush(QColor(C_GREEN) if cached else QColor(C_DIM)))

    def _clean_all_cache(self):
        """清理全部数据集缓存"""
        reply = QMessageBox.warning(self, "确认清理",
            f"将删除全部本地缓存:\n{self._cache_dir}\n\n"
            f"这将释放磁盘空间，但可以重新下载。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        import shutil
        try:
            if os.path.exists(self._cache_dir):
                shutil.rmtree(self._cache_dir)
            self._refresh_cache_status()
            QMessageBox.information(self, "清理完成", "所有缓存已删除")
        except Exception as e:
            QMessageBox.warning(self, "清理失败", f"部分文件可能被占用:\n{e}")

    def _mk_info_func(self, ds):
        """创建查看信息的闭包"""
        def show_info():
            self._show_dataset_info(ds)
        return show_info

    def _mk_download_func(self, ds):
        """创建下载的闭包"""
        def download():
            self._download_dataset(ds)
        return download

    def _mk_manual_dl_func(self, ds):
        """创建手动下载的闭包"""
        def manual_dl():
            self._manual_download_guide(ds)
        return manual_dl

    def _mk_delete_func(self, ds):
        """创建删除的闭包"""
        def delete():
            self._delete_dataset(ds)
        return delete

    def _show_dataset_info(self, ds):
        """查看数据集信息 — 通过 HuggingFace Hub API 获取元数据"""
        repo_id = ds["repo_id"]
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

        info_text = f"""
📊 {ds['name']}
{'─' * 50}
repo_id:  {repo_id}
机器人:   {ds['robot']}
任务数:   {ds['tasks']}
标签:     {', '.join(ds['tags'])}
描述:     {ds['desc']}
本地状态: {'✅ 已缓存' if self._is_cached(repo_id) else '未下载'}
"""
        # 尝试从 HuggingFace Hub 获取元信息
        try:
            import urllib.request, json
            url = f"https://huggingface.co/api/datasets/{repo_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "XSpaceStudio/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            downloads = data.get("downloads", "N/A")
            likes = data.get("likes", "N/A")
            last_modified = data.get("lastModified", "N/A")
            branch = data.get("defaultBranch", "main")

            info_text += f"""
{'─' * 50}
📡 HuggingFace Hub 信息
Downloads:  {downloads}
Likes:      {likes}
Last Modified: {last_modified}
Default Branch: {branch}
"""

            # 尝试获取 info.json (数据集元信息)
            try:
                info_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/meta/info.json"
                req2 = urllib.request.Request(info_url, headers={"User-Agent": "XSpaceStudio/1.0"})
                with urllib.request.urlopen(req2, timeout=15) as resp2:
                    meta = json.loads(resp2.read().decode())

                total_eps = meta.get("total_episodes", "?")
                total_frames = meta.get("total_frames", "?")
                fps = meta.get("fps", "?")
                robot_type = meta.get("robot_type", "?")
                chunks = meta.get("chunks", {})
                chunk_count = len(chunks) if isinstance(chunks, dict) else "?"

                features = meta.get("features", {})
                feat_summary = "\n".join([f"    {k}: {v.get('dtype','?')}" for k, v in features.items()]) if features else "    (none)"

                info_text += f"""
{'─' * 50}
📋 数据集元信息 (info.json)
  Total Episodes: {total_eps}
  Total Frames:   {total_frames}
  FPS:            {fps}
  Robot Type:     {robot_type}
  Chunks:         {chunk_count}

  Features (数据字段):
{feat_summary}
"""
            except Exception as e:
                info_text += f"\n⚠️ 无法获取 info.json: {e}\n"

        except Exception as e:
            info_text += f"\n⚠️ 无法连接 HuggingFace Hub: {e}\n  (请检查网络连接)\n"

        QApplication.restoreOverrideCursor()

        # 显示在对话框中
        from PyQt5.QtWidgets import QDialog, QScrollArea
        dialog = QDialog(self)
        dialog.setWindowTitle(f"数据集信息 — {ds['name']}")
        dialog.setFixedSize(680, 520)
        dialog.setStyleSheet(f"QDialog{{background:{C_BG}; border:2px solid {SYS2_COLOR}; border-radius:8px;}}")

        dlg_layout = QVBoxLayout()
        dlg_layout.setContentsMargins(16, 12, 16, 12)
        dlg_layout.setSpacing(8)

        title = QLabel(f"📊 {ds['name']}")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color:{SYS2_COLOR}; background:transparent; border:none;")
        dlg_layout.addWidget(title)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        text.setStyleSheet(f"background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:12px;")
        text.setPlainText(info_text)
        dlg_layout.addWidget(text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFont(QFont("Arial", 10, QFont.Bold))
        close_btn.setStyleSheet(f"background:{SYS2_COLOR}; color:white; border:none; border-radius:6px; padding:8px 24px;")
        close_btn.clicked.connect(dialog.close)
        btn_row.addWidget(close_btn)
        dlg_layout.addLayout(btn_row)

        dialog.setLayout(dlg_layout)
        dialog.exec_()

    def _manual_download_guide(self, ds):
        """显示手动下载指引"""
        repo_id = ds["repo_id"]
        cache_path = self._get_cache_dir_for_repo(repo_id)
        hf_url = f"https://huggingface.co/datasets/{repo_id}"
        hf_dl = f"https://huggingface.co/datasets/{repo_id}/resolve/main"
        
        msg = f"""📥 手动下载 · {ds['name']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📎 下载链接（浏览器打开）:
   {hf_url}

⬇️ 直接下载按钮在页面右上角 ⋮ → Download

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 下载后放到这个目录:
   {cache_path}

   在 WSL 终端里执行:
   mkdir -p "{cache_path}"
   然后把下载的文件放到这个目录

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 提示:
   1. 浏览器访问上面的链接
   2. 点 Download 下载 ZIP
   3. 解压到上面📁目录
   4. 回数据集管理点「刷新」
"""
        QMessageBox.information(self, f"📥 手动下载 - {ds['name']}", msg)
        # 复制下载链接到剪贴板
        QApplication.clipboard().setText(hf_url)
    
    def _download_dataset(self, ds):
        """下载数据集（仅下载前 N episodes）"""
        from PyQt5.QtWidgets import QInputDialog
        repo_id = ds["repo_id"]

        episodes, ok = QInputDialog.getInt(self, "下载数据集",
            f"下载 {ds['name']} ({repo_id})\n\n"
            f"请输入要下载的 episode 数量 (前 N 个):\n"
            f"(建议: 1~10，完整数据集可能很大)",
            value=10, min=1, max=1000)

        if not ok:
            return

        # 在后台线程下载
        from PyQt5.QtCore import QThread, pyqtSignal
        class DownloadWorker(QThread):
            progress = pyqtSignal(str)
            finished = pyqtSignal(bool, str)

            def __init__(self, repo_id, n_episodes, parent=None):
                super().__init__(parent)
                self.repo_id = repo_id
                self.n = n_episodes

            def run(self):
                try:
                    # 使用国内镜像加速
                    import os
                    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
                    
                    try:
                        from huggingface_hub import snapshot_download
                        self.progress.emit(f"⬇️ 开始下载 {self.repo_id}...")
                        
                        # LeRobot v2 使用分块parquet格式，直接下载整个数据集
                        # 但限制只下载 data/ 和 meta/ 目录
                        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
                        
                        local_path = snapshot_download(
                            repo_id=self.repo_id,
                            repo_type="dataset",
                            cache_dir=cache_dir,
                            allow_patterns=[
                                "meta/*",           # 元数据
                                "data/*",           # 数据文件 (parquet)
                                "videos/*",         # 视频文件 (如果有)
                            ],
                            ignore_patterns=[
                                "*.md",             # 文档
                                "LICENSE*",         # 许可证
                            ],
                        )
                        
                        self.progress.emit(f"✅ 数据集已下载到:\n{local_path}")
                        self.progress.emit(f"\n📦 包含的文件:")
                        
                        # 列出下载的文件
                        if os.path.exists(local_path):
                            meta_files = glob.glob(os.path.join(local_path, "meta/*"))
                            data_files = glob.glob(os.path.join(local_path, "data/**/*.parquet"), recursive=True)
                            video_files = glob.glob(os.path.join(local_path, "videos/**/*.mp4"), recursive=True)
                            
                            self.progress.emit(f"  📋 meta/: {len(meta_files)} 个文件")
                            self.progress.emit(f"  📊 data/: {len(data_files)} 个 parquet 文件")
                            if video_files:
                                self.progress.emit(f"  🎥 videos/: {len(video_files)} 个视频文件")
                        
                        self.finished.emit(True, f"成功下载数据集到 {local_path}")

                    except ImportError:
                        self.finished.emit(False, "缺少 huggingface_hub 库，无法下载")
                    except Exception as e:
                        self.finished.emit(False, f"下载失败: {e}")

                except Exception as e:
                    self.finished.emit(False, f"错误: {e}")

        worker = DownloadWorker(repo_id, episodes)
        # 显示进度对话框
        from PyQt5.QtWidgets import QDialog, QProgressBar as QPB
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle(f"下载中 — {ds['name']}")
        progress_dialog.setFixedSize(500, 200)
        progress_dialog.setStyleSheet(f"QDialog{{background:{C_BG}; border:2px solid {C_GREEN}; border-radius:8px;}}")

        pdl = QVBoxLayout()
        pdl.setContentsMargins(20, 16, 20, 16)
        pdl.setSpacing(8)

        pd_title = QLabel(f"⬇️ 下载 {ds['name']}")
        pd_title.setFont(QFont("Arial", 13, QFont.Bold))
        pd_title.setStyleSheet(f"color:{C_GREEN}; background:transparent; border:none;")
        pdl.addWidget(pd_title)

        pd_log = QTextEdit()
        pd_log.setReadOnly(True)
        pd_log.setFont(QFont("Consolas", 9))
        pd_log.setStyleSheet(f"background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px;")
        pdl.addWidget(pd_log)

        progress_dialog.setLayout(pdl)
        progress_dialog.show()

        worker.progress.connect(lambda msg: pd_log.append(msg))

        def on_finished(ok, msg):
            pd_log.append(f"\n{'✅' if ok else '❌'} {msg}")
            self._refresh_cache_status()

        worker.finished.connect(on_finished)
        worker.start()

        # 保存引用防止回收
        self._download_worker = worker
        self._download_dialog = progress_dialog

    def _on_view_dataset(self, ds):
        """打开数据集内容查看器"""
        from dataset_viewer import DatasetViewer
        repo_id = ds["repo_id"]
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        viewer = DatasetViewer(repo_id, cache_dir, self)
        viewer.exec_()

    def _delete_dataset(self, ds):
        """删除数据集本地缓存"""
        repo_id = ds["repo_id"]
        cache_path = self._get_cache_dir_for_repo(repo_id)

        if not os.path.exists(cache_path):
            QMessageBox.information(self, "未缓存", f"{ds['name']} 尚未下载到本地")
            return

        reply = QMessageBox.warning(self, "确认删除",
            f"将删除 {ds['name']} 的本地缓存:\n{cache_path}\n\n可以重新下载，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        import shutil
        try:
            shutil.rmtree(cache_path)
            self._refresh_cache_status()
            QMessageBox.information(self, "已删除", f"{ds['name']} 缓存已清理")
        except Exception as e:
            QMessageBox.warning(self, "删除失败", f"部分文件可能被占用:\n{e}")


class TrainingModule(QWidget):
    """Training Console - Support for SmolVLA and custom policy training"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Import training backend
        from training_backend import training_backend
        self.train_backend = training_backend
        
        # Status tracking
        self.is_training = False
        self.is_paused = False
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI with global scroll area"""
        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建滚动区域包裹整个内容
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {C_BG};
                width: 12px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C_BORDER};
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_CYAN};
            }}
        """)
        
        # 创建内容容器
        content_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== Top Bar: Title + SmolVLA Button =====
        top_bar = QHBoxLayout()
        
        title = QLabel("🧠 SmolVLA Training Console")
        title.setStyleSheet(f"color: {C_WHITE}; font-size: 20px; font-weight: bold;")
        top_bar.addWidget(title)
        
        top_bar.addStretch()
        
        # SmolVLA info badge
        self.smolvla_btn = QPushButton("✅ SmolVLA")
        self.smolvla_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C_GREEN};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 12px;
                font-weight: bold;
            }}
        """)
        self.smolvla_btn.setEnabled(False)
        top_bar.addWidget(self.smolvla_btn)
        
        layout.addLayout(top_bar)
        
        # ===== Training Parameter Area =====
        param_group = QGroupBox(" SmolVLA Parameters ")
        param_group.setStyleSheet(f"""
            QGroupBox {{
                color: {C_WHITE};
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 24px;
                padding-top: 48px;
                margin-top: 24px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                font-weight: bold;
            }}
            QLabel {{
                color: {C_WHITE};
                background: transparent;
                padding: 2px 0px;
                min-height: 24px;
            }}
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {{
                min-height: 24px;
                padding: 4px 8px;
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
            }}
            QCheckBox {{
                min-height: 24px;
                padding: 2px 0px;
                color: {C_WHITE};
            }}
        """)
        
        param_layout = QFormLayout()
        param_layout.setSpacing(12)
        param_layout.setHorizontalSpacing(20)
        param_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        param_layout.setContentsMargins(0, 4, 0, 0)
        
        # ===== SmolVLA Model Info =====
        policy_label = QLabel("🧠 SmolVLA Model")
        policy_label.setFont(QFont("Arial", 12, QFont.Bold))
        policy_label.setStyleSheet(f"color: {C_BLUE}; padding-bottom: 4px;")
        param_layout.addRow(policy_label)
        
        # SmolVLA version info (read-only display)
        self.vlm_info = QLabel("SmolVLM2-500M-Video-Instruct · 450M params · Cross-Attention")
        self.vlm_info.setStyleSheet(f"color: {C_GRAY}; font-size: 10px; padding: 4px 8px; background: {C_BG}; border-radius: 4px;")
        self.vlm_info.setWordWrap(True)
        param_layout.addRow("VLM Backbone:", self.vlm_info)
        
        # Freeze SmolVLM
        self.freeze_checkbox = QCheckBox("Enabled")
        self.freeze_checkbox.setChecked(True)
        self.freeze_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {C_WHITE};
                background: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {C_BORDER};
                border-radius: 3px;
                background: {C_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {C_BLUE};
                border-color: {C_BLUE};
            }}
        """)
        self.freeze_checkbox.setToolTip("Freeze SmolVLM backbone (--policy.freeze_smolvlm)")
        param_layout.addRow("Freeze SmolVLM:", self.freeze_checkbox)
        
        # Enable World Model
        self.world_model_checkbox = QCheckBox("Enabled")
        self.world_model_checkbox.setChecked(False)
        self.world_model_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {C_WHITE};
                background: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {C_BORDER};
                border-radius: 3px;
                background: {C_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {C_BLUE};
                border-color: {C_BLUE};
            }}
        """)
        self.world_model_checkbox.setToolTip("Enable LeWorld Model (--policy.enable_lew_world_model)")
        param_layout.addRow("World Model:", self.world_model_checkbox)
        
        # Repeated Diffusion Steps
        self.diffusion_spin = QSpinBox()
        self.diffusion_spin.setRange(1, 100)
        self.diffusion_spin.setValue(5)
        self.diffusion_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.diffusion_spin.setToolTip("Action prediction steps (repeated diffusion/flow matching steps)")
        param_layout.addRow("Action Steps:", self.diffusion_spin)

        # ===== Architecture =====
        arch_label = QLabel("Architecture")
        arch_label.setFont(QFont("Arial", 11, QFont.Bold))
        arch_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(arch_label)

        # VLM layers
        self.vlm_layers_spin = QSpinBox()
        self.vlm_layers_spin.setRange(4, 32)
        self.vlm_layers_spin.setValue(16)
        self.vlm_layers_spin.setToolTip("Number of VLM layers used (num_vlm_layers)")
        param_layout.addRow("VLM Layers:", self.vlm_layers_spin)

        # Expert layers
        self.expert_layers_spin = QSpinBox()
        self.expert_layers_spin.setRange(-1, 32)
        self.expert_layers_spin.setValue(-1)
        self.expert_layers_spin.setToolTip("Expert layers (-1 = same as VLM)")
        param_layout.addRow("Expert Layers:", self.expert_layers_spin)

        # Expert width
        self.expert_width_spin = QDoubleSpinBox()
        self.expert_width_spin.setRange(0.25, 2.0)
        self.expert_width_spin.setValue(0.75)
        self.expert_width_spin.setSingleStep(0.25)
        self.expert_width_spin.setToolTip("Expert hidden size relative to VLM")
        param_layout.addRow("Expert Width:", self.expert_width_spin)

        # Self-attention interval
        self.self_attn_spin = QSpinBox()
        self.self_attn_spin.setRange(1, 8)
        self.self_attn_spin.setValue(2)
        self.self_attn_spin.setToolTip("Self-attention every N layers")
        param_layout.addRow("Self-Attn Every:", self.self_attn_spin)

        # ===== I/O Dimensions =====
        io_label = QLabel("Input / Output")
        io_label.setFont(QFont("Arial", 11, QFont.Bold))
        io_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(io_label)

        # Observation steps
        self.obs_steps_spin = QSpinBox()
        self.obs_steps_spin.setRange(1, 10)
        self.obs_steps_spin.setValue(1)
        self.obs_steps_spin.setToolTip("Number of observation steps (n_obs_steps)")
        param_layout.addRow("Obs Steps:", self.obs_steps_spin)

        # Chunk size  
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(10, 200)
        self.chunk_spin.setValue(50)
        self.chunk_spin.setSingleStep(10)
        self.chunk_spin.setToolTip("Action chunk size")
        param_layout.addRow("Chunk Size:", self.chunk_spin)

        # State dim
        self.state_dim_spin = QSpinBox()
        self.state_dim_spin.setRange(1, 128)
        self.state_dim_spin.setValue(32)
        self.state_dim_spin.setToolTip("Max state dimension (padded)")
        param_layout.addRow("Max State Dim:", self.state_dim_spin)

        # Action dim
        self.action_dim_spin = QSpinBox()
        self.action_dim_spin.setRange(1, 128)
        self.action_dim_spin.setValue(32)
        self.action_dim_spin.setToolTip("Max action dimension (padded)")
        param_layout.addRow("Max Action Dim:", self.action_dim_spin)
        
        # Dataset selection
        self.dataset_combo = QComboBox()
        self.dataset_combo.addItems([
            "lerobot/pusht",
            "lerobot/metaworld_mt50",
            "lerobot/xarm_lift_medium",
            "lerobot/aloha_sim_transfer_cube_human",
            "lerobot/koch_bimanual_folding",
            "lerobot/so100_pick_place"
        ])
        self.dataset_combo.setStyleSheet(f"""
            QComboBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }}
        """)
        param_layout.addRow("Dataset:", self.dataset_combo)
        # 同步 combo 到老的 edit 字段
        self.dataset_combo.currentTextChanged.connect(lambda t: self.dataset_repo_edit.setText(t))
        self.dataset_combo.currentTextChanged.connect(self._auto_output_dir)
        self.dataset_combo.currentTextChanged.connect(self._on_dataset_changed)
        
        # 本地缓存路径显示
        self.dataset_path_label = QLabel()
        self.dataset_path_label.setFont(QFont("Consolas", 8))
        self.dataset_path_label.setStyleSheet(f"color:{C_GRAY}; padding-left:4px;")
        self.dataset_path_label.setWordWrap(True)
        param_layout.addRow("本地路径:", self.dataset_path_label)
        self.dataset_combo.currentTextChanged.connect(self._update_dataset_path)
        # 初始化显示
        self._update_dataset_path(self.dataset_combo.currentText())

        # Batch size
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 256)
        self.batch_spin.setValue(8)
        self.batch_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.batch_spin.setToolTip("Number of samples processed per training step")
        param_layout.addRow("Batch Size:", self.batch_spin)
        
        # Training steps
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(100, 1000000)
        self.steps_spin.setValue(500)
        self.steps_spin.setSingleStep(100)
        self.steps_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.steps_spin.setToolTip("Total number of training steps")
        param_layout.addRow("Training Steps:", self.steps_spin)
        
        # ===== Image Preprocessing =====
        img_label = QLabel("Image Preprocessing")
        img_label.setFont(QFont("Arial", 11, QFont.Bold))
        img_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(img_label)

        # Resize width
        self.resize_w_spin = QSpinBox()
        self.resize_w_spin.setRange(64, 1024)
        self.resize_w_spin.setValue(512)
        self.resize_w_spin.setSingleStep(64)
        self.resize_w_spin.setToolTip("Image resize width")
        param_layout.addRow("Resize Width:", self.resize_w_spin)

        # Resize height
        self.resize_h_spin = QSpinBox()
        self.resize_h_spin.setRange(64, 1024)
        self.resize_h_spin.setValue(512)
        self.resize_h_spin.setSingleStep(64)
        self.resize_h_spin.setToolTip("Image resize height")
        param_layout.addRow("Resize Height:", self.resize_h_spin)

        # Empty cameras
        self.empty_cameras_spin = QSpinBox()
        self.empty_cameras_spin.setRange(0, 4)
        self.empty_cameras_spin.setValue(0)
        self.empty_cameras_spin.setToolTip("Number of empty camera channels")
        param_layout.addRow("Extra Cameras:", self.empty_cameras_spin)

        # Position encoding
        self.min_period_spin = QDoubleSpinBox()
        self.min_period_spin.setRange(0.001, 0.1)
        self.min_period_spin.setValue(0.004)
        self.min_period_spin.setDecimals(4)
        self.min_period_spin.setSingleStep(0.001)
        self.min_period_spin.setToolTip("Min period for sine-cosine positional encoding")
        param_layout.addRow("Min Period:", self.min_period_spin)

        self.max_period_spin = QDoubleSpinBox()
        self.max_period_spin.setRange(1.0, 16.0)
        self.max_period_spin.setValue(4.0)
        self.max_period_spin.setSingleStep(1.0)
        self.max_period_spin.setToolTip("Max period for sine-cosine positional encoding")
        param_layout.addRow("Max Period:", self.max_period_spin)
        
        # Checkpoint interval
        self.ckpt_spin = QSpinBox()
        self.ckpt_spin.setRange(10, 10000)
        self.ckpt_spin.setValue(100)
        self.ckpt_spin.setSingleStep(10)
        self.ckpt_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.ckpt_spin.setToolTip("Number of steps to save checkpoint")
        param_layout.addRow("Checkpoint Interval:", self.ckpt_spin)
        
        # ===== Dataset Settings =====
        dataset_label = QLabel("Dataset Settings")
        dataset_label.setFont(QFont("Arial", 11, QFont.Bold))
        dataset_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(dataset_label)
        
        # Dataset Repo ID
        self.dataset_repo_edit = QLineEdit("lerobot/pusht")
        self.dataset_repo_edit.setStyleSheet(f"""
            QLineEdit {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.dataset_repo_edit.setToolTip("HuggingFace dataset repo ID (--dataset.repo_id)")
        param_layout.addRow("Dataset Repo ID:", self.dataset_repo_edit)
        
        # ===== Optimizer Settings =====
        opt_label = QLabel("Optimizer Settings")
        opt_label.setFont(QFont("Arial", 11, QFont.Bold))
        opt_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(opt_label)
        
        # Learning Rate
        self.lr_spin = QDoubleSpinBox()
        self.lr_spin.setRange(0.000001, 0.1)
        self.lr_spin.setValue(0.0001)
        self.lr_spin.setSingleStep(0.00001)
        self.lr_spin.setDecimals(6)
        self.lr_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.lr_spin.setToolTip("Optimizer learning rate (--optimizer.lr)")
        param_layout.addRow("Learning Rate:", self.lr_spin)
        
        # Weight Decay
        self.weight_decay_spin = QDoubleSpinBox()
        self.weight_decay_spin.setRange(0.0000001, 0.01)
        self.weight_decay_spin.setValue(0.000001)
        self.weight_decay_spin.setSingleStep(0.000001)
        self.weight_decay_spin.setDecimals(7)
        self.weight_decay_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.weight_decay_spin.setToolTip("Weight decay (--optimizer.weight_decay)")
        param_layout.addRow("Weight Decay:", self.weight_decay_spin)
        
        # Gradient Clipping
        self.grad_clip_spin = QDoubleSpinBox()
        self.grad_clip_spin.setRange(0.1, 100.0)
        self.grad_clip_spin.setValue(10.0)
        self.grad_clip_spin.setSingleStep(0.5)
        self.grad_clip_spin.setDecimals(1)
        self.grad_clip_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.grad_clip_spin.setToolTip("Gradient clipping norm (--optimizer.grad_clip_norm)")
        param_layout.addRow("Grad Clip Norm:", self.grad_clip_spin)
        
        # ===== Scheduler Settings =====
        sched_label = QLabel("Scheduler Settings")
        sched_label.setFont(QFont("Arial", 11, QFont.Bold))
        sched_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(sched_label)
        
        # Scheduler Type
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems([
            "cosine_decay_with_warmup",
            "constant",
            "linear_decay"
        ])
        self.scheduler_combo.setStyleSheet(f"""
            QComboBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
            }}
        """)
        self.scheduler_combo.setToolTip("Learning rate scheduler type (--scheduler.type)")
        param_layout.addRow("Scheduler Type:", self.scheduler_combo)
        
        # Warmup Steps
        self.warmup_spin = QSpinBox()
        self.warmup_spin.setRange(0, 100000)
        self.warmup_spin.setValue(500)
        self.warmup_spin.setSingleStep(100)
        self.warmup_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.warmup_spin.setToolTip("Number of warmup steps (--scheduler.num_warmup_steps)")
        param_layout.addRow("Warmup Steps:", self.warmup_spin)
        
        # Decay Steps
        self.decay_spin = QSpinBox()
        self.decay_spin.setRange(100, 1000000)
        self.decay_spin.setValue(500)
        self.decay_spin.setSingleStep(100)
        self.decay_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.decay_spin.setToolTip("Number of decay steps (--scheduler.num_decay_steps)")
        param_layout.addRow("Decay Steps:", self.decay_spin)
        
        # Peak LR
        self.peak_lr_spin = QDoubleSpinBox()
        self.peak_lr_spin.setRange(0.000001, 0.1)
        self.peak_lr_spin.setValue(0.0001)
        self.peak_lr_spin.setSingleStep(0.00001)
        self.peak_lr_spin.setDecimals(6)
        self.peak_lr_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.peak_lr_spin.setToolTip("Peak learning rate (--scheduler.peak_lr)")
        param_layout.addRow("Peak LR:", self.peak_lr_spin)
        
        # Decay LR
        self.decay_lr_spin = QDoubleSpinBox()
        self.decay_lr_spin.setRange(0.0000001, 0.01)
        self.decay_lr_spin.setValue(0.000001)
        self.decay_lr_spin.setSingleStep(0.000001)
        self.decay_lr_spin.setDecimals(7)
        self.decay_lr_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.decay_lr_spin.setToolTip("Final learning rate after decay (--scheduler.decay_lr)")
        param_layout.addRow("Decay LR:", self.decay_lr_spin)
        
        # ===== Experiment Settings =====
        exp_label = QLabel("Experiment Settings")
        exp_label.setFont(QFont("Arial", 11, QFont.Bold))
        exp_label.setStyleSheet(f"color: {C_CYAN}; padding-top: 12px;")
        param_layout.addRow(exp_label)
        
        # Eval Frequency
        self.eval_freq_spin = QSpinBox()
        self.eval_freq_spin.setRange(0, 100000)
        self.eval_freq_spin.setValue(500)
        self.eval_freq_spin.setSingleStep(100)
        self.eval_freq_spin.setStyleSheet(f"""
            QSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.eval_freq_spin.setToolTip("Evaluation frequency in steps, 0 to disable (--eval.frequency)")
        param_layout.addRow("Eval Frequency:", self.eval_freq_spin)
        
        # Push to Hub
        self.push_hub_checkbox = QCheckBox("Enabled")
        self.push_hub_checkbox.setChecked(False)
        self.push_hub_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {C_WHITE};
                background: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {C_BORDER};
                border-radius: 3px;
                background: {C_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {C_BLUE};
                border-color: {C_BLUE};
            }}
        """)
        self.push_hub_checkbox.setToolTip("Push checkpoint to HuggingFace Hub (--policy.push_to_hub)")
        param_layout.addRow("Push to Hub:", self.push_hub_checkbox)

        # Compile model
        self.compile_checkbox = QCheckBox("Use torch.compile (faster, higher first-run)")
        self.compile_checkbox.setChecked(False)
        self.compile_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {C_WHITE};
                background: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {C_BORDER};
                border-radius: 3px;
                background: {C_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {C_BLUE};
                border-color: {C_BLUE};
            }}
        """)
        param_layout.addRow("Compile:", self.compile_checkbox)
        
        # Output Directory
        self.output_dir_edit = QLineEdit("outputs/smolvla_pusht")
        self.output_dir_edit.setStyleSheet(f"""
            QLineEdit {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.output_dir_edit.setToolTip("Output directory for checkpoints and logs")
        param_layout.addRow("Output Directory:", self.output_dir_edit)
        
        param_group.setLayout(param_layout)
        
        # Wrap param_group in QScrollArea so all parameters are scrollable
        self.param_scroll = QScrollArea()
        self.param_scroll.setWidget(param_group)
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.param_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.param_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {C_BORDER};
                width: 12px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C_BLUE};
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_CYAN};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        layout.addWidget(self.param_scroll)
        
        # ===== Control Button Area =====
        # Wrap buttons in a container widget with explicit background to prevent color bleeding
        btn_container = QWidget()
        btn_container.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(16)  # 增加间距
        btn_layout.setContentsMargins(0, 8, 0, 8)  # 增加上下边距防止紫色渗透
        
        # Start button
        self.start_btn = QPushButton("▶ Start Training")
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_GREEN};
                color: white;
                border: 2px solid {C_GREEN};
                border-radius: 6px;
                padding: 12px 32px;
                margin: 0px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_GREEN};
                border: 2px solid {C_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {C_GREEN}bb;
                border: 2px solid {C_BLUE};
            }}
            QPushButton:disabled {{
                background-color: {C_GRAY}44;
                color: {C_GRAY};
                border: 2px solid {C_GRAY}44;
            }}
        """)
        self.start_btn.clicked.connect(self._start_training)
        btn_layout.addWidget(self.start_btn)
        
        # 恢复默认参数
        self.defaults_btn = QPushButton("🔄 恢复默认")
        self.defaults_btn.setToolTip("一键恢复 SmolVLA 原始默认训练参数")
        self.defaults_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_CARD};
                color: {C_GRAY};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_BORDER};
                color: {C_WHITE};
            }}
        """)
        self.defaults_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(self.defaults_btn)
        
        # Pause/Resume button
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_ORANGE};
                color: white;
                border: 2px solid {C_ORANGE};
                border-radius: 6px;
                padding: 12px 32px;
                margin: 0px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_ORANGE};
                border: 2px solid {C_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {C_ORANGE}bb;
                border: 2px solid {C_BLUE};
            }}
            QPushButton:disabled {{
                background-color: {C_GRAY}44;
                color: {C_GRAY};
                border: 2px solid {C_GRAY}44;
            }}
        """)
        self.pause_btn.clicked.connect(self._pause_training)
        btn_layout.addWidget(self.pause_btn)
        
        # Stop button
        self.stop_btn = QPushButton("⏹ Stop Training")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_RED};
                color: white;
                border: 2px solid {C_RED};
                border-radius: 6px;
                padding: 12px 32px;
                margin: 0px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_RED};
                border: 2px solid {C_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {C_RED}bb;
                border: 2px solid {C_BLUE};
            }}
            QPushButton:disabled {{
                background-color: {C_GRAY}44;
                color: {C_GRAY};
                border: 2px solid {C_GRAY}44;
            }}
        """)
        self.stop_btn.clicked.connect(self._stop_training)
        btn_layout.addWidget(self.stop_btn)
        
        # Preview command button
        self.preview_btn = QPushButton("👁 Preview CLI Command")
        self.preview_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_PURPLE};
                color: white;
                border: 2px solid {C_PURPLE};
                border-radius: 6px;
                padding: 12px 32px;
                margin: 0px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C_PURPLE};
                border: 2px solid {C_BLUE};
            }}
            QPushButton:pressed {{
                background-color: {C_PURPLE}bb;
                border: 2px solid {C_BLUE};
            }}
        """)
        self.preview_btn.clicked.connect(self._preview_command)
        self.preview_btn.setToolTip("Preview the full lerobot-train CLI command without running it")
        btn_layout.addWidget(self.preview_btn)
        
        btn_container.setLayout(btn_layout)
        layout.addWidget(btn_container)
        
        # ===== Progress Bar =====
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Progress: %p%")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                text-align: center;
                color: {C_WHITE};
                font-weight: bold;
                height: 30px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                           stop:0 {C_GREEN}, stop:1 {C_BLUE});
                border-radius: 5px;
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        # ===== Log Output Terminal =====
        log_group = QGroupBox(" Training Log ")
        log_group.setStyleSheet(f"""
            QGroupBox {{
                color: {C_WHITE};
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                font-weight: bold;
            }}
        """)
        
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(600)  # 确保 log 区域足够大
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background: {C_BG};
                color: {C_WHITE};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }}
            QScrollBar:vertical {{
                background: {C_BG};
                width: 12px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C_BORDER};
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_CYAN};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)  # stretch=1 让 log 占据大部分空间
        
        # Set content widget in scroll area and add to main layout
        content_widget.setLayout(layout)
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Main layout
        self.setLayout(main_layout)
        
        # Initialize log
        self._log("🎮 Training console initialized")
        self._log("Ready to start training...")
    
    def showEvent(self, event):
        """Override showEvent to set minimum height based on screen size"""
        super().showEvent(event)
        # Dynamically set param_scroll minimum height to 1/3 of screen height
        if hasattr(self, 'param_scroll'):
            screen = QApplication.primaryScreen().geometry()
            min_height = screen.height() // 3
            self.param_scroll.setMinimumHeight(min_height)
    
    def _log(self, message):
        """Add log message"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # Auto scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _switch_to_smolvla(self):
        """SmolVLA is the only model — refresh params"""
        self._log("🧠 SmolVLA mode — 参数已按默认配置")
        self.smolvla_btn.setText("✅ SmolVLA Active")
        self.smolvla_btn.setEnabled(False)
    
    def _update_dataset_path(self, repo_id):
        """更新数据集本地缓存路径显示"""
        if not repo_id: return
        slug = repo_id.replace("/", "___")
        path = os.path.expanduser(f"~/.cache/huggingface/datasets/{slug}")
        cached = os.path.isdir(path)
        if cached:
            import glob
            try:
                # 支持 .parquet 和 .arrow 两种格式
                parquets = glob.glob(os.path.join(path, "**", "*.parquet"), recursive=True)
                arrows = glob.glob(os.path.join(path, "**", "*.arrow"), recursive=True)
                valid = [p for p in parquets + arrows if os.path.isfile(p)]
                size = sum(os.path.getsize(p) for p in valid) if valid else 0
                for unit in ['B','KB','MB','GB']:
                    if size < 1024: break
                    size /= 1024
                self.dataset_path_label.setText(f"✅ 已缓存 · {len(valid)}文件 · {size:.1f}{unit}")
                self.dataset_path_label.setStyleSheet(f"color:{C_GREEN}; font-weight:bold; font-size:10px; padding:4px 8px; background:{C_GREEN}22; border:1px solid {C_GREEN}66; border-radius:4px;")
            except Exception as e:
                self.dataset_path_label.setText(f"⚠️ {e}")
                self.dataset_path_label.setStyleSheet(f"color:{C_ORANGE}; font-size:9px;")
        else:
            self.dataset_path_label.setText(f"❌ 未缓存 · 需下载")
            self.dataset_path_label.setStyleSheet(f"color:{C_RED}; font-weight:bold; font-size:10px; padding:4px 8px; background:{C_RED}22; border:1px solid {C_RED}66; border-radius:4px;")

    def _auto_output_dir(self):
        """根据当前数据集自动更新输出目录"""
        ds = self.dataset_combo.currentText()
        if ds:
            name = ds.split("/")[-1]
            self.output_dir_edit.setText(f"outputs/smolvla_{name}")
    
    def _on_dataset_changed(self, ds):
        """数据集切换时自动更新输出目录和缓存状态"""
        self._update_dataset_path(ds)
        self._auto_output_dir()
    
    def _reset_defaults(self):
        """恢复 SmolVLA 原始默认训练参数（来自 configuration_smolvla.py）"""
        # Architecture
        self.vlm_layers_spin.setValue(16)
        self.expert_layers_spin.setValue(-1)
        self.expert_width_spin.setValue(0.75)
        self.self_attn_spin.setValue(2)
        # I/O
        self.obs_steps_spin.setValue(1)
        self.chunk_spin.setValue(50)
        self.state_dim_spin.setValue(32)
        self.action_dim_spin.setValue(32)
        # Image
        self.resize_w_spin.setValue(512)
        self.resize_h_spin.setValue(512)
        self.empty_cameras_spin.setValue(0)
        self.min_period_spin.setValue(0.004)
        self.max_period_spin.setValue(4.0)
        # Policy
        self.freeze_checkbox.setChecked(True)
        self.world_model_checkbox.setChecked(False)
        self.diffusion_spin.setValue(5)
        # Dataset + Training
        self.dataset_combo.setCurrentText("lerobot/pusht")
        self.batch_spin.setValue(1)
        self.steps_spin.setValue(500)
        self.ckpt_spin.setValue(100)
        # Optimizer
        self.lr_spin.setValue(0.0001)
        self.weight_decay_spin.setValue(0.000000001)
        self.grad_clip_spin.setValue(10.0)
        # Scheduler
        self.scheduler_combo.setCurrentText("cosine_decay_with_warmup")
        self.warmup_spin.setValue(1000)
        self.decay_spin.setValue(30000)
        self.peak_lr_spin.setValue(0.0001)
        self.decay_lr_spin.setValue(0.0000025)
        # Experiment
        self.output_dir_edit.setText("outputs/smolvla_pusht")
        self.eval_freq_spin.setValue(500)
        self.push_hub_checkbox.setChecked(False)
        self.compile_checkbox.setChecked(False)
        self._update_dataset_path("lerobot/pusht")
        self._log("🔄 已恢复 SmolVLA 原始默认训练参数")

    def _start_training(self):
        """Start SmolVLA training"""
        # Dataset
        dataset_repo_id = self.dataset_combo.currentText()
        ds_name = dataset_repo_id.split("/")[-1]
        output_dir = f"outputs/smolvla_{ds_name}"
        self.output_dir_edit.setText(output_dir)

        # Gather all params
        params = {
            "dataset_repo_id": dataset_repo_id,
            "output_dir": output_dir,
            # Architecture
            "n_obs_steps": self.obs_steps_spin.value(),
            "chunk_size": self.chunk_spin.value(),
            "n_action_steps": self.chunk_spin.value(),
            "max_state_dim": self.state_dim_spin.value(),
            "max_action_dim": self.action_dim_spin.value(),
            # Image
            "resize_w": self.resize_w_spin.value(),
            "resize_h": self.resize_h_spin.value(),
            "empty_cameras": self.empty_cameras_spin.value(),
            "min_period": self.min_period_spin.value(),
            "max_period": self.max_period_spin.value(),
            # Policy
            "freeze_smolvlm": self.freeze_checkbox.isChecked(),
            "enable_lew_world_model": self.world_model_checkbox.isChecked(),
            "repeated_diffusion_steps": self.diffusion_spin.value(),
            "num_vlm_layers": self.vlm_layers_spin.value(),
            "num_expert_layers": self.expert_layers_spin.value(),
            "expert_width": self.expert_width_spin.value(),
            "self_attn_every": self.self_attn_spin.value(),
            "compile_model": self.compile_checkbox.isChecked(),
            # Training
            "batch_size": self.batch_spin.value(),
            "total_steps": self.steps_spin.value(),
            "checkpoint_interval": self.ckpt_spin.value(),
            # Optimizer
            "learning_rate": self.lr_spin.value(),
            "weight_decay": self.weight_decay_spin.value(),
            "grad_clip_norm": self.grad_clip_spin.value(),
            # Scheduler
            "scheduler_type": self.scheduler_combo.currentText(),
            "num_warmup_steps": self.warmup_spin.value(),
            "num_decay_steps": self.decay_spin.value(),
            "peak_lr": self.peak_lr_spin.value(),
            "decay_lr": self.decay_lr_spin.value(),
            # Experiment
            "eval_freq": self.eval_freq_spin.value(),
            "push_to_hub": self.push_hub_checkbox.isChecked(),
        }

        self._log(f"🚀 Starting SmolVLA training...")
        self._log(f"   Dataset: {dataset_repo_id} | Output: {output_dir}")
        self._log(f"   Architecture: VLM={params['num_vlm_layers']}L Expert={params['num_expert_layers']}L W={params['expert_width']}")
        self._log(f"   I/O: obs={params['n_obs_steps']} chunk={params['chunk_size']} s={params['max_state_dim']} a={params['max_action_dim']}")
        self._log(f"   Training: batch={params['batch_size']} steps={params['total_steps']} lr={params['learning_rate']}")

        import os
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        output_dir_abs = os.path.join(repo_root, output_dir)

        success = self.train_backend.start_smolvla_training(
            repo_root=repo_root,
            dataset_repo_id=dataset_repo_id,
            output_dir=output_dir_abs,
            **params,
            log_callback=self._log,
            progress_callback=self._update_progress
        )
        
        if success:
            self.is_training = True
            self.is_paused = False
            
            # Update button states
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.smolvla_btn.setEnabled(False)
            
            self._log("✅ Training started successfully")
        else:
            self._log("❌ Failed to start training")
    
    def _pause_training(self):
        """Pause/Resume training"""
        if self.is_paused:
            # Resume
            success = self.train_backend.resume_training(log_callback=self._log)
            if success:
                self.is_paused = False
                self.pause_btn.setText("⏸ Pause")
                self._log("▶ Training resumed")
        else:
            # Pause
            success = self.train_backend.pause_training(log_callback=self._log)
            if success:
                self.is_paused = True
                self.pause_btn.setText("▶ Resume")
                self._log("⏸ Training paused")
    
    def _stop_training(self):
        """Stop training"""
        success = self.train_backend.stop_training(log_callback=self._log)
        
        if success:
            self.is_training = False
            self.is_paused = False
            
            # Reset button states
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("⏸ Pause")
            self.stop_btn.setEnabled(False)
            
            # Reset SmolVLA button
            self.smolvla_btn.setEnabled(True)
            self.smolvla_btn.setText("✅ SmolVLA")
            self.smolvla_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C_GREEN};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 20px;
                    font-size: 12px;
                    font-weight: bold;
                }}
            """)
            
            self._log("⏹ Training stopped")
    
    def _preview_command(self):
        """Preview SmolVLA training configuration"""
        dataset_repo_id = self.dataset_combo.currentText()
        ds_name = dataset_repo_id.split("/")[-1]
        output_dir = f"outputs/smolvla_{ds_name}"
        self.output_dir_edit.setText(output_dir)

        self._log("=" * 60)
        self._log(f"🧠 SmolVLA Training Preview")
        self._log(f"   VLM:      SmolVLM2-500M · 450M params · Cross-Attn")
        self._log(f"   Expert:   {self.vlm_layers_spin.value()}VLM/{self.expert_layers_spin.value()}exp L · W={self.expert_width_spin.value()}")
        self._log(f"   Dataset:  {dataset_repo_id}")
        self._log(f"   I/O:      obs={self.obs_steps_spin.value()} · chunk={self.chunk_spin.value()} · s={self.state_dim_spin.value()}/a={self.action_dim_spin.value()}")
        self._log(f"   Image:    {self.resize_w_spin.value()}×{self.resize_h_spin.value()} · {self.empty_cameras_spin.value()} extra cameras")
        self._log(f"   Training: batch={self.batch_spin.value()} · steps={self.steps_spin.value()} · lr={self.lr_spin.value():.0e}")
        self._log(f"   Scheduler: {self.scheduler_combo.currentText()} · warmup={self.warmup_spin.value()} · decay={self.decay_spin.value()}")
        self._log(f"   Output:   {output_dir}")
        self._log(f"   Freeze VLM: {self.freeze_checkbox.isChecked()} · Compile: {self.compile_checkbox.isChecked()}")
        self._log("=" * 60)
        self._log(f"点击 Start Training 开始训练")
    
    def _update_progress(self, value):
        """Update progress bar"""
        self.progress_bar.setValue(value)


class EvalModule(SubModuleWidget):
    def __init__(self):
        super().__init__("评估分析", [("Sys-12", SYS12_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)
        
        # ── 训练历史 ──
        train_group = QGroupBox("📈 训练历史")
        train_group.setStyleSheet(f"QGroupBox{{color:{SYS12_COLOR}; font-weight:bold; {card_style(C_CARD, SYS12_COLOR, 8, 12)}}}")
        tl = QVBoxLayout()
        
        import os, json, glob
        
        # 扫描所有训练记录
        proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        train_records = []
        for d in sorted(glob.glob(os.path.join(proj_root, "outputs", "*"))):
            meta_path = os.path.join(d, "training_meta.json")
            if os.path.exists(meta_path):
                try:
                    m = json.load(open(meta_path))
                    m["_dir"] = os.path.basename(d)
                    train_records.append(m)
                except:
                    pass
        
        if train_records:
            # 记录选择器
            sel_row = QHBoxLayout()
            sel_row.addWidget(QLabel("训练记录:"))
            self.eval_record_combo = QComboBox()
            self.eval_record_combo.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px; min-width:250px;")
            for i, m in enumerate(train_records):
                label = f"[{m['_dir'][:16]}] {m['model']} | {m['dataset']} | {m['steps']}步 | loss {m['final_loss']:.4f}"
                self.eval_record_combo.addItem(label, i)
            self.eval_record_combo.currentIndexChanged.connect(lambda idx: self._show_training_record(train_records))
            sel_row.addWidget(self.eval_record_combo, 1)
            tl.addLayout(sel_row)
            
            # 详情 + 曲线
            self.eval_info = QLabel()
            self.eval_info.setStyleSheet(f"color:{C_WHITE}; font-size:11px; padding:4px;")
            tl.addWidget(self.eval_info)
            
            self.eval_svg = QLabel()
            self.eval_svg.setAlignment(Qt.AlignCenter)
            tl.addWidget(self.eval_svg)
            
            # 默认选第一条
            self._show_training_record(train_records)
        else:
            hint = QLabel("<span style='color:#8b949e'>暂无训练记录。运行训练后自动显示损失曲线。</span>")
            hint.setFont(QFont("Arial", 11))
            hint.setStyleSheet(f"color:{C_GRAY}; padding:20px;")
            tl.addWidget(hint)
        
        train_group.setLayout(tl)
        bl.addWidget(train_group)
        
        # ── 检查点 ──
        ckpt = QGroupBox("检查点"); ckpt.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        cl = QFormLayout()
        cb = QComboBox(); cb.addItems(["latest", "best", "checkpoint_10000", "自定义..."])
        cl.addRow("Checkpoint:", cb)
        ep = QSpinBox(); ep.setRange(1, 1000); ep.setValue(50)
        cl.addRow("Episode数:", ep)
        ckpt.setLayout(cl)
        bl.addWidget(ckpt)
        
        # ── 操作 ──
        btn_row = QHBoxLayout()
        for txt in ["运行评估", "动作回放", "Rollout"]:
            b = QPushButton(txt)
            b.setStyleSheet(f"""QPushButton{{background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:10px 18px;}} 
            QPushButton:hover{{border-color:{SYS12_COLOR};}}""")
            btn_row.addWidget(b)
        bl.addLayout(btn_row)
        
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setStyleSheet(f"background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(self.log)
        body.setLayout(bl)
        self._build_shell(body)
    
    def _show_training_record(self, records):
        """显示选中的训练记录"""
        idx = self.eval_record_combo.currentIndex()
        if idx < 0 or idx >= len(records):
            return
        m = records[idx]
        initial_loss = m.get('initial_loss')
        final_loss = m.get('final_loss')
        reduction_pct = m.get('reduction_pct')
        n_params = m.get('params') or m.get('total_params') or 0
        # 构建loss行，null字段显示为N/A
        loss_parts = []
        if initial_loss is not None:
            loss_parts.append(f"{initial_loss:.4f}")
        else:
            loss_parts.append("N/A")
        if final_loss is not None:
            loss_parts.append(f"{final_loss:.4f}")
        else:
            loss_parts.append("N/A")
        loss_line = f"loss {loss_parts[0]}→{loss_parts[1]}"
        if reduction_pct is not None:
            loss_line += f" ({reduction_pct}%↓)"
        self.eval_info.setText(
            f"<b>{m.get('model','?')}</b> · {m.get('dataset','?')} · <b>{m.get('steps','?')}步</b> · "
            f"{loss_line}<br>"
            f"<span style='color:#8b949e'>{n_params//1e6:.0f}M参数 | {m.get('device','?')} | {m.get('timestamp','?')}</span>"
        )
        proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        svg_path = os.path.join(proj_root, "outputs", m["_dir"], "loss_curve.svg")
        if os.path.exists(svg_path):
            self.eval_svg.setPixmap(QPixmap(svg_path).scaled(580, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.eval_svg.setText("<span style='color:#8b949e'>无损失曲线</span>")


class HardwareModule(SubModuleWidget):
    """硬件工具箱 — System 0 基石层: 仿真 + 真实硬件统一接口
    
    架构: 仿真引擎(hardware_simulator.py) ↔ GUI ↔ ROS2/gRPC(真机)
    模式: sim(虚拟设备) | local(本地ROS2) | real(Orin真机TCP桥)
    """
    
    def __init__(self):
        super().__init__("硬件工具箱", [("System 0", SYS0_COLOR)])
        
        # SSH 连接复用 — 加速所有硬件控制命令
        import subprocess
        try:
            subprocess.run(
                ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/orin-ssh.sock", 
                 "-o", "ControlPersist=120", "-fN", "nvidia@192.168.23.10"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except:
            pass  # Orin 不在线也不崩溃
        
        self.sim = get_simulator("sim")
        self._selected_device = "overview"
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        
        # 回放引擎
        self.replay = ReplayEngine()
        self._replay_thread = None
        
        # ── 顶部工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        
        mode_label = QLabel("模式:")
        mode_label.setStyleSheet(f"color:{C_WHITE}; font-weight:bold;")
        toolbar.addWidget(mode_label)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["🖥️ 仿真模拟 (Sim)", "🔌 本地连接 (Local)", "🤖 Orin真机 (Real)"])
        self.mode_combo.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self.mode_combo)
        
        toolbar.addSpacing(20)
        
        self.btn_start = QPushButton("▶ 启动仿真")
        self.btn_start.setStyleSheet(f"background:{C_GREEN}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
        self.btn_start.clicked.connect(self._toggle_sim)
        toolbar.addWidget(self.btn_start)
        
        self.btn_reset = QPushButton("↺ 重置")
        self.btn_reset.setStyleSheet(f"background:{C_ORANGE}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
        self.btn_reset.clicked.connect(self._reset)
        toolbar.addWidget(self.btn_reset)
        
        self.btn_discover = QPushButton("🔍 发现硬件")
        self.btn_discover.setStyleSheet(f"background:{C_RED}; color:white; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
        self.btn_discover.setToolTip("SSH连接Orin · 发现ROS2节点和Topic · 系统资源 · TCP Bridge状态")
        self.btn_discover.clicked.connect(self._discover_hardware)
        self.btn_discover.setVisible(False)  # 仅Real模式显示
        toolbar.addWidget(self.btn_discover)
        
        self.status_label = QLabel("● 待机")
        self.status_label.setStyleSheet(f"color:{C_GRAY}; padding:4px 12px; background:{C_BG2}; border-radius:4px;")
        toolbar.addWidget(self.status_label)
        
        toolbar.addStretch()
        
        # ── 主内容区: 设备树 + 详情 ──
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧: 设备树
        tree_panel = QWidget()
        tree_panel.setStyleSheet(f"background:{C_BG2}; border-radius:6px;")
        tree_layout = QVBoxLayout()
        tree_layout.setContentsMargins(8, 8, 8, 8)
        
        tree_title = QLabel("设备树")
        tree_title.setFont(QFont("Arial", 12, QFont.Bold))
        tree_title.setStyleSheet(f"color:{SYS0_COLOR};")
        tree_layout.addWidget(tree_title)
        
        self.device_tree = QTreeWidget()
        self.device_tree.setHeaderLabels(["设备", "状态"])
        self.device_tree.setColumnWidth(0, 180)
        self.device_tree.setStyleSheet(f"""
            QTreeWidget{{background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px;}}
            QTreeWidget::item{{padding:4px;}}
            QTreeWidget::item:selected{{background:{SYS0_COLOR}33; color:{SYS0_COLOR};}}
            QHeaderView::section{{background:{C_BG2}; color:{C_GRAY}; border:none; padding:4px; font-size:10px;}}
        """)
        self.device_tree.itemClicked.connect(self._on_device_selected)
        self._build_device_tree()
        tree_layout.addWidget(self.device_tree)
        tree_panel.setLayout(tree_layout)
        splitter.addWidget(tree_panel)
        
        # 右侧: 设备详情
        self.detail_stack = QStackedWidget()
        self.detail_stack.setStyleSheet(f"background:{C_BG}; border-radius:6px;")
        self.detail_stack.addWidget(self._build_overview_detail())
        self.detail_stack.addWidget(self._build_joint_detail())
        self.detail_stack.addWidget(self._build_camera_detail())
        self.detail_stack.addWidget(self._build_force_detail())
        self.detail_stack.addWidget(self._build_io_detail())
        splitter.addWidget(self.detail_stack)
        splitter.setSizes([280, 680])
        
        # ── 🎛️ 硬件总线 (CANoe风格) ──
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(80)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setStyleSheet(f"background:#0a0e14; color:{C_GREEN}; border:1px solid {C_BORDER}; border-radius:4px; padding:6px;")
        self.log.setText("  System 0 硬件工具箱就绪 · 仿真模式 · 等待启动 ...\n")
        
        # ── 组装 ──
        body = QVBoxLayout()
        body.setSpacing(8)
        body.addLayout(toolbar)
        body.addWidget(splitter, 1)
        
        # ── 🎛️ 硬件总线 (CANoe风格) ──
        hw_group = QGroupBox("🎛️ 硬件总线 · Orin 真实设备")
        hw_group.setStyleSheet(f"QGroupBox{{color:{SYS0_COLOR}; font-weight:bold; font-size:11px; border:2px solid {SYS0_COLOR}; border-radius:6px; margin-top:12px; padding-top:16px;}}")
        hw_layout = QVBoxLayout()
        hw_layout.setSpacing(4)
        
        # 硬件列表表头
        self.hw_table = QTableWidget()
        self.hw_table.setColumnCount(6)
        self.hw_table.setHorizontalHeaderLabels(["硬件", "类型", "状态", "当前值", "控制接口", "操作"])
        self.hw_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.hw_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.hw_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.hw_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.hw_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.hw_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.hw_table.verticalHeader().setVisible(False)
        self.hw_table.verticalHeader().setDefaultSectionSize(42)  # 行高
        self.hw_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hw_table.setMinimumHeight(320)
        self.hw_table.setStyleSheet(f"""
            QTableWidget{{background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER};}}
            QTableWidget::item{{padding:6px 8px; font-size:10px;}}
            QHeaderView::section{{background:{C_BG2}; color:{SYS0_COLOR}; border:1px solid {C_BORDER}; padding:4px; font-size:9px; font-weight:bold;}}
        """)
        hw_layout.addWidget(self.hw_table)
        hw_group.setLayout(hw_layout)
        body.addWidget(hw_group)
        
        # ── 填充硬件列表 ──
        self._build_hardware_bus()
        
        body.addWidget(self.log)
        
        container = QWidget()
        container.setLayout(body)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar{width:8px;}")
        scroll.setWidget(container)
        self._build_shell(scroll)

    # ═══ 硬件总线 · CANoe风格 ═══
    
    def _build_hardware_bus(self):
        """构建Orin真实硬件控制面板 — 每个硬件一行"""
        devices = [
            # (名称, 类型, 状态获取方法, 控制接口列表)
            ("🚦 三色塔灯",    "IO/灯光",   self._get_tower_status,  self._get_tower_controls),
            ("🤖 珞石机械臂",  "6-DOF臂",   None,                    ["/move_joint(TargetPose)", "/robot_stop(Trigger)"]),
            ("🖐️ 电动夹爪",   "末端执行器", None,                   ["/gripper_driver(GripperSrv)"]),
            ("⚡ 力/力矩传感器","六维力",    None,                    ["/robot/force_torque(Wrench)"]),
            ("📷 RealSense D435","RGB-D相机", None,                    ["/color/image_raw", "/depth/rect", "/points"]),
            ("🚨 双路急停",    "安全IO",     None,                    ["/physical_estop", "/usb_estop"]),
            ("📱 扫码枪",      "Honeywell",  None,                    ["/barcode_scanner/status"]),
            ("🖐️ 触觉传感器", "TS-F-L",    None,                    ["/tactile_sensor(TactileSensor)"]),
            ("👁️ FoundationPose","视觉定位",  None,                    "待接入"),
            ("📡 障碍物检测",  "安全",       None,                    "待接入"),
            ("🎛️ 状态机",      "控制器",     None,                    ["state_machine/*"]),
            ("🖥️ HMI 人机界面","HMI",       None,                    "待接入"),
        ]
        
        self.hw_table.setRowCount(len(devices))
        for row, (name, hw_type, status_fn, controls) in enumerate(devices):
            # 名称
            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor(C_WHITE))
            self.hw_table.setItem(row, 0, name_item)
            # 类型
            self.hw_table.setItem(row, 1, QTableWidgetItem(hw_type))
            # 状态
            status_item = QTableWidgetItem("⏸ 待查询" if status_fn else "⏸ 待接入")
            status_item.setForeground(QColor(C_GRAY))
            self.hw_table.setItem(row, 2, status_item)
            # 当前值
            val_item = QTableWidgetItem("-" if status_fn else "-")
            val_item.setForeground(QColor(C_GRAY))
            self.hw_table.setItem(row, 3, val_item)
            # 控制接口
            if isinstance(controls, list):
                ctrl_text = ", ".join(controls)
            else:
                ctrl_text = str(controls)
            ctrl_item = QTableWidgetItem(ctrl_text)
            ctrl_item.setForeground(QColor(C_CYAN))
            self.hw_table.setItem(row, 4, ctrl_item)
            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(3)
            
            if name == "🚦 三色塔灯":
                for color, label, style_color in [
                    ("green",  "🟢", C_GREEN),
                    ("yellow", "🟡", C_YELLOW),
                    ("red",    "🔴", C_RED),
                    ("off",    "⚫", C_GRAY),
                ]:
                    btn = self._make_hw_btn(label, style_color)
                    btn.clicked.connect(lambda checked, c=color: self._tower_cmd(c))
                    btn_layout.addWidget(btn)
            elif name == "🖐️ 电动夹爪":
                open_btn = self._make_hw_btn("🖐️开", C_GREEN)
                open_btn.setToolTip("张开到最大")
                open_btn.clicked.connect(lambda: self._gripper_cmd(200.0))
                btn_layout.addWidget(open_btn)
                close_btn = self._make_hw_btn("✊关", C_RED)
                close_btn.setToolTip("闭合到最小")
                close_btn.clicked.connect(lambda: self._gripper_cmd(0.0))
                btn_layout.addWidget(close_btn)
            elif name == "🤖 珞石机械臂":
                read_btn = self._make_hw_btn("📡", C_BLUE)
                read_btn.setToolTip("读取关节状态")
                read_btn.clicked.connect(self._read_robot_joints)
                btn_layout.addWidget(read_btn)
                stop_btn = self._make_hw_btn("🛑", C_RED)
                stop_btn.setToolTip("急停")
                stop_btn.clicked.connect(self._robot_stop)
                btn_layout.addWidget(stop_btn)
            elif name == "📷 RealSense D435":
                check_btn = self._make_hw_btn("📸", C_CYAN)
                check_btn.setToolTip("检测相机")
                check_btn.clicked.connect(self._check_camera)
                btn_layout.addWidget(check_btn)
            elif name == "🖐️ 触觉传感器":
                read_btn = self._make_hw_btn("📡", C_ORANGE)
                read_btn.setToolTip("读取触觉")
                read_btn.clicked.connect(self._read_tactile)
                btn_layout.addWidget(read_btn)
            elif name in ["⚡ 力/力矩传感器", "🚨 双路急停", "📱 扫码枪"]:
                read_btn = self._make_hw_btn("📡", C_BLUE)
                read_btn.setToolTip("读取状态")
                read_btn.clicked.connect(lambda checked, r=row: self._read_sensor(r))
                btn_layout.addWidget(read_btn)
            else:
                ph = QLabel("待接入")
                ph.setStyleSheet(f"color:{C_GRAY}; font-size:9px;")
                btn_layout.addWidget(ph)
            
            btn_widget.setLayout(btn_layout)
            self.hw_table.setCellWidget(row, 5, btn_widget)
    
    def _make_hw_btn(self, text, color):
        btn = QPushButton(text)
        btn.setFixedSize(38, 30)
        btn.setStyleSheet(f"""
            QPushButton{{background:{C_BG2}; color:{color}; border:1px solid {color}; border-radius:4px; font-size:12px;}}
            QPushButton:hover{{background:{color}; color:#0d1117;}}
            QPushButton:pressed{{background:{C_DIM};}}
        """)
        btn.setToolTip(f"塔灯 {text}")
        return btn
    
    def _tower_cmd(self, color):
        """发送塔灯控制命令"""
        import subprocess
        self._log(f"🚦 塔灯 → {color}")
        try:
            subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                f"ROS_DOMAIN_ID=23 ros2 topic pub --once /tower_light/command "
                f"std_msgs/msg/String '{{\"data\":\"{color}\"}}'"
            ], timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 更新状态
            self.hw_table.item(0, 2).setText("🟢 已控制")
            self.hw_table.item(0, 3).setText(color)
        except Exception as e:
            self._log(f"   ❌ 塔灯控制失败: {e}")
    
    def _gripper_cmd(self, pos):
        """夹爪开/关"""
        import subprocess
        action = "张开" if pos > 0 else "闭合"
        self._log(f"🖐️ 夹爪 → {action}")
        try:
            r = subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash 2>/dev/null && "
                f"ROS_DOMAIN_ID=23 ros2 service call /gripper_driver interfaces/srv/GripperSrv "
                f"'{{target_pos: {pos}, target_speed: 50.0, target_force: -1.0, "
                f"target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}}'"
            ], capture_output=True, text=True, timeout=8)
            curr = ""
            if "curr_pos" in r.stdout:
                import re; m = re.search(r'curr_pos=([\d.]+)', r.stdout)
                if m: curr = f" → {float(m.group(1)):.0f} raw"
            self.hw_table.item(2, 2).setText("🟢")
            self.hw_table.item(2, 3).setText(f"{action}{curr}")
        except Exception as e:
            self._log(f"   ❌ {e}")
    
    def _get_tower_status(self):
        return "待实现"
    
    def _get_tower_controls(self):
        return ["/tower_light/command (std_msgs/String)"]
    
    def _check_camera(self):
        """拍摄 RealSense 照片并弹窗显示"""
        import subprocess, os
        self._log("📷 拍摄中...")
        try:
            # 上传拍照脚本
            cap_script = os.path.join(os.path.dirname(__file__), "capture_cam.py")
            
            # 1. 上传脚本到Orin
            subprocess.run(["scp", "-o", "ControlPath=/tmp/orin-ssh.sock",
                cap_script, "nvidia@192.168.23.10:/tmp/cam_cap.py"],
                timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 2. 运行拍照
            r = subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && python3 /tmp/cam_cap.py"
            ], capture_output=True, text=True, timeout=12)
            
            if "OK" in r.stdout:
                # 3. 拉回图片
                subprocess.run(["scp", "-o", "ControlPath=/tmp/orin-ssh.sock",
                    "nvidia@192.168.23.10:/tmp/cam.jpg", "/tmp/orin_cam.jpg"],
                    timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                from PyQt5.QtGui import QPixmap
                pix = QPixmap("/tmp/orin_cam.jpg")
                if not pix.isNull():
                    dlg = QDialog(self)
                    dlg.setWindowTitle("📷 RealSense D405 实拍")
                    dlg.setStyleSheet(f"background:{C_BG};")
                    dl = QVBoxLayout()
                    img_label = QLabel()
                    img_label.setPixmap(pix.scaled(640, 480, Qt.KeepAspectRatio))
                    img_label.setAlignment(Qt.AlignCenter)
                    dl.addWidget(img_label)
                    btn = QPushButton("关闭")
                    btn.setStyleSheet(f"background:{C_BLUE}; color:white; border:none; border-radius:4px; padding:6px 20px;")
                    btn.clicked.connect(dlg.accept)
                    dl.addWidget(btn)
                    dlg.setLayout(dl)
                    dlg.exec_()
                    self.hw_table.item(4, 2).setText("🟢")
                    self.hw_table.item(4, 3).setText(f"{pix.width()}x{pix.height()}")
                    self._log(f"   ✅ {pix.width()}x{pix.height()}")
                else:
                    self.hw_table.item(4, 3).setText("加载失败")
            else:
                self.hw_table.item(4, 2).setText("⏸")
                self.hw_table.item(4, 3).setText("无帧")
                self._log("   ⏸ 无帧")
        except Exception as e:
            self.hw_table.item(4, 3).setText(f"错误")
            self._log(f"   ❌ {e}")
    
    def _read_tactile(self):
        """读取触觉传感器"""
        import subprocess
        self._log("🖐️ 读取触觉...")
        try:
            r = subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                "ROS_DOMAIN_ID=23 timeout 3 ros2 topic echo --once /tactile_sensor 2>/dev/null"
            ], capture_output=True, text=True, timeout=8)
            out = r.stdout
            if "sensor_name" in out:
                import re
                name = re.search(r'sensor_name: (.+)', out)
                model = re.search(r'sensor_model: (.+)', out)
                nf = re.search(r'nf:\n(.+)', out)
                nf_val = nf.group(1).strip()[:60] if nf else "?"
                info = f"{name.group(1) if name else '?'} | nf={nf_val}"
                self.hw_table.item(7, 2).setText("🟢")
                self.hw_table.item(7, 3).setText(info[:80])
                self._log(f"   ✅ {info[:80]}")
            else:
                self.hw_table.item(7, 2).setText("⏸")
                self.hw_table.item(7, 3).setText("空闲(无接触)")
        except Exception as e:
            self._log(f"   ❌ {e}")

    def _read_sensor(self, row):
        """通用传感器读取 — 力/急停/扫码"""
        import subprocess
        topics = {
            3: ("/robot/force_torque", "⚡ 力传感器"),
            5: ("/emergency_stop", "🚨 急停"),
            6: ("/barcode_scanner/status", "📱 扫码枪"),
        }
        if row not in topics: return
        topic, label = topics[row]
        self._log(f"{label} 读取中...")
        try:
            r = subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                f"ROS_DOMAIN_ID=23 timeout 3 ros2 topic echo --once {topic} 2>/dev/null"
            ], capture_output=True, text=True, timeout=8)
            out = r.stdout.strip()
            if out:
                # 提取关键信息
                lines = out.split('\n')[:4]
                info = " | ".join([l.strip()[:30] for l in lines if l.strip() and not l.startswith('---')])
                self.hw_table.item(row, 2).setText("🟢")
                self.hw_table.item(row, 3).setText(info[:80])
                self._log(f"   ✅ {info[:60]}")
            else:
                self.hw_table.item(row, 2).setText("⏸")
                self.hw_table.item(row, 3).setText("idle")
                self._log(f"   ⏸ idle")
        except Exception as e:
            self._log(f"   ❌ {e}")

    def _read_robot_joints(self):
        """读取机械臂当前关节状态"""
        import subprocess, re
        self._log("🤖 读取关节状态...")
        try:
            r = subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash 2>/dev/null && "
                "ROS_DOMAIN_ID=23 timeout 3 ros2 topic echo --once /robot/joint_states 2>/dev/null"
            ], capture_output=True, text=True, timeout=8)
            out = r.stdout
            # 解析 position 值
            positions = []
            in_pos = False
            for line in out.split('\n'):
                line = line.strip()
                if 'position:' in line:
                    in_pos = True; continue
                if in_pos and line.startswith('-'):
                    try: positions.append(float(line.strip()))
                    except: break
                elif in_pos and not line.startswith('-'):
                    break
            
            if positions:
                j_str = " ".join([f"J{i+1}:{p:+.3f}" for i, p in enumerate(positions[:6])])
                self.hw_table.item(1, 2).setText("🟢")
                self.hw_table.item(1, 3).setText(j_str)
                self._log(f"   关节: {j_str}")
            else:
                self.hw_table.item(1, 2).setText("⚠️")
                self.hw_table.item(1, 3).setText("无数据(idle)")
        except Exception as e:
            self._log(f"   ❌ {e}")
    
    def _robot_stop(self):
        """机械臂急停"""
        import subprocess
        self._log("🛑 机械臂急停!")
        try:
            subprocess.run([
                "ssh", "-o", "ControlPath=/tmp/orin-ssh.sock", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
                "source /opt/ros/humble/setup.bash && "
                "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash 2>/dev/null && "
                "ROS_DOMAIN_ID=23 ros2 service call /robot_stop std_srvs/srv/Trigger '{}'"
            ], timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.hw_table.item(1, 2).setText("🛑")
            self.hw_table.item(1, 3).setText("已急停")
        except Exception as e:
            self._log(f"   ❌ {e}")

    # ═══ 设备树 ═══
    
    def _build_device_tree(self):
        self.device_tree.clear()
        
        overview = QTreeWidgetItem(["📋 系统概览", ""])
        self.device_tree.addTopLevelItem(overview)
        
        robot = QTreeWidgetItem(["🤖 Z700 机器人", f"{len(Z700_JOINTS)} DOF"])
        for jname, jdesc in Z700_JOINTS.items():
            arm = "🟠左" if "left" in jname else "🔵右"
            QTreeWidgetItem(robot, [f"  {jname}", f"{arm} {jdesc}"])
        self.device_tree.addTopLevelItem(robot)
        
        cam = QTreeWidgetItem(["📷 相机阵列", f"{len(Z700_CAMERAS)} 路"])
        for cname, cfg in Z700_CAMERAS.items():
            QTreeWidgetItem(cam, [f"  {cname}", f"{cfg['w']}×{cfg['h']} @{cfg['fps']}fps"])
        self.device_tree.addTopLevelItem(cam)
        
        force = QTreeWidgetItem(["⚡ 力传感器", "6-axis"])
        self.device_tree.addTopLevelItem(force)
        
        io_dev = QTreeWidgetItem(["🔌 数字IO", "5 设备"])
        QTreeWidgetItem(io_dev, ["  急停按钮", "NC常闭"])
        QTreeWidgetItem(io_dev, ["  塔灯", "3色"])
        QTreeWidgetItem(io_dev, ["  光栅", "安全光幕"])
        QTreeWidgetItem(io_dev, ["  扫码枪", "Honeywell"])
        QTreeWidgetItem(io_dev, ["  夹爪×2", "力控+位置"])
        self.device_tree.addTopLevelItem(io_dev)
        
        safety = QTreeWidgetItem(["🛡️ 安全系统", "监控中"])
        self.device_tree.addTopLevelItem(safety)
        
        self.device_tree.expandAll()
    
    # ═══ 详情面板 ═══
    
    def _detail_section(self, title: str, color: str = SYS0_COLOR) -> QVBoxLayout:
        """创建详情段的标题+容器"""
        layout = QVBoxLayout()
        label = QLabel(title)
        label.setFont(QFont("Arial", 14, QFont.Bold))
        label.setStyleSheet(f"color:{color}; padding:8px 0;")
        layout.addWidget(label)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet(f"background:{C_BORDER};"); layout.addWidget(sep)
        return layout
    
    def _build_overview_detail(self):
        w = QWidget()
        l = self._detail_section("系统概览", C_CYAN)
        
        info_text = QLabel(
            "<b>Z-MAX 多模态动作专家 · System 0 硬件抽象层</b><br><br>"
            "<b>硬件平台:</b> Z700 轮式双臂机器人<br>"
            "<b>算力平台:</b> NVIDIA AGX Orin<br>"
            "<b>控制周期:</b> 1ms (1000Hz)<br>"
            "<b>力控带宽:</b> 1kHz 关节力矩闭环<br>"
            "<b>推理延迟:</b> VLA <10ms<br>"
            "<b>通讯:</b> EtherCAT (电机) / TCP Bridge (Orin↔PC) / gRPC (控制)<br>"
            "<b>安全:</b> 急停 · 力控柔顺 · 光栅 · 塔灯<br><br>"
            "<b>当前模式:</b> 🖥️ 仿真模拟 — 所有设备为虚拟仿真<br>"
            "<b>操作提示:</b> 点击左侧设备树查看详情 · 点击<i>启动仿真</i>开始"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(f"color:{C_WHITE}; font-size:12px; padding:12px; background:{C_BG2}; border-radius:6px;")
        l.addWidget(info_text)
        l.addStretch()
        w.setLayout(l)
        return w
    
    def _build_joint_detail(self):
        w = QWidget()
        l = self._detail_section("🤖 关节状态", SYS0_COLOR)
        
        self.joint_table = QTableWidget()
        self.joint_table.setColumnCount(7)
        self.joint_table.setHorizontalHeaderLabels(["关节", "位置 rad", "速度 rad/s", "力矩 Nm", "温度 °C", "电流 A", "状态"])
        self.joint_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.joint_table.verticalHeader().setVisible(False)
        self.joint_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.joint_table.setStyleSheet(f"""
            QTableWidget{{background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER};}}
            QTableWidget::item{{padding:4px 8px; font-size:10px;}}
            QHeaderView::section{{background:{C_BG2}; color:{SYS0_COLOR}; border:1px solid {C_BORDER}; padding:4px; font-size:9px; font-weight:bold;}}
        """)
        l.addWidget(self.joint_table)
        
        # 关节控制
        ctrl_row = QHBoxLayout()
        target_label = QLabel("目标位置:")
        target_label.setStyleSheet(f"color:{C_GRAY};")
        ctrl_row.addWidget(target_label)
        self.joint_target = QDoubleSpinBox()
        self.joint_target.setRange(-3.14, 3.14)
        self.joint_target.setValue(0.0)
        self.joint_target.setSingleStep(0.01)
        self.joint_target.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px;")
        ctrl_row.addWidget(self.joint_target)
        apply_joint = QPushButton("应用")
        apply_joint.setStyleSheet(f"background:{C_GREEN}; color:#0d1117; border:none; border-radius:4px; padding:4px 12px; font-weight:bold;")
        apply_joint.clicked.connect(self._apply_joint_target)
        ctrl_row.addWidget(apply_joint)
        ctrl_row.addStretch()
        l.addLayout(ctrl_row)
        w.setLayout(l)
        return w
    
    def _build_camera_detail(self):
        w = QWidget()
        l = self._detail_section("📷 相机状态", SYS0_COLOR)
        
        self.cam_table = QTableWidget()
        self.cam_table.setColumnCount(5)
        self.cam_table.setHorizontalHeaderLabels(["相机", "分辨率", "帧率", "编码", "时间戳"])
        self.cam_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cam_table.verticalHeader().setVisible(False)
        self.cam_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cam_table.setStyleSheet(f"""
            QTableWidget{{background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER};}}
            QTableWidget::item{{padding:4px 8px; font-size:10px;}}
            QHeaderView::section{{background:{C_BG2}; color:{SYS0_COLOR}; border:1px solid {C_BORDER}; padding:4px; font-size:9px; font-weight:bold;}}
        """)
        l.addWidget(self.cam_table)
        w.setLayout(l)
        return w
    
    def _build_force_detail(self):
        w = QWidget()
        l = self._detail_section("⚡ 六维力传感器", SYS0_COLOR)
        
        grid = QGridLayout()
        grid.setSpacing(10)
        self.force_labels = {}
        for i, (k, label) in enumerate([
            ("fx", "Fx (N)"), ("fy", "Fy (N)"), ("fz", "Fz (N)"),
            ("tx", "Tx (Nm)"), ("ty", "Ty (Nm)"), ("tz", "Tz (Nm)"),
        ]):
            val = QLabel("0.000")
            val.setFont(QFont("Consolas", 18, QFont.Bold))
            val.setStyleSheet(f"color:{C_GREEN}; padding:8px; background:{C_BG2}; border-radius:6px;")
            val.setAlignment(Qt.AlignCenter)
            self.force_labels[k] = val
            grid.addWidget(QLabel(label), i//3*2, i%3)
            grid.addWidget(val, i//3*2+1, i%3)
        l.addLayout(grid)
        
        info = QLabel("力控带宽: 1kHz | 精度: <2N | 量程: ±500N / ±20Nm")
        info.setStyleSheet(f"color:{C_GRAY}; font-size:10px;")
        l.addWidget(info)
        l.addStretch()
        w.setLayout(l)
        return w
    
    def _build_io_detail(self):
        w = QWidget()
        l = self._detail_section("🔌 数字 IO 状态", SYS0_COLOR)
        
        self.io_table = QTableWidget()
        self.io_table.setColumnCount(2)
        self.io_table.setHorizontalHeaderLabels(["设备", "状态"])
        self.io_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.io_table.verticalHeader().setVisible(False)
        self.io_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.io_table.setStyleSheet(f"""
            QTableWidget{{background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; gridline-color:{C_BORDER};}}
            QTableWidget::item{{padding:6px 10px; font-size:11px;}}
            QHeaderView::section{{background:{C_BG2}; color:{SYS0_COLOR}; border:1px solid {C_BORDER}; padding:4px; font-size:9px; font-weight:bold;}}
        """)
        l.addWidget(self.io_table)
        
        # IO控制按钮
        io_ctrl = QHBoxLayout()
        for label, cmd in [("🔴 触发急停", "estop"), ("🟢 释放急停", "release_estop")]:
            btn = QPushButton(label)
            btn.setStyleSheet(f"background:{C_RED}; color:white; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
            btn.clicked.connect(lambda _, c=cmd: self._io_command(c))
            io_ctrl.addWidget(btn)
        io_ctrl.addStretch()
        l.addLayout(io_ctrl)
        w.setLayout(l)
        return w
    
    # ═══ 操作 ═══
    
    def _on_mode_changed(self, idx):
        modes = ["sim", "local", "real"]
        is_real = (modes[idx] == "real")
        
        # Real模式 vs 仿真模式 UI切换
        self.btn_start.setVisible(not is_real)
        self.btn_reset.setVisible(not is_real)
        self.btn_discover.setVisible(is_real)
        
        if is_real:
            self.status_label.setText("🔴 真机模式")
            self.status_label.setStyleSheet(f"color:{C_RED}; padding:4px 12px; background:{C_BG2}; border-radius:4px; border:1px solid {C_RED}44;")
            if self.sim.running:
                self.sim.stop()
                self._timer.stop()
            self._log(f"⚠️ 切换到真机模式 — 请点击「发现硬件」连接 Orin")
            # 显示真机节点列表
            self._populate_nodes(Z700_ROS2_NODES["real"])
        else:
            self.status_label.setText("● 待机")
            self.status_label.setStyleSheet(f"color:{C_GRAY}; padding:4px 12px; background:{C_BG2}; border-radius:4px;")
            self._populate_nodes(Z700_ROS2_NODES[modes[idx]])
            self._log(f"模式切换: {modes[idx]}")
        
        self._refresh_topo()
    
    def _toggle_sim(self):
        if self.sim.running:
            self.sim.stop()
            self._timer.stop()
            self.btn_start.setText("▶ 启动仿真")
            self.btn_start.setStyleSheet(f"background:{C_GREEN}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
            self.status_label.setText("● 已停止")
            self.status_label.setStyleSheet(f"color:{C_GRAY}; padding:4px 12px; background:{C_BG2}; border-radius:4px;")
            self._log("仿真已停止")
        else:
            self.sim.start()
            self._timer.start(100)  # 100ms刷新
            self.btn_start.setText("⏸ 停止仿真")
            self.btn_start.setStyleSheet(f"background:{C_RED}; color:white; border:none; border-radius:4px; padding:6px 16px; font-weight:bold;")
            self.status_label.setText("● 运行中")
            self.status_label.setStyleSheet(f"color:{C_GREEN}; padding:4px 12px; background:{C_BG2}; border-radius:4px;")
            self._log("仿真已启动 · 1ms控制周期 · 14-DOF · 7路相机 · 力传感器 · IO")
    
    def _reset(self):
        was_running = self.sim.running
        if was_running:
            self.sim.stop()
            self._timer.stop()
        self.sim.reset()
        if was_running:
            self.sim.start()
            self._timer.start(100)
        self._refresh()
        self._log("设备已重置")
    
    def _apply_joint_target(self):
        target = self.joint_target.value()
        for j in self.sim.joints.values():
            j.target = target
        self._log(f"关节目标 → {target:.2f} rad")
    
    def _io_command(self, cmd):
        if cmd == "estop":
            self.sim.io.estop = True
            self._log("⚠️ 急停触发！所有电机断电")
        elif cmd == "release_estop":
            self.sim.io.estop = False
            self._log("急停已释放")
    
    def _discover_hardware(self):
        """SSH到Orin发现真实硬件"""
        self.btn_discover.setEnabled(False)
        self.btn_discover.setText("⏳ 发现中...")
        self._log("🔍 开始发现硬件 · 连接 Orin (192.168.23.10)...")
        
        self._discovery_thread = HardwareDiscoveryThread()
        self._discovery_thread.progress.connect(lambda msg: self._log(msg))
        self._discovery_thread.result_ready.connect(self._on_discovery_result)
        self._discovery_thread.start()
    
    def _on_discovery_result(self, result: dict):
        self.btn_discover.setEnabled(True)
        self.btn_discover.setText("🔍 再次发现")
        
        if not result.get("success"):
            error = result.get("error", "未知错误")
            self._log(f"❌ 发现失败: {error}")
            QMessageBox.warning(self, "硬件发现失败", 
                f"无法连接到 Orin 或发现硬件:\n\n{error}\n\n"
                "请确认:\n"
                "1. Orin 已开机且网络连通\n"
                "2. ROS2 系统已启动\n"
                "3. SSH 免密已配置")
            return
        
        nodes = result.get("nodes", [])
        topics = result.get("topics", [])
        system = result.get("system", {})
        tcp = result.get("tcp_bridge", {})
        
        self._log(f"✅ 发现完成！{len(nodes)} 节点 · {len(topics)} Topic")
        
        # 更新 ROS2 节点列表
        if nodes:
            node_data = [(n, result.get("topic_details", {}).get(n, "")) for n in nodes]
            self._populate_nodes(node_data if node_data[0][1] else 
                [(n, Z700_ROS2_NODES.get("real", {}).get(n, "")) for n in nodes])
        
        # 更新设备树状态
        self.device_tree.topLevelItem(0).setText(1, "🔴 真机在线")
        self.device_tree.topLevelItem(1).setText(1, f"{len(nodes)} 节点 ✅")
        self.device_tree.topLevelItem(4).setText(1, "🔴 真实IO")
        
        self.status_label.setText(f"🟢 在线 · {len(nodes)}节点")
        self.status_label.setStyleSheet(f"color:{C_GREEN}; padding:4px 12px; background:{C_BG2}; border-radius:4px; border:1px solid {C_GREEN}44;")
    
    # ═══ 📼 数据回放 ═══
    
    def _refresh_replay_sessions(self):
        """刷新回放会话列表"""
        self.replay_combo.clear()
        self.replay_combo.addItem("— 选择回放会话 —")
        for s in self.replay.list_sessions():
            self.replay_combo.addItem(s)
    
    def _replay_load(self):
        """加载回放会话"""
        session = self.replay_combo.currentText()
        if not session or session.startswith("—"):
            return
        ok = self.replay.load_session(session)
        if ok:
            self._log(f"📼 加载回放: {session} · {self.replay.total_frames} 帧 · {self.replay.duration:.1f}s")
            self.replay_info.setText(f"{self.replay.total_frames} 帧 | {self.replay.duration:.1f}s")
            self.replay_play_btn.setEnabled(True)
            self.replay_stop_btn.setEnabled(True)
            self._replay_show_frame()
        else:
            self._log(f"❌ 加载失败: {session}")
    
    def _replay_toggle(self):
        """播放/暂停切换"""
        if not self.replay.total_frames:
            return
        
        if self.replay.playing:
            # 暂停
            self.replay.playing = False
            if self._replay_thread:
                self._replay_thread.pause()
            self.replay_play_btn.setText("▶ 播放")
            self.replay_play_btn.setStyleSheet(f"background:{C_GREEN}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold; font-size:13px;")
            self._log("⏸ 回放暂停")
        else:
            # 播放
            self.replay.playing = True
            if self._replay_thread and self._replay_thread.isRunning():
                self._replay_thread.resume()
            else:
                self._replay_thread = ReplayThread(self.replay, fps=10)
                self._replay_thread.frame_ready.connect(self._on_replay_frame)
                self._replay_thread.finished.connect(self._on_replay_finished)
                self._replay_thread.start()
            self.replay_play_btn.setText("⏸ 暂停")
            self.replay_play_btn.setStyleSheet(f"background:{C_ORANGE}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold; font-size:13px;")
            self._log("▶ 回放开始")
    
    def _replay_stop(self):
        """停止回放"""
        self.replay.playing = False
        if self._replay_thread and self._replay_thread.isRunning():
            self._replay_thread.quit()
            self._replay_thread.wait(500)
        self.replay.current_frame = 0
        self.replay_play_btn.setText("▶ 播放")
        self.replay_play_btn.setStyleSheet(f"background:{C_GREEN}; color:#0d1117; border:none; border-radius:4px; padding:6px 16px; font-weight:bold; font-size:13px;")
        self.replay_progress.setValue(0)
        self.replay_info.setText(f"0/{self.replay.total_frames} 帧 | 0.0s")
        self.replay_joint_display.setText("回放已停止")
        self._log("⏹ 回放停止")
    
    def _on_replay_frame(self, frame_idx: int):
        """回放帧更新"""
        frame = self.replay.get_frame(frame_idx)
        if not frame:
            return
        self._replay_show_frame()
    
    def _replay_show_frame(self):
        """显示当前帧数据"""
        frame = self.replay.get_frame()
        if not frame:
            return
        joints = frame.get("joints", [])
        gripper = frame.get("gripper", None)
        ts = frame.get("ts", 0) - (self.replay.frames[0]["ts"] if self.replay.frames else 0)
        
        # 更新进度
        self.replay_progress.setValue(int(self.replay.progress * 1000))
        self.replay_info.setText(f"{self.replay.current_frame}/{self.replay.total_frames} 帧 | {ts:.2f}s")
        
        # 关节显示
        if joints:
            j_str = " ".join([f"J{i+1}:{v:+.4f}" for i, v in enumerate(joints[:6])])
            gripper_str = f"  夹爪:{gripper:.1f}" if gripper is not None else ""
            self.replay_joint_display.setText(f"[{ts:.2f}s] {j_str}{gripper_str}")
    
    def _on_replay_finished(self):
        """回放结束"""
        if self.replay.loop:
            self._log("🔄 循环回放")
        else:
            self._replay_stop()
            self._log("✅ 回放完成")
    
    def _on_device_selected(self, item, col):
        text = item.text(0).strip()
        if "概览" in text: self.detail_stack.setCurrentIndex(0)
        elif any(k in text for k in ["joint", "gripper"]): self.detail_stack.setCurrentIndex(1)
        elif "camera" in text.lower() or "相机" in text: self.detail_stack.setCurrentIndex(2)
        elif "力" in text: self.detail_stack.setCurrentIndex(3)
        elif "IO" in text or "io" in text: self.detail_stack.setCurrentIndex(4)
        else: self.detail_stack.setCurrentIndex(0)
    
    # ═══ 刷新 ═══
    
    def _refresh(self):
        self._refresh_topo()
        self._refresh_joints()
        self._refresh_cameras()
        self._refresh_force()
        self._refresh_io()
    
    def _refresh_topo(self):
        pass  # 功能拓扑为静态显示
    
    def _refresh_joints(self):
        if not hasattr(self, 'joint_table'):
            return
        snap = self.sim.get_joint_snapshot()
        self.joint_table.setRowCount(len(snap))
        for i, (jname, s) in enumerate(snap.items()):
            for j, key in enumerate(["pos", "vel", "torque", "temp", "current"]):
                self.joint_table.setItem(i, j, QTableWidgetItem(str(s[key])))
            status = "✅" if s["enabled"] else "❌"
            self.joint_table.setItem(i, 5, QTableWidgetItem(f"{s['current']:.2f}"))
            self.joint_table.setItem(i, 6, QTableWidgetItem(status))
    
    def _refresh_cameras(self):
        if not hasattr(self, 'cam_table'):
            return
        snap = self.sim.get_camera_snapshot()
        self.cam_table.setRowCount(len(snap))
        for i, (cname, s) in enumerate(snap.items()):
            self.cam_table.setItem(i, 0, QTableWidgetItem(cname))
            self.cam_table.setItem(i, 1, QTableWidgetItem(s["size"]))
            self.cam_table.setItem(i, 2, QTableWidgetItem(str(s["fps"])))
            self.cam_table.setItem(i, 3, QTableWidgetItem(s["enc"]))
            self.cam_table.setItem(i, 4, QTableWidgetItem(str(s["ts"])))
    
    def _refresh_force(self):
        if not hasattr(self, 'force_labels'):
            return
        f = self.sim.force
        for k, lbl in self.force_labels.items():
            val = getattr(f, k, 0.0)
            lbl.setText(f"{val:+.3f}")
    
    def _refresh_io(self):
        if not hasattr(self, 'io_table'):
            return
        snap = self.sim.get_io_snapshot()
        self.io_table.setRowCount(len(snap))
        for i, (dev, state) in enumerate(snap.items()):
            self.io_table.setItem(i, 0, QTableWidgetItem(dev))
            self.io_table.setItem(i, 1, QTableWidgetItem(state))
    
    def _populate_nodes(self, nodes):
        pass  # 已迁移到实时监控模块
    
    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"  [{ts}] {msg}")




class ConfigModule(SubModuleWidget):
    """配置中心: 支持 Sys-11纯动作 和 Sys-11+Sys-12混合 两种模式"""
    
    def __init__(self):
        super().__init__("配置中心", [("Sys-11", SYS11_COLOR), ("Sys-12", SYS12_COLOR)])
        
        # ========== 所有控件的深色主题全局样式 ==========
        dark_theme_style = f"""
            QGroupBox {{
                color: {C_WHITE};
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }}
            QLabel {{
                color: {C_WHITE};
            }}
            QSpinBox, QDoubleSpinBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px;
            }}
            QComboBox {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px;
                min-width: 100px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QLineEdit {{
                color: {C_WHITE};
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                padding: 4px;
            }}
            QCheckBox {{
                color: {C_WHITE};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 2px solid {C_GRAY};
                background-color: {C_BG};
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid {C_GREEN};
                background-color: {C_GREEN};
            }}
        """
        self.setStyleSheet(dark_theme_style)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        
        body = QWidget()
        bl = QVBoxLayout()
        bl.setSpacing(16)
        bl.setContentsMargins(8, 8, 8, 8)
        
        # ===== 架构模式选择 =====
        mode_group = QGroupBox("架构模式")
        mode_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        mode_layout = QVBoxLayout()
        
        self.mode_btn_group = QButtonGroup()
        
        # RadioButton 样式：深色背景下使用浅色文字，自定义指示器为圆形单选按钮
        radio_style = f"""
            QRadioButton {{
                color: {C_WHITE};
                spacing: 8px;
                font-size: 14px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid {C_GRAY};
                background-color: {C_BG};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {SYS11_COLOR};
                background-color: {SYS11_COLOR};
            }}
            QRadioButton:hover {{
                color: {SYS11_COLOR};
            }}
        """
        
        self.radio_sys11 = QRadioButton("Sys-11 纯动作系统 (smolvla)")
        self.radio_sys11.setToolTip("仅使用 DiT-B action head，轻量快速，显存 ~4-6GB")
        self.radio_sys11.setStyleSheet(radio_style)
        self.radio_sys11.toggled.connect(self._on_mode_changed)
        self.mode_btn_group.addButton(self.radio_sys11, 0)
        mode_layout.addWidget(self.radio_sys11)
        
        self.radio_mixed = QRadioButton("Sys-11+Sys-12 混合架构 (smolvla_lew)")
        self.radio_mixed.setToolTip("VLA + LeWorldModel 世界模型，更强泛化能力，显存 ~8-12GB")
        self.radio_mixed.setStyleSheet(radio_style)
        self.radio_mixed.toggled.connect(self._on_mode_changed)
        self.mode_btn_group.addButton(self.radio_mixed, 1)
        mode_layout.addWidget(self.radio_mixed)
        
        self.mode_desc = QLabel()
        self.mode_desc.setWordWrap(True)
        self.mode_desc.setStyleSheet(f"color:{C_GRAY}; padding:8px; background:{C_BG}; border-radius:4px;")
        mode_layout.addWidget(self.mode_desc)
        
        mode_group.setLayout(mode_layout)
        bl.addWidget(mode_group)
        
        # ===== 基础配置 =====
        base_group = QGroupBox("基础配置 (两种模式共用)")
        base_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, SYS11_COLOR, 8, 12)}}}")
        base_layout = QFormLayout()
        
        self.cfg_chunk_size = QSpinBox()
        self.cfg_chunk_size.setRange(1, 50)
        self.cfg_chunk_size.setValue(7)
        base_layout.addRow("Chunk Size:", self.cfg_chunk_size)
        
        self.cfg_n_action_steps = QSpinBox()
        self.cfg_n_action_steps.setRange(1, 50)
        self.cfg_n_action_steps.setValue(7)
        base_layout.addRow("Action Steps:", self.cfg_n_action_steps)
        
        self.cfg_n_obs_steps = QSpinBox()
        self.cfg_n_obs_steps.setRange(1, 10)
        self.cfg_n_obs_steps.setValue(1)
        base_layout.addRow("Obs Steps:", self.cfg_n_obs_steps)
        
        base_group.setLayout(base_layout)
        bl.addWidget(base_group)
        
        # ===== VLM 骨干网络 =====
        vlm_group = QGroupBox("VLM 骨干网络 (Sys-11 共性参数)")
        vlm_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, SYS11_COLOR, 8, 12)}}}")
        vlm_layout = QFormLayout()
        
        self.cfg_smolvlm_name = QComboBox()
        self.cfg_smolvlm_name.setEditable(True)
        self.cfg_smolvlm_name.addItems([
            "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
            "HuggingFaceTB/SmolVLM2-2.2B-Video-Instruct"
        ])
        vlm_layout.addRow("VLM 模型:", self.cfg_smolvlm_name)
        
        self.cfg_freeze_vlm = QCheckBox("冻结 VLM 主干 (节省显存)")
        self.cfg_freeze_vlm.setChecked(True)
        self.cfg_freeze_vlm.setToolTip("Sys-11 模式必须 True; Sys-11+Sys-12 混合模式必须 False")
        vlm_layout.addRow("", self.cfg_freeze_vlm)
        
        self.cfg_siglip_size = QSpinBox()
        self.cfg_siglip_size.setRange(32, 224)
        self.cfg_siglip_size.setValue(64)
        self.cfg_siglip_size.setSuffix(" px")
        vlm_layout.addRow("SigLIP 输入:", self.cfg_siglip_size)
        
        self.cfg_num_vision_tokens = QSpinBox()
        self.cfg_num_vision_tokens.setRange(16, 128)
        self.cfg_num_vision_tokens.setValue(64)
        vlm_layout.addRow("视觉 Tokens:", self.cfg_num_vision_tokens)
        
        self.cfg_expert_width = QDoubleSpinBox()
        self.cfg_expert_width.setRange(0.3, 0.8)
        self.cfg_expert_width.setValue(0.5)
        self.cfg_expert_width.setSingleStep(0.05)
        self.cfg_expert_width.setDecimals(2)
        vlm_layout.addRow("Expert 宽度:", self.cfg_expert_width)
        
        vlm_group.setLayout(vlm_layout)
        bl.addWidget(vlm_group)
        
        # ===== Sys-11 Action Head =====
        action_group = QGroupBox("Action Head (Sys-11 DiT-B)")
        action_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, SYS11_COLOR, 8, 12)}}}")
        action_layout = QFormLayout()
        
        self.cfg_action_model = QComboBox()
        self.cfg_action_model.addItems(["DiT-B", "DiT-L", "DiT-test"])
        action_layout.addRow("模型类型:", self.cfg_action_model)
        
        self.cfg_action_hidden = QSpinBox()
        self.cfg_action_hidden.setRange(128, 1024)
        self.cfg_action_hidden.setValue(512)
        action_layout.addRow("隐藏维度:", self.cfg_action_hidden)
        
        self.cfg_action_layers = QSpinBox()
        self.cfg_action_layers.setRange(1, 12)
        self.cfg_action_layers.setValue(2)
        action_layout.addRow("层数:", self.cfg_action_layers)
        
        self.cfg_action_dropout = QDoubleSpinBox()
        self.cfg_action_dropout.setRange(0.0, 0.5)
        self.cfg_action_dropout.setValue(0.2)
        self.cfg_action_dropout.setSingleStep(0.05)
        self.cfg_action_dropout.setDecimals(2)
        action_layout.addRow("Dropout:", self.cfg_action_dropout)
        
        self.cfg_inference_steps = QSpinBox()
        self.cfg_inference_steps.setRange(1, 20)
        self.cfg_inference_steps.setValue(4)
        action_layout.addRow("推理步数:", self.cfg_inference_steps)
        
        self.cfg_diffusion_steps = QSpinBox()
        self.cfg_diffusion_steps.setRange(1, 20)
        self.cfg_diffusion_steps.setValue(4)
        action_layout.addRow("训练重复:", self.cfg_diffusion_steps)
        
        action_group.setLayout(action_layout)
        bl.addWidget(action_group)
        
        # ===== Sys-12 LeWorldModel =====
        self.wm_group = QGroupBox("世界模型 (Sys-12 LeWorldModel)")
        self.wm_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, SYS12_COLOR, 8, 12)}}}")
        wm_layout = QFormLayout()
        
        self.cfg_lew_loss_weight = QDoubleSpinBox()
        self.cfg_lew_loss_weight.setRange(0.01, 1.0)
        self.cfg_lew_loss_weight.setValue(0.1)
        self.cfg_lew_loss_weight.setSingleStep(0.01)
        self.cfg_lew_loss_weight.setDecimals(2)
        wm_layout.addRow("Loss 权重:", self.cfg_lew_loss_weight)
        
        self.cfg_lew_hidden_dim = QSpinBox()
        self.cfg_lew_hidden_dim.setRange(64, 512)
        self.cfg_lew_hidden_dim.setValue(192)
        wm_layout.addRow("Hidden Dim:", self.cfg_lew_hidden_dim)
        
        self.cfg_lew_num_layers = QSpinBox()
        self.cfg_lew_num_layers.setRange(1, 12)
        self.cfg_lew_num_layers.setValue(6)
        wm_layout.addRow("层数:", self.cfg_lew_num_layers)
        
        self.cfg_lew_heads = QComboBox()
        self.cfg_lew_heads.addItems(["4", "8", "16"])
        self.cfg_lew_heads.setCurrentIndex(1)
        wm_layout.addRow("注意力头:", self.cfg_lew_heads)
        
        self.cfg_lew_dim_head = QSpinBox()
        self.cfg_lew_dim_head.setRange(16, 64)
        self.cfg_lew_dim_head.setValue(24)
        wm_layout.addRow("头维度:", self.cfg_lew_dim_head)
        
        self.cfg_lew_mlp_dim = QSpinBox()
        self.cfg_lew_mlp_dim.setRange(256, 2048)
        self.cfg_lew_mlp_dim.setValue(768)
        wm_layout.addRow("MLP Dim:", self.cfg_lew_mlp_dim)
        
        self.cfg_lew_dropout = QDoubleSpinBox()
        self.cfg_lew_dropout.setRange(0.0, 0.3)
        self.cfg_lew_dropout.setValue(0.1)
        self.cfg_lew_dropout.setSingleStep(0.05)
        self.cfg_lew_dropout.setDecimals(2)
        wm_layout.addRow("Dropout:", self.cfg_lew_dropout)
        
        self.cfg_num_video_frames = QSpinBox()
        self.cfg_num_video_frames.setRange(2, 16)
        self.cfg_num_video_frames.setValue(2)
        wm_layout.addRow("视频帧数:", self.cfg_num_video_frames)
        
        self.wm_group.setLayout(wm_layout)
        bl.addWidget(self.wm_group)
        
        # ===== 预处理/后处理 =====
        proc_group = QGroupBox("预处理 / 后处理")
        proc_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        proc_layout = QFormLayout()
        
        self.cfg_resize = QComboBox()
        self.cfg_resize.addItems(["64x64", "128x128", "None (原始)"])
        proc_layout.addRow("Resize:", self.cfg_resize)
        
        self.cfg_bin_gripper = QCheckBox("二值化 Gripper")
        self.cfg_bin_gripper.setChecked(True)
        proc_layout.addRow("", self.cfg_bin_gripper)
        
        self.cfg_dtype = QComboBox()
        self.cfg_dtype.addItems(["float16", "bfloat16", "float32"])
        proc_layout.addRow("Dtype:", self.cfg_dtype)
        
        proc_group.setLayout(proc_layout)
        bl.addWidget(proc_group)
        
        # ===== 优化器 =====
        opt_group = QGroupBox("优化器 & 调度器")
        opt_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        opt_layout = QFormLayout()
        
        self.cfg_lr = QLineEdit("1e-4")
        opt_layout.addRow("学习率:", self.cfg_lr)
        
        self.cfg_grad_clip = QDoubleSpinBox()
        self.cfg_grad_clip.setRange(0.1, 100.0)
        self.cfg_grad_clip.setValue(10.0)
        self.cfg_grad_clip.setDecimals(1)
        opt_layout.addRow("梯度裁剪:", self.cfg_grad_clip)
        
        self.cfg_warmup = QSpinBox()
        self.cfg_warmup.setRange(0, 100000)
        self.cfg_warmup.setValue(1000)
        opt_layout.addRow("Warmup:", self.cfg_warmup)
        
        self.cfg_decay_steps = QSpinBox()
        self.cfg_decay_steps.setRange(1000, 1000000)
        self.cfg_decay_steps.setValue(30000)
        opt_layout.addRow("Decay Steps:", self.cfg_decay_steps)
        
        self.cfg_checkpointing = QCheckBox("Gradient Checkpointing (省显存)")
        self.cfg_checkpointing.setChecked(True)
        opt_layout.addRow("", self.cfg_checkpointing)
        
        opt_group.setLayout(opt_layout)
        bl.addWidget(opt_group)
        
        # ===== 配置预览 =====
        preview_group = QGroupBox("配置预览")
        preview_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        preview_layout = QVBoxLayout()
        
        self.config_preview = QTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setFont(QFont("Consolas", 10))
        self.config_preview.setStyleSheet(f"background:{C_BG}; color:{C_GREEN}; border:1px solid {C_BORDER}; border-radius:4px;")
        self.config_preview.setMaximumHeight(180)
        preview_layout.addWidget(self.config_preview)
        
        preview_group.setLayout(preview_layout)
        bl.addWidget(preview_group)
        
        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(f"QPushButton{{padding:10px 20px; background:{C_GREEN}; color:{C_BG}; border-radius:4px; font-weight:bold;}}")
        save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(save_btn)
        
        load_btn = QPushButton("加载")
        load_btn.setStyleSheet(f"QPushButton{{padding:10px 20px; background:{SYS11_COLOR}; color:{C_WHITE}; border-radius:4px; font-weight:bold;}}")
        load_btn.clicked.connect(self._load_config)
        btn_layout.addWidget(load_btn)
        
        export_btn = QPushButton("导出 YAML")
        export_btn.setStyleSheet(f"QPushButton{{padding:10px 20px; background:{SYS12_COLOR}; color:{C_WHITE}; border-radius:4px; font-weight:bold;}}")
        export_btn.clicked.connect(self._export_yaml)
        btn_layout.addWidget(export_btn)
        
        apply_btn = QPushButton("应用")
        apply_btn.setStyleSheet(f"QPushButton{{padding:10px 20px; background:{C_ORANGE}; color:{C_BG}; border-radius:4px; font-weight:bold;}}")
        apply_btn.clicked.connect(self._apply_config)
        btn_layout.addWidget(apply_btn)
        
        bl.addLayout(btn_layout)
        bl.addStretch()
        
        # 初始化
        self.radio_sys11.setChecked(True)
        self._connect_signals()
        self._update_preview()
        
        body.setLayout(bl)
        scroll.setWidget(body)
        
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        
        container = QWidget()
        container.setLayout(outer)
        self._build_shell(container)
    
    def _on_mode_changed(self, checked):
        if not checked:
            return
        
        is_mixed = self.radio_mixed.isChecked()
        
        if is_mixed:
            self.mode_desc.setText(
                "<b>Sys-11+Sys-12 混合架构</b><br>"
                "VLA + DiT-B + LeWorldModel | 世界模型预测未来视觉 | 显存 ~8-12GB"
            )
            self.cfg_freeze_vlm.setChecked(False)
            self.cfg_freeze_vlm.setEnabled(False)
            self.wm_group.setVisible(True)
        else:
            self.mode_desc.setText(
                "<b>Sys-11 纯动作系统</b><br>"
                "仅 DiT-B Action Head | 轻量快速 | 显存 ~4-6GB"
            )
            self.cfg_freeze_vlm.setChecked(True)
            self.cfg_freeze_vlm.setEnabled(True)
            self.wm_group.setVisible(False)
        
        self._update_preview()
    
    def _connect_signals(self):
        widgets = [
            self.cfg_chunk_size, self.cfg_n_action_steps, self.cfg_n_obs_steps,
            self.cfg_smolvlm_name, self.cfg_freeze_vlm, self.cfg_siglip_size,
            self.cfg_num_vision_tokens, self.cfg_expert_width,
            self.cfg_action_model, self.cfg_action_hidden, self.cfg_action_layers,
            self.cfg_action_dropout, self.cfg_inference_steps, self.cfg_diffusion_steps,
            self.cfg_lew_loss_weight, self.cfg_lew_hidden_dim, self.cfg_lew_num_layers,
            self.cfg_lew_heads, self.cfg_lew_dim_head, self.cfg_lew_mlp_dim,
            self.cfg_lew_dropout, self.cfg_num_video_frames,
            self.cfg_resize, self.cfg_bin_gripper, self.cfg_dtype,
            self.cfg_lr, self.cfg_grad_clip, self.cfg_warmup, self.cfg_decay_steps,
            self.cfg_checkpointing
        ]
        for w in widgets:
            if hasattr(w, 'valueChanged'):
                w.valueChanged.connect(self._update_preview)
            elif hasattr(w, 'currentTextChanged'):
                w.currentTextChanged.connect(self._update_preview)
            elif hasattr(w, 'toggled'):
                w.toggled.connect(self._update_preview)
            elif hasattr(w, 'textChanged'):
                w.textChanged.connect(self._update_preview)
    
    def _get_config_dict(self):
        is_mixed = self.radio_mixed.isChecked()
        d = {
            'type': 'smolvla_lew',
            'mode': 'Sys-11+Sys-12 Mixed' if is_mixed else 'Sys-11 Pure',
            'chunk_size': self.cfg_chunk_size.value(),
            'n_action_steps': self.cfg_n_action_steps.value(),
            'n_obs_steps': self.cfg_n_obs_steps.value(),
            'smolvlm_name': self.cfg_smolvlm_name.currentText(),
            'freeze_smolvlm': self.cfg_freeze_vlm.isChecked(),
            'siglip_image_size': self.cfg_siglip_size.value(),
            'num_vision_tokens': self.cfg_num_vision_tokens.value(),
            'expert_width_multiplier': self.cfg_expert_width.value(),
            'action_model_type': self.cfg_action_model.currentText(),
            'action_hidden_size': self.cfg_action_hidden.value(),
            'action_num_layers': self.cfg_action_layers.value(),
            'action_dropout': self.cfg_action_dropout.value(),
            'num_inference_timesteps': self.cfg_inference_steps.value(),
            'repeated_diffusion_steps': self.cfg_diffusion_steps.value(),
            'enable_lew_world_model': is_mixed,
            'optimizer_lr': self.cfg_lr.text(),
            'optimizer_grad_clip_norm': self.cfg_grad_clip.value(),
            'scheduler_warmup_steps': self.cfg_warmup.value(),
            'scheduler_decay_steps': self.cfg_decay_steps.value(),
            'torch_dtype': self.cfg_dtype.currentText(),
            'gradient_checkpointing': self.cfg_checkpointing.isChecked(),
        }
        if is_mixed:
            d.update({
                'lew_loss_weight': self.cfg_lew_loss_weight.value(),
                'lew_hidden_dim': self.cfg_lew_hidden_dim.value(),
                'lew_num_layers': self.cfg_lew_num_layers.value(),
                'lew_attention_heads': int(self.cfg_lew_heads.currentText()),
                'lew_dim_head': self.cfg_lew_dim_head.value(),
                'lew_mlp_dim': self.cfg_lew_mlp_dim.value(),
                'lew_dropout': self.cfg_lew_dropout.value(),
                'num_video_frames': self.cfg_num_video_frames.value(),
            })
        return d
    
    def _update_preview(self):
        d = self._get_config_dict()
        lines = [f"# smolvla_lew config - {QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm')}"]
        for k, v in d.items():
            lines.append(f"  {k}: {v}")
        self.config_preview.setText("\n".join(lines))
    
    def _save_config(self):
        config_dir = os.path.expanduser("~/xspace/configs/smolvla_lew")
        os.makedirs(config_dir, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = os.path.join(config_dir, f"config_{ts}.txt")
        with open(fp, 'w') as f:
            f.write(self.config_preview.toPlainText())
        QMessageBox.information(self, "保存成功", f"配置已保存到:\n{fp}")
    
    def _load_config(self):
        config_dir = os.path.expanduser("~/xspace/configs/smolvla_lew")
        if not os.path.exists(config_dir):
            QMessageBox.warning(self, "无配置", "配置目录不存在")
            return
        files = sorted([f for f in os.listdir(config_dir) if f.endswith('.txt')], reverse=True)
        if not files:
            QMessageBox.warning(self, "无配置", "没有找到配置文件")
            return
        QMessageBox.information(self, "加载", f"最新配置: {files[0]}\n目录: {config_dir}")
    
    def _export_yaml(self):
        config_dir = os.path.expanduser("~/xspace/configs/smolvla_lew")
        os.makedirs(config_dir, exist_ok=True)
        fp = os.path.join(config_dir, "smolvla_lew_config.yaml")
        d = self._get_config_dict()
        with open(fp, 'w') as f:
            f.write("policy:\n")
            for k, v in d.items():
                f.write(f"  {k}: {v}\n")
        QMessageBox.information(self, "导出成功", f"YAML 配置已导出到:\n{fp}\n\n可用于 lerobot-train 训练")
    
    def _apply_config(self):
        d = self._get_config_dict()
        mode_str = d['mode']
        msg = f"配置已应用!\n\n"
        msg += f"模式: {mode_str}\n"
        msg += f"VLM: {d['smolvlm_name']}\n"
        msg += f"冻结 VLM: {d['freeze_smolvlm']}\n"
        msg += f"Chunk: {d['chunk_size']} / Steps: {d['n_action_steps']}\n"
        if d['enable_lew_world_model']:
            msg += f"LeWorldModel: 启用 (layers={d['lew_num_layers']}, hidden={d['lew_hidden_dim']})"
        else:
            msg += "LeWorldModel: 禁用"
        QMessageBox.information(self, "应用成功", msg)


class MonitorModule(SubModuleWidget):
    """实时监控 — Rerun/RViz 双模式 3D 可视化
    
    Rerun: 现代化机器人数据可视化 (rerun.io)
    RViz:  ROS2 原生 3D 可视化工具
    数据源: 回放会话 | 实时仿真 | Orin真机
    """
    
    def __init__(self):
        super().__init__("实时监控", [("Sys-11", SYS11_COLOR), ("Sys-12", SYS12_COLOR)])
        from hardware_simulator import ReplayEngine
        
        self.replay = ReplayEngine()
        self._rerun_process = None
        self._rviz_process = None
        
        body = QWidget()
        bl = QVBoxLayout()
        bl.setSpacing(10)
        bl.setContentsMargins(8, 8, 8, 8)
        
        # ═══ 左右分栏: 信号源 | 引擎 ═══
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        
        # 左侧: 信号源 (竖排)
        src_group = QGroupBox("信号源")
        src_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, C_CYAN, 8, 12)}}}")
        src_layout = QVBoxLayout()
        src_layout.setSpacing(8)
        
        self._src_group = QButtonGroup()
        radio_style = f"QRadioButton{{color:{C_WHITE}; spacing:6px; font-size:12px; padding:2px 0;}} QRadioButton::indicator{{width:14px;height:14px;border-radius:7px;border:2px solid {C_GRAY};background:{C_BG};}} QRadioButton::indicator:checked{{border-color:{C_CYAN};background:{C_CYAN};}}"
        
        self.src_replay = QRadioButton("回放数据")
        self.src_replay.setStyleSheet(radio_style); self.src_replay.setChecked(True)
        self._src_group.addButton(self.src_replay, 0)
        src_layout.addWidget(self.src_replay)
        
        self.mon_session_combo = QComboBox()
        self.mon_session_combo.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:3px 6px; font-size:10px;")
        self._refresh_monitor_sessions()
        src_layout.addWidget(self.mon_session_combo)
        
        self.src_sim = QRadioButton("仿真数据")
        self.src_sim.setStyleSheet(radio_style)
        self._src_group.addButton(self.src_sim, 1)
        src_layout.addWidget(self.src_sim)
        
        self.src_demo = QRadioButton("演示动画")
        self.src_demo.setStyleSheet(radio_style)
        self._src_group.addButton(self.src_demo, 2)
        src_layout.addWidget(self.src_demo)
        
        self.src_live = QRadioButton("实时数据")
        self.src_live.setStyleSheet(radio_style)
        self._src_group.addButton(self.src_live, 3)
        src_layout.addWidget(self.src_live)
        
        self.src_dummy = QRadioButton("离线仿真")
        self.src_dummy.setStyleSheet(radio_style)
        self._src_group.addButton(self.src_dummy, 4)
        src_layout.addWidget(self.src_dummy)
        
        self.src_pusht = QRadioButton("PushT数据")
        self.src_pusht.setStyleSheet(radio_style)
        self._src_group.addButton(self.src_pusht, 5)
        src_layout.addWidget(self.src_pusht)
        
        self.src_status = QLabel("回放: 未加载")
        self.src_status.setStyleSheet(f"color:{C_GRAY}; font-size:10px; padding-top:4px;")
        src_layout.addWidget(self.src_status)
        src_group.setLayout(src_layout)
        top_row.addWidget(src_group)
        
        # 右侧: 可视化引擎 (竖排)
        eng_group = QGroupBox("可视化引擎")
        eng_group.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; font-weight:bold; {card_style(C_CARD, C_PURPLE, 8, 12)}}}")
        eng_layout = QVBoxLayout()
        eng_layout.setSpacing(8)
        
        self.mon_rerun_btn = QPushButton("📊 Rerun (Web)")
        self.mon_rerun_btn.setCheckable(True); self.mon_rerun_btn.setChecked(True)
        self.mon_rerun_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, True))
        self.mon_rerun_btn.clicked.connect(lambda: self._switch_mode("rerun"))
        eng_layout.addWidget(self.mon_rerun_btn)
        
        self.mon_rviz_btn = QPushButton("🤖 RViz (ROS2)")
        self.mon_rviz_btn.setCheckable(True)
        self.mon_rviz_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, False))
        self.mon_rviz_btn.clicked.connect(lambda: self._switch_mode("rviz"))
        eng_layout.addWidget(self.mon_rviz_btn)
        
        self.mon_mode_label = QLabel("端口: 9877")
        self.mon_mode_label.setStyleSheet(f"color:{C_GRAY}; font-size:10px; padding:2px 0;")
        eng_layout.addWidget(self.mon_mode_label)
        eng_layout.addStretch()
        eng_group.setLayout(eng_layout)
        top_row.addWidget(eng_group)
        
        bl.addLayout(top_row)
        
        # ═══ 操作栏: 启动+停止+状态 ═══
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)
        
        btn_base = "border:none; border-radius:6px; padding:10px 32px; font-weight:bold; font-size:15px;"
        self.mon_launch_btn = QPushButton("▶ 启动")
        self.mon_launch_btn.setStyleSheet(f"QPushButton{{background:{C_GREEN}; color:#0d1117; {btn_base}}} QPushButton:hover{{background:#4ade80;}} QPushButton:pressed{{background:#22c55e;}} QPushButton:disabled{{background:{C_DIM}; color:{C_GRAY};}}")
        self.mon_launch_btn.clicked.connect(self._mon_launch)
        ctrl_row.addWidget(self.mon_launch_btn)
        
        self.mon_stop_btn = QPushButton("⏹ 停止")
        self.mon_stop_btn.setStyleSheet(f"QPushButton{{background:{C_RED}; color:white; {btn_base}}} QPushButton:hover{{background:#f87171;}} QPushButton:pressed{{background:#ef4444;}} QPushButton:disabled{{background:{C_DIM}; color:{C_GRAY};}}")
        self.mon_stop_btn.clicked.connect(self._mon_stop)
        self.mon_stop_btn.setEnabled(False)
        ctrl_row.addWidget(self.mon_stop_btn)
        
        ctrl_row.addStretch()
        self.mon_status = QLabel("● 就绪")
        self.mon_status.setStyleSheet(f"color:{C_GRAY}; padding:6px 16px; background:{C_BG2}; border-radius:4px; font-size:12px;")
        ctrl_row.addWidget(self.mon_status)
        bl.addLayout(ctrl_row)
        
        # ═══ Topic/Node 面板 (水平分割) ═══
        tn_split = QHBoxLayout()
        tn_split.setSpacing(8)
        
        # Topic 列表
        topic_box = QVBoxLayout()
        topic_header = QHBoxLayout()
        topic_header.addWidget(QLabel("Topics"))
        self.tn_refresh_btn = QPushButton("刷新")
        self.tn_refresh_btn.setStyleSheet(f"background:{C_BLUE}; color:white; border:none; border-radius:3px; padding:2px 10px; font-size:10px;")
        self.tn_refresh_btn.clicked.connect(self._refresh_topic_node_list)
        topic_header.addWidget(self.tn_refresh_btn)
        topic_header.addStretch()
        topic_box.addLayout(topic_header)
        
        self.topic_list_view = QTextEdit()
        self.topic_list_view.setReadOnly(True)
        self.topic_list_view.setFont(QFont("Consolas", 9))
        self.topic_list_view.setStyleSheet(f"color:{C_CYAN}; padding:4px; background:#0a0e14; border:1px solid {C_BORDER}; border-radius:4px;")
        self.topic_list_view.setMaximumHeight(150)
        self.topic_list_view.setHtml("<i>等待数据...</i>")
        topic_box.addWidget(self.topic_list_view)
        tn_split.addLayout(topic_box, 1)
        
        # Node 列表
        node_box = QVBoxLayout()
        node_box.addWidget(QLabel("Nodes"))
        
        self.node_list_view = QTextEdit()
        self.node_list_view.setReadOnly(True)
        self.node_list_view.setFont(QFont("Consolas", 9))
        self.node_list_view.setStyleSheet(f"color:{C_PURPLE}; padding:4px; background:#0a0e14; border:1px solid {C_BORDER}; border-radius:4px;")
        self.node_list_view.setMaximumHeight(150)
        self.node_list_view.setHtml("<i>等待数据...</i>")
        node_box.addWidget(self.node_list_view)
        tn_split.addLayout(node_box, 1)
        
        bl.addLayout(tn_split)
        
        # ═══ 实时信号追踪面板 ═══
        self.mon_data_preview = QTextEdit()
        self.mon_data_preview.setReadOnly(True)
        self.mon_data_preview.setFont(QFont("Consolas", 10))
        self.mon_data_preview.setStyleSheet(f"color:{C_GREEN}; padding:8px; background:#0a0e14; border:1px solid {C_BORDER}; border-radius:4px;")
        self.mon_data_preview.setMinimumHeight(120)
        self.mon_data_preview.setHtml("<i>选择「实时数据」查看 Orin 信号追踪</i>")
        bl.addWidget(self.mon_data_preview)
        
        # ═══ 日志 ═══
        self.mon_log = QTextEdit()
        self.mon_log.setReadOnly(True)
        self.mon_log.setFont(QFont("Consolas", 9))
        self.mon_log.setStyleSheet(f"background:#0a0e14; color:{C_GREEN}; border:1px solid {C_BORDER}; border-radius:4px; padding:6px;")
        self.mon_log.setText("  就绪\n")
        bl.addWidget(self.mon_log)
        
        body.setLayout(bl)
        self._build_shell(body)
        
        # 信号源切换
        self.src_replay.toggled.connect(lambda v: v and self._on_source_changed("replay"))
        self.src_sim.toggled.connect(lambda v: v and self._on_source_changed("sim"))
        self.src_demo.toggled.connect(lambda v: v and self._on_source_changed("demo"))
        self.src_live.toggled.connect(lambda v: v and self._on_source_changed("live"))
        self.src_dummy.toggled.connect(lambda v: v and self._on_source_changed("dummy"))
        self.src_pusht.toggled.connect(lambda v: v and self._on_source_changed("pusht"))
    
    def _mode_btn_style(self, color, active):
        if active:
            return f"background:{color}; color:white; border:none; border-radius:6px; padding:10px 20px; font-weight:bold; font-size:14px;"
        return f"background:{color}33; color:{color}; border:1px solid {color}44; border-radius:6px; padding:10px 20px; font-weight:bold; font-size:14px;"
    
    # ═══ 操作 ═══
    
    def _refresh_monitor_sessions(self):
        self.mon_session_combo.clear()
        self.mon_session_combo.addItem("— 选择回放会话 —")
        for s in self.replay.list_sessions():
            self.mon_session_combo.addItem(s)
    
    def _switch_mode(self, mode):
        if mode == "rerun":
            self.mon_rerun_btn.setChecked(True)
            self.mon_rerun_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, True))
            self.mon_rviz_btn.setChecked(False)
            self.mon_rviz_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, False))
            self.mon_mode_label.setText("本地 Web Viewer · port 9877")
        else:
            self.mon_rviz_btn.setChecked(True)
            self.mon_rviz_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, True))
            self.mon_rerun_btn.setChecked(False)
            self.mon_rerun_btn.setStyleSheet(self._mode_btn_style(C_PURPLE, False))
            self.mon_mode_label.setText("ROS2 RViz · 需 source 环境")
    
    def _on_source_changed(self, src):
        """信号源切换"""
        if src == "replay":
            self.mon_session_combo.setEnabled(True)
            session = self.mon_session_combo.currentText()
            if session and not session.startswith("—"):
                self._mon_load_session()
            self.src_status.setText("回放: 选择会话")
        elif src == "sim":
            self.mon_session_combo.setEnabled(False)
            self._mon_use_sim()
            self.src_status.setText("仿真: Z700 14-DOF")
        elif src == "demo":
            self.mon_session_combo.setEnabled(False)
            self._gen_rrd_demo()
            self.src_status.setText("演示: 生成 .rrd 动画")
        elif src == "live":
            self.mon_session_combo.setEnabled(False)
            self._start_live_monitor()
            self.src_status.setText("实时: 连接 Orin...")
        elif src == "dummy":
            self.mon_session_combo.setEnabled(False)
            self._start_dummy_monitor()
            self.src_status.setText("离线: 本地仿真")
        elif src == "pusht":
            self.mon_session_combo.setEnabled(False)
            self._gen_pusht_rrd()
            self.src_status.setText("PushT: 已生成 .rrd")
    
    def _mon_load_session(self):
        session = self.mon_session_combo.currentText()
        if not session or session.startswith("—"):
            return
        if self.replay.load_session(session):
            self._mlog(f"✅ 加载 {session} · {self.replay.total_frames}帧 · {self.replay.duration:.1f}s")
            self.mon_data_preview.setHtml(
                f"<b>✅ 已加载: {session}</b><br>"
                f"帧数: {self.replay.total_frames} | 时长: {self.replay.duration:.2f}s<br>"
                f"关节数据: {'✅' if self.replay.get_frame(0) and self.replay.get_frame(0).get('joints') else '❌'}<br>"
                f"<br>点击「启动可视化」开始"
            )
        else:
            self._mlog(f"❌ 加载失败: {session}")
    
    def _mon_use_sim(self):
        """使用仿真数据"""
        from hardware_simulator import get_simulator
        self._sim_src = get_simulator("sim")
        self._mlog("🖥️ 数据源: 仿真引擎 (14-DOF 正弦波)")
        self.mon_data_preview.setHtml(
            "<b>🖥️ 仿真数据源</b><br>"
            "Z700 14-DOF 正弦波 · 7路相机测试图案 · 六维力传感器<br>"
            "点击「启动可视化」查看实时仿真数据"
        )
    
    def _mon_launch(self):
        """根据信号源启动可视化"""
        mode = "rerun" if self.mon_rerun_btn.isChecked() else "rviz"
        
        if mode == "rviz":
            self._launch_rviz()
            return
        
        # Rerun 模式
        if self.src_replay.isChecked():
            # 确保回放数据已加载
            if self.replay.total_frames <= 0:
                self.replay.load_session("replay_001")
            import os
            bag_rrd = os.path.expanduser("~/yspace/replay_data/zmax_bag_001.rrd")
            if os.path.exists(bag_rrd):
                self._mlog("📼 使用 rosbag 回放 (328秒真机数据)")
                self.src_status.setText("回放: rosbag 328s")
            else:
                self._gen_replay_rrd()
            self._start_replay_display()
        elif self.src_sim.isChecked():
            self._gen_sim_rrd()
        elif self.src_live.isChecked():
            self._gen_live_rrd()
        elif self.src_pusht.isChecked():
            pass  # 已在上一步生成
        
        self._open_rerun_local()
    
    def _launch_rerun(self):
        """启动 Rerun — 全部在后台 QThread 中运行"""
        try:
            import rerun as rr
        except ImportError:
            self._mlog("❌ rerun-sdk 未安装")
            return
        
        if self.replay.total_frames <= 0 and not hasattr(self, '_sim_src'):
            self._mlog("⚠️ 请先选择数据源")
            return
        
        self._mlog("📊 启动 Rerun (后台线程)...")
        
        # 创建后台工作线程
        self._rerun_worker = _RerunStreamWorker(
            replay=self.replay,
            sim=getattr(self, '_sim_src', None),
        )
        self._rerun_worker.log_msg.connect(self._mlog)
        self._rerun_worker.finished.connect(self._on_rerun_done)
        self._rerun_worker.start()
        
        self.mon_launch_btn.setEnabled(False)
        self.mon_stop_btn.setEnabled(True)
        self.mon_status.setText("🟢 运行中")
        self.mon_status.setStyleSheet(f"color:{C_GREEN}; padding:6px 14px; background:{C_BG2}; border-radius:4px; font-size:11px;")
    
    def _on_rerun_done(self):
        self.mon_launch_btn.setEnabled(True)
        self.mon_stop_btn.setEnabled(False)
        self.mon_status.setText("● 已停止")
        self.mon_status.setStyleSheet(f"color:{C_GRAY}; padding:6px 14px; background:{C_BG2}; border-radius:4px; font-size:11px;")
        self._mlog("⏹ Rerun 已停止")
    
    def _launch_rviz(self):
        """启动 RViz"""
        import subprocess
        
        rviz_config = os.path.expanduser("~/lerobot-smolvla-lew/launch/zmax_monitor.rviz")
        
        cmd = ["rviz2"]
        if os.path.exists(rviz_config):
            cmd += ["-d", rviz_config]
        
        self._mlog(f"🤖 启动 RViz: {' '.join(cmd)}")
        
        try:
            self._rviz_process = subprocess.Popen(cmd, 
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._mlog("   RViz 已启动（独立窗口）")
            self._mlog("   注意: 需要 ROS2 环境 source 后 RViz 才能连接")
        except FileNotFoundError:
            self._mlog("❌ rviz2 未找到，请确保 ROS2 已安装并 source")
            return
        
        self.mon_launch_btn.setEnabled(False)
        self.mon_stop_btn.setEnabled(True)
        self.mon_status.setText("🟢 运行中")
        self.mon_status.setStyleSheet(f"color:{C_GREEN}; padding:6px 14px; background:{C_BG2}; border-radius:4px; font-size:11px;")
    
    def _mon_stop(self):
        """停止可视化"""
        self._live_running = False
        self._replay_display_running = False
        if hasattr(self, '_live_timer'):
            self._live_timer.stop()
        if hasattr(self, '_replay_timer'):
            self._replay_timer.stop()
        if hasattr(self, '_rerun_worker') and self._rerun_worker:
            self._rerun_worker.stop()
            self._rerun_worker = None
        self.replay.playing = False
        
        if self._rviz_process and self._rviz_process.poll() is None:
            self._rviz_process.terminate()
            self._mlog("⏹ RViz 已停止")
        
        self.mon_launch_btn.setEnabled(True)
        self.mon_stop_btn.setEnabled(False)
        self.mon_status.setText("● 已停止")
        self.mon_status.setStyleSheet(f"color:{C_GRAY}; padding:6px 14px; background:{C_BG2}; border-radius:4px; font-size:11px;")
        self._mlog("⏹ 可视化已停止")
    
    def _mlog(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.mon_log.append(f"  [{ts}] {msg}")
    
    def _gen_rrd_demo(self):
        """生成演示 .rrd 文件 — 6-DOF 机器人动画"""
        import rerun as rr, math, os
        
        out = os.path.expanduser("~/yspace/replay_data/robot_demo.rrd")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        
        self._mlog("📊 生成演示动画 .rrd...")
        rr.init('Z-MAX Robot Demo', spawn=False)
        
        rr.log('world/xyz', rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.5,0,0],[0,0.5,0],[0,0,0.5]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]), static=True)
        rr.log('robot/base', rr.Points3D([[0,0,0]], radii=[0.08], colors=[[100,100,100]]), static=True)
        
        trail = []
        for frame in range(60):
            t = frame * 0.1
            rr.set_time('frame', sequence=frame)
            pts = []; x = y = z = 0.0
            for j in range(6):
                phase = j * 0.8; amp = 0.3/(j+1)
                x += math.cos(t*2+phase)*amp*0.5
                y += math.sin(t*2+phase)*amp*0.6
                z += math.cos(t*1.5+phase)*amp*0.3
                pts.append([x,y,z])
            colors = [[255-i*30,100+i*20,i*40] for i in range(6)]
            rr.log('robot/joints', rr.Points3D(pts, radii=[0.05]*6, colors=colors))
            for i in range(5):
                rr.log(f'robot/link_{i}', rr.Arrows3D(
                    origins=[pts[i]], vectors=[[pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1], pts[i+1][2]-pts[i][2]]], radii=[0.015]))
            trail.append(pts[-1])
            if len(trail)>1: rr.log('robot/trail', rr.LineStrips3D([trail[-60:]], colors=[[255,200,0]]))
        
        rr.save(out)
        size_kb = os.path.getsize(out)/1024
        self._mlog(f"✅ {out} ({size_kb:.0f}KB)")
        self._mlog(f"   🌐 打开 https://rerun.io/viewer → 拖入 .rrd 文件")
    
    def _gen_replay_rrd(self):
        """回放数据 → .rrd"""
        if self.replay.total_frames <= 0:
            self._mlog("⚠️ 请先加载回放会话")
            return
        import rerun as rr
        self._mlog(f"📊 生成回放 .rrd ({self.replay.total_frames}帧)...")
        rr.init("replay", spawn=False)
        rr.log("world/xyz", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.3,0,0],[0,0.3,0],[0,0,0.3]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]), static=True)
        
        self.replay.current_frame = 0
        for seq in range(self.replay.total_frames):
            frame = self.replay.get_frame()
            if not frame: break
            rr.set_time("frame", sequence=seq)
            joints = frame.get("joints", [])
            if len(joints) >= 6:
                pts = [[i*0.2, joints[i]*0.8, 0] for i in range(6)]
                rr.log("robot/joints", rr.Points3D(pts, radii=[0.05]*6,
                    colors=[[255-i*30,100+i*20,i*40] for i in range(6)]))
                for i in range(5):
                    rr.log(f"robot/link_{i}", rr.Arrows3D(origins=[pts[i]],
                        vectors=[[pts[i+1][0]-pts[i][0],pts[i+1][1]-pts[i][1],0]], radii=[0.01]))
            self.replay.advance()
        
        out = os.path.expanduser("~/yspace/replay_data/replay.rrd")
        rr.save(out)
        self._mlog(f"   ✅ {out} ({os.path.getsize(out)/1024:.0f}KB)")
    
    def _gen_sim_rrd(self):
        """仿真数据 → .rrd"""
        from hardware_simulator import get_simulator
        import rerun as rr, math
        sim = get_simulator("sim")
        self._mlog("📊 生成仿真 .rrd (60帧)...")
        rr.init("sim", spawn=False)
        rr.log("world/xyz", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.3,0,0],[0,0.3,0],[0,0,0.3]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]), static=True)
        
        sim.start()
        for seq in range(60):
            snap = sim.get_joint_snapshot()
            positions = [s["pos"] for s in list(snap.values())[:6]]
            rr.set_time("frame", sequence=seq)
            pts = [[i*0.2, positions[i]*0.8, 0] for i in range(min(6,len(positions)))]
            rr.log("robot/joints", rr.Points3D(pts, radii=[0.05]*6,
                colors=[[255-i*30,100+i*20,i*40] for i in range(6)]))
            import time; time.sleep(0.01)
        sim.stop()
        
        out = os.path.expanduser("~/yspace/replay_data/sim.rrd")
        rr.save(out)
        self._mlog(f"   ✅ {out} ({os.path.getsize(out)/1024:.0f}KB)")
    
    def _start_live_monitor(self):
        """SSH 到 Orin 拉取实时 ROS2 topic/node 列表 + 数据"""
        import subprocess
        
        self._mlog("🔍 实时监控: 连接 Orin...")
        self._live_data = {"status": "连接中...", "topics": {}, "topic_list": [], "node_list": []}
        
        # 获取 topic/node 列表
        self._fetch_topic_node_list()
        self._show_topic_node_lists()
        
        import threading
        def _poll():
            while getattr(self, '_live_running', True):
                try:
                    r = subprocess.run([
                        "ssh", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
                        "source /opt/ros/humble/setup.bash && "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /gripper_pos 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /robot/joint_states 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /robot/force_torque 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /robot_status 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /emergency_stop 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /tower_light/status 2>/dev/null; "
                        "echo '---'; "
                        "ROS_DOMAIN_ID=23 ros2 topic echo --once /robot/tcp_pose 2>/dev/null "],
                        capture_output=True, text=True, timeout=8)
                    out = r.stdout.strip()
                    if out:
                        topics = {}
                        sections = out.split('---')
                        topic_names = ["gripper_pos", "joint_states", "force_torque", 
                                      "robot_status", "emergency_stop", "tower_light", "tcp_pose"]
                        for i, sec in enumerate(sections):
                            sec = sec.strip()
                            if sec and i < len(topic_names):
                                # 提取关键数据行
                                key_lines = []
                                for line in sec.split('\n')[:6]:
                                    line = line.strip()
                                    if line and not line.startswith('---'):
                                        key_lines.append(line)
                                topics[topic_names[i]] = " | ".join(key_lines[:3]) if key_lines else "无数据"
                        self._live_data["topics"] = topics
                        self._live_data["_ts"] = {t: time.time() for t in topics}
                        self._live_data["status"] = "🟢 在线"
                    else:
                        self._live_data["status"] = "⚠️ 机器人idle"
                except:
                    self._live_data["status"] = "🔴 断开"
                time.sleep(1.5)
        
        self._live_running = True
        t = threading.Thread(target=_poll, daemon=True)
        t.start()
        
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._update_live_display)
        self._live_timer.start(500)
        self._mlog("   ✅ 实时监控已启动")
    
    def _start_dummy_monitor(self):
        """离线仿真 — 本地生成假数据替代 Orin"""
        from hardware_simulator import get_simulator
        
        self._mlog("🖥️ 离线仿真: 本地假数据...")
        sim = get_simulator("sim")
        sim.start()
        
        self._live_data = {"status": "🖥️ 离线仿真", "topics": {}, "topic_list": [], "node_list": []}
        
        # 假 topic/node 列表
        self._live_data["topic_list"] = [
            "/robot/joint_states", "/gripper_pos", "/robot/force_torque",
            "/robot/tcp_pose", "/robot_status", "/emergency_stop",
            "/tower_light/status", "/real_joint_states", "/joint_states",
            "/tf", "/tf_static", "/parameter_events", "/rosout",
        ]
        self._live_data["node_list"] = [
            "/robot_driver", "/gripper_driver", "/motion", "/vision",
            "/vision_tag", "/robot_state_publisher", "/rviz2",
        ]
        self._show_topic_node_lists()
        
        import threading
        def _poll():
            while getattr(self, '_live_running', True):
                snap = sim.get_joint_snapshot()
                topics = {}
                positions = list(snap.values())[:6]
                topics["joint_states"] = " | ".join([f"J{i+1}:{s['pos']:+.4f}" for i, s in enumerate(positions)])
                topics["gripper_pos"] = f"data: {sim.io.gripper_left:.1f}"
                topics["force_torque"] = f"Fx:{sim.force.fx:+.3f} Fy:{sim.force.fy:+.3f} Fz:{sim.force.fz:+.3f}"
                topics["robot_status"] = '{"success":true,"mode":"sim"}'
                topics["emergency_stop"] = f"data: {str(sim.io.estop).lower()}"
                topics["tower_light"] = f"{['灭','红','黄','绿'][sim.io.tower_light]}"
                topics["tcp_pose"] = f"x:{math.sin(time.time())*0.1:.4f} y:0.0 z:0.27"
                self._live_data["topics"] = topics
                self._live_data["_ts"] = {t: time.time() for t in topics}
                time.sleep(0.5)
        
        self._live_running = True
        t = threading.Thread(target=_poll, daemon=True)
        t.start()
        
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._update_live_display)
        self._live_timer.start(500)
        self._mlog("   ✅ 离线仿真已启动")
    
    def _refresh_topic_node_list(self):
        """手动刷新 Topic/Node 列表"""
        self._mlog("🔄 刷新 Topic/Node 列表...")
        self._fetch_topic_node_list()
        self._show_topic_node_lists()
    
    def _fetch_topic_node_list(self):
        """SSH 获取 topic/node 列表"""
        import subprocess
        try:
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "nvidia@192.168.23.10",
                 "source /opt/ros/humble/setup.bash && "
                 "echo '===TOPICS===' && ROS_DOMAIN_ID=23 ros2 topic list 2>/dev/null && "
                 "echo '===NODES===' && ROS_DOMAIN_ID=23 ros2 node list 2>/dev/null"],
                capture_output=True, text=True, timeout=10)
            out = r.stdout
            if '===TOPICS===' in out:
                parts = out.split('===TOPICS===')
                if len(parts) > 1:
                    node_part = parts[1].split('===NODES===')
                    self._live_data["topic_list"] = [t.strip() for t in node_part[0].split('\n') if t.strip()]
                    if len(node_part) > 1:
                        self._live_data["node_list"] = [n.strip() for n in node_part[1].split('\n') if n.strip()]
            self._mlog(f"   ✅ {len(self._live_data.get('topic_list',[]))} topics, {len(self._live_data.get('node_list',[]))} nodes")
        except Exception as e:
            self._mlog(f"   ⚠️ {e}")
    
    def _show_topic_node_lists(self):
        """显示 Topic/Node 列表到独立面板"""
        tl = self._live_data.get("topic_list", [])
        nl = self._live_data.get("node_list", [])
        
        t_html = "<pre style='color:#39d2c0; font-size:10px; margin:0;'>"
        t_html += f"<b>Topics ({len(tl)})</b>\n"
        for t in tl[:20]:
            t_html += f"  {t}\n"
        if len(tl) > 20:
            t_html += f"  ... 共 {len(tl)} 个\n"
        t_html += "</pre>"
        self.topic_list_view.setHtml(t_html)
        
        n_html = "<pre style='color:#bc8cff; font-size:10px; margin:0;'>"
        n_html += f"<b>Nodes ({len(nl)})</b>\n"
        for n in nl[:15]:
            n_html += f"  {n}\n"
        if len(nl) > 15:
            n_html += f"  ... 共 {len(nl)} 个\n"
        n_html += "</pre>"
        self.node_list_view.setHtml(n_html)
    
    def _update_live_display(self):
        """实时面板: 信号追踪 + 余晖效果"""
        d = getattr(self, '_live_data', {})
        now = time.time()
        
        lines = ["<pre style='color:#3fb950; font-size:10px; margin:0;'>"]
        lines.append("<b>── 实时信号追踪 ──</b>\n")
        
        topics_data = d.get("topics", {})
        if topics_data:
            for topic, value in topics_data.items():
                # 计算新鲜度 → 颜色渐变
                last_ts = d.get("_ts", {}).get(topic, 0)
                age = now - last_ts
                if age < 0.5:
                    color = "#3fb950"  # 鲜绿
                    bright = "<b>"
                    endb = "</b>"
                elif age < 2.0:
                    r = int(0x3f + (0x48-0x3f) * (age-0.5)/1.5)
                    g = int(0xb9 - (0xb9-0x4f) * (age-0.5)/1.5)
                    b = int(0x50 - (0x50-0x58) * (age-0.5)/1.5)
                    color = f"#{r:02x}{g:02x}{b:02x}"
                    bright = ""; endb = ""
                else:
                    color = "#484f58"  # 暗灰
                    bright = ""; endb = ""
                
                lines.append(f"  <span style='color:{color}'>{bright}{topic:24s}{endb}</span> {value}\n")
        else:
            lines.append("  等待数据...\n")
        
        lines.append("</pre>")
        self.mon_data_preview.setHtml("".join(lines))
    
    def _gen_live_rrd(self):
        """实时采集 5 秒数据 → .rrd"""
        import rerun as rr, os
        self._mlog("📊 采集 5 秒实时数据...")
        
        rr.init("live", spawn=False)
        rr.log("world/xyz", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.3,0,0],[0,0.3,0],[0,0,0.3]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]), static=True)
        
        for seq in range(50):
            d = getattr(self, '_live_data', {})
            joints = d.get("joints", [])
            try:
                positions = [float(v) for v in joints[:6]]
                rr.set_time("frame", sequence=seq)
                pts = [[i*0.2, positions[i]*0.8, 0] for i in range(min(6,len(positions)))]
                rr.log("robot/joints", rr.Points3D(pts, radii=[0.05]*6,
                    colors=[[255-i*30,100+i*20,i*40] for i in range(6)]))
            except: pass
            import time; time.sleep(0.1)
        
        out = os.path.expanduser("~/yspace/replay_data/live.rrd")
        rr.save(out)
        self._mlog(f"   ✅ {out} ({os.path.getsize(out)/1024:.0f}KB)")
    
    def _start_replay_display(self):
        """回放数据终端显示 — 定时刷新信号追踪面板"""
        if self.replay.total_frames <= 0:
            return
        
        self._mlog(f"📺 终端回放显示: {self.replay.total_frames} 帧")
        self.replay.current_frame = 0
        
        def _show_frame():
            if not getattr(self, '_replay_display_running', True):
                self._replay_timer.stop()
                return
            
            frame = self.replay.get_frame()
            if not frame:
                self._replay_timer.stop()
                return
            
            joints = frame.get("joints", [])
            topics = {}
            if len(joints) >= 6:
                topics["joint_states"] = " | ".join([f"J{i+1}:{joints[i]:+.4f}" for i in range(6)])
            topics["gripper_pos"] = f"data: {frame.get('gripper', '?')}"
            topics["frame"] = f"{self.replay.current_frame}/{self.replay.total_frames}"
            topics["time"] = f"{frame.get('ts',0)-self.replay.frames[0]['ts']:.2f}s" if self.replay.frames else "?"
            
            self._live_data = {"status": "📼 回放中", "topics": topics, "_ts": {t: time.time() for t in topics}}
            self._update_live_display()
            self.replay.advance()
        
        self._replay_display_running = True
        self._replay_timer = QTimer()
        self._replay_timer.timeout.connect(_show_frame)
        self._replay_timer.start(200)
        self._mlog("   ✅ 终端显示已启动")
    
    def _gen_pusht_rrd(self):
        """PushT数据集 → .rrd — 1个完整episode轨迹"""
        import rerun as rr
        
        self._mlog("📊 加载 PushT 数据集...")
        try:
            from datasets import load_dataset
            ds = load_dataset("lerobot/pusht", split="train[:100]")
        except:
            self._mlog("❌ 无法加载 PushT")
            return
        
        rr.init("PushT LeRobot", spawn=False)
        # 固定坐标系和背景
        rr.log("world/xy", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0]], vectors=[[0.6,0,0],[0,0.6,0]],
            colors=[[255,0,0],[0,255,0]], labels=["X","Y"]), static=True)
        
        prev_pos = None
        total = len(ds)
        for f_idx, row in enumerate(ds):
            state = row["observation.state"]
            action = row["action"]
            x, y = float(state[0]), float(state[1])
            
            rr.set_time("frame", sequence=f_idx)
            
            # Agent 当前位置 (蓝色圆点)
            rr.log("agent/current", rr.Points3D([[x, y, 0]], 
                radii=[0.02], colors=[[30,144,255]]))
            
            # Action 方向 (浅蓝箭头)
            rr.log("agent/action", rr.Arrows3D(
                origins=[[x, y, 0]],
                vectors=[[float(action[0])*0.03, float(action[1])*0.03, 0]],
                colors=[[100,200,255]]))
            
            # 轨迹连线
            if prev_pos is not None:
                rr.log("agent/trail", rr.LineStrips3D(
                    [[prev_pos, [x, y, 0]]], colors=[[60,160,255,120]]))
            prev_pos = [x, y, 0]
        
        out = os.path.expanduser("~/yspace/replay_data/pusht.rrd")
        rr.save(out)
        self._mlog(f"✅ {out} ({os.path.getsize(out)/1024:.0f}KB, {total} frames)")

    def _open_rerun_local(self):
        """根据信号源选 .rrd → subprocess 启动 rerun --web-viewer"""
        import subprocess, os
        
        # 根据信号源选文件
        if self.src_replay.isChecked():
            bag_rrd = os.path.expanduser("~/yspace/replay_data/zmax_bag_001.rrd")
            if os.path.exists(bag_rrd):
                rrd = bag_rrd
            else:
                rrd = os.path.expanduser("~/yspace/replay_data/replay.rrd")
        elif self.src_sim.isChecked():
            rrd = os.path.expanduser("~/yspace/replay_data/sim.rrd")
        elif self.src_live.isChecked():
            rrd = os.path.expanduser("~/yspace/replay_data/live.rrd")
        elif self.src_pusht.isChecked():
            rrd = os.path.expanduser("~/yspace/replay_data/pusht.rrd")
        else:
            rrd = os.path.expanduser("~/yspace/replay_data/robot_demo.rrd")
        
        if not os.path.exists(rrd):
            self._mlog(f"⚠️ .rrd 不存在: {rrd}")
            return
        
        # 杀掉旧的 rerun 进程，释放端口
        subprocess.run(["pkill", "-f", "rerun.*web-viewer"], 
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._mlog("🚀 启动 Rerun Web Viewer...")
        try:
            subprocess.Popen(
                ["rerun", rrd, "--web-viewer"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self._mlog("   🌐 http://127.0.0.1:9090")
        except Exception as e:
            self._mlog(f"   ❌ {e}")


# ═══════════════════════════════════════════════
# Rerun 后台流线程 — 完全隔离，不阻塞 GUI
# ═══════════════════════════════════════════════

class _RerunStreamWorker(QThread):
    """后台线程：初始化 Rerun + Web Viewer + 数据流推送"""
    log_msg = pyqtSignal(str)
    
    def __init__(self, replay=None, sim=None):
        super().__init__()
        self._replay = replay
        self._sim = sim
        self._running = True
    
    def stop(self):
        self._running = False
    
    def run(self):
        import rerun as rr
        from rerun import components as rrc
        import time
        
        try:
            self.log_msg.emit("📊 Rerun: 初始化...")
            rr.init("Z-MAX Monitor")
            
            # gRPC 服务
            grpc_url = rr.serve_grpc()
            self.log_msg.emit(f"   gRPC: {grpc_url}")
            
            # Web Viewer
            rr.serve_web_viewer(open_browser=False, connect_to=grpc_url)
            self.log_msg.emit("   🌐 http://127.0.0.1:9090")
            self.log_msg.emit("   ⏳ 等待浏览器连接 (3秒)...")
            time.sleep(3)  # 等浏览器连上
            
            # 开始推送数据
            if self._replay and self._replay.total_frames > 0:
                self._stream_replay(rr, rrc)
            elif self._sim:
                self._stream_sim(rr, rrc)
            else:
                # 无数据源，推一些演示数据
                self._stream_demo(rr, rrc)
                
        except Exception as e:
            self.log_msg.emit(f"❌ Rerun 错误: {e}")
    
    def _stream_replay(self, rr, rrc):
        frames = self._replay.total_frames
        self.log_msg.emit(f"   ▶ 推送回放数据: {frames} 帧")
        self._replay.current_frame = 0
        
        # 先画3D坐标系参考
        rr.log("world/xyz", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.3,0,0],[0,0.3,0],[0,0,0.3]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]
        ))
        rr.log("world/origin", rr.Points3D([[0,0,0]], radii=[0.02]))
        
        seq = 0
        while self._running and self._replay.current_frame < frames:
            frame = self._replay.get_frame()
            if not frame:
                break
            
            rr.set_time("stable_time", sequence=seq)
            
            joints = frame.get("joints", [])
            if len(joints) >= 6:
                # 6个关节做成明显的3D点 + 连线
                pts = [[i*0.2, joints[i]*0.8, 0] for i in range(6)]
                colors = [[255-i*30, 100+i*20, i*40] for i in range(6)]
                rr.log("robot/joints", rr.Points3D(pts, radii=[0.06]*6, colors=colors))
                # 连线
                for i in range(5):
                    rr.log(f"robot/link_{i}", rr.Arrows3D(
                        origins=[pts[i]], vectors=[[pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1], 0]],
                        radii=[0.01]
                    ))
                for i, v in enumerate(joints[:6]):
                    rr.log(f"joint/J{i+1}", rrc.Scalar(v))
            
            gripper = frame.get("gripper")
            if gripper is not None:
                rr.log("gripper", rrc.Scalar(gripper))
            
            self._replay.advance()
            seq += 1
            time.sleep(0.15)  # ~7fps, 让浏览器有时间渲染
        
        self.log_msg.emit("   ✅ 回放完成")
    
    def _stream_sim(self, rr, rrc):
        sim = self._sim
        if not sim.running:
            sim.start()
        self.log_msg.emit("   ▶ 推送仿真数据")
        
        seq = 0
        while self._running and sim.running:
            snap = sim.get_joint_snapshot()
            positions = [s["pos"] for s in snap.values()]
            
            rr.set_time("stable_time", sequence=seq)
            rr.log("joints/3d", rr.Points3D(
                [[i*0.15, positions[i]*0.3, 0] for i in range(min(6, len(positions)))],
                radii=[0.03]*min(6, len(positions))
            ))
            
            rr.log("force/fx", rrc.Scalar(sim.force.fx))
            rr.log("force/fz", rrc.Scalar(sim.force.fz))
            seq += 1
            time.sleep(0.1)
        
        sim.stop()
    
    def _stream_demo(self, rr, rrc):
        """演示数据 — 持续30秒的正弦波动画"""
        import math
        self.log_msg.emit("   ▶ 推送演示数据 (30秒正弦波)")
        
        # 坐标系
        rr.log("world/xyz", rr.Arrows3D(
            origins=[[0,0,0],[0,0,0],[0,0,0]],
            vectors=[[0.3,0,0],[0,0.3,0],[0,0,0.3]],
            colors=[[255,0,0],[0,255,0],[0,0,255]]
        ))
        rr.log("world/origin", rr.Points3D([[0,0,0]], radii=[0.02]))
        
        seq = 0
        start = time.time()
        while self._running and (time.time() - start) < 30:
            t = time.time() - start
            rr.set_time("stable_time", sequence=seq)
            
            # 6个正弦波关节
            pts = [[i*0.2, math.sin(t*2 + i)*0.5, math.cos(t*1.5 + i)*0.2] for i in range(6)]
            colors = [[255-i*30, 100+i*20, i*40] for i in range(6)]
            rr.log("robot/joints", rr.Points3D(pts, radii=[0.06]*6, colors=colors))
            
            # 连线
            for i in range(5):
                rr.log(f"robot/link_{i}", rr.Arrows3D(
                    origins=[pts[i]], 
                    vectors=[[pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1], pts[i+1][2]-pts[i][2]]],
                    radii=[0.01]
                ))
            
            for i in range(6):
                rr.log(f"joint/J{i+1}", rrc.Scalar(pts[i][1]))
            
            seq += 1
            time.sleep(0.1)
        
        self.log_msg.emit("   ✅ 演示完成")


# ═══════════════════════════════════════════════
# 插拔场景模块: Z700轮式双臂机器人 + ROI计算器
# ============================================================
ROI_ACCENT = C_CYAN  # ROI模块专用颜色


class InferencePanel(QWidget):
    """Z-MAX 推理服务面板 — Server/Client 控制 + 旁路验证预留"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        from inference_server import ZmaxInferenceServer
        from inference_client import ZmaxInferenceClient, DataSource
        
        self.server = ZmaxInferenceServer(log_callback=self._log_server)
        self.client = ZmaxInferenceClient(log_callback=self._log_client)
        
        self._init_ui()
    
    def _init_ui(self):
        main = QVBoxLayout()
        main.setSpacing(12)
        main.setContentsMargins(20, 16, 20, 16)
        
        # ── 标题 ──
        title = QLabel("🌐 推理服务")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet(f"color:{C_WHITE};")
        main.addWidget(title)
        
        hint = QLabel("本地Server + 本地Client  |  旁路验证预留(Client在Orin远端)")
        hint.setStyleSheet(f"color:{C_GRAY}; font-size:10px;")
        main.addWidget(hint)
        
        # ── Server + Client 双栏 ──
        panels = QHBoxLayout()
        panels.setSpacing(16)
        panels.addWidget(self._build_server_panel(), 1)
        panels.addWidget(self._build_client_panel(), 1)
        main.addLayout(panels)
        
        # ── 控制栏 ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)
        
        self.start_btn = QPushButton("▶ 完整启动")
        self.start_btn.clicked.connect(self._full_start)
        self.start_btn.setStyleSheet(f"background:{C_GREEN}; color:white; border:none; border-radius:6px; padding:10px 24px; font-size:13px; font-weight:bold;")
        ctrl.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹ 全部停止")
        self.stop_btn.clicked.connect(self._full_stop)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(f"background:{C_RED}; color:white; border:none; border-radius:6px; padding:10px 24px; font-size:13px; font-weight:bold;")
        ctrl.addWidget(self.stop_btn)
        
        ctrl.addStretch()
        main.addLayout(ctrl)
        
        # ── 日志 ──
        log_g = QGroupBox("推理日志")
        log_g.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:12px; padding-top:32px; margin-top:16px;}} QGroupBox::title{{left:12px; padding:0 8px; font-weight:bold;}}")
        ll = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(250)
        self.log_text.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:8px; font-family:Consolas; font-size:10px;")
        ll.addWidget(self.log_text)
        log_g.setLayout(ll)
        main.addWidget(log_g, 1)
        
        self.setLayout(main)
    
    def _build_server_panel(self):
        g = QGroupBox("🖥️ 推理服务端")
        g.setStyleSheet(f"QGroupBox{{color:{C_CYAN}; background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:12px; padding-top:32px; margin-top:16px;}} QGroupBox::title{{left:12px; padding:0 8px; font-weight:bold;}}")
        l = QFormLayout()
        l.setSpacing(8)
        
        # 模型路径
        row = QHBoxLayout()
        self.ckpt_edit = QLineEdit("outputs/smolvla_metaworld/checkpoints/000300/pretrained_model")
        self.ckpt_edit.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        browse_btn = QPushButton("📂")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._browse_checkpoint)
        browse_btn.setStyleSheet(f"background:{C_BORDER}; color:{C_WHITE}; border:none; border-radius:4px;")
        row.addWidget(self.ckpt_edit)
        row.addWidget(browse_btn)
        l.addRow("模型:", row)
        
        # 端口
        port_row = QHBoxLayout()
        self.host_edit = QLineEdit("0.0.0.0")
        self.host_edit.setFixedWidth(100)
        self.host_edit.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(50051)
        self.port_spin.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        port_row.addWidget(QLabel("Host:"))
        port_row.addWidget(self.host_edit)
        port_row.addWidget(QLabel("Port:"))
        port_row.addWidget(self.port_spin)
        port_row.addStretch()
        l.addRow("地址:", port_row)
        
        # 状态
        self.server_status = QLabel("⚪ 未启动")
        self.server_status.setStyleSheet(f"color:{C_GRAY}; font-weight:bold; padding:4px 8px; background:{C_BG}; border-radius:4px;")
        l.addRow("状态:", self.server_status)
        
        # 独立启停
        btns = QHBoxLayout()
        self.srv_start = QPushButton("启动")
        self.srv_start.clicked.connect(self._server_start)
        self.srv_start.setStyleSheet(f"background:{C_GREEN}88; color:white; border:none; border-radius:4px; padding:6px 16px;")
        self.srv_stop = QPushButton("停止")
        self.srv_stop.clicked.connect(self._server_stop)
        self.srv_stop.setEnabled(False)
        self.srv_stop.setStyleSheet(f"background:{C_RED}88; color:white; border:none; border-radius:4px; padding:6px 16px;")
        btns.addWidget(self.srv_start)
        btns.addWidget(self.srv_stop)
        btns.addStretch()
        l.addRow("操作:", btns)
        
        g.setLayout(l)
        return g
    
    def _build_client_panel(self):
        g = QGroupBox("📱 推理客户端")
        g.setStyleSheet(f"QGroupBox{{color:{C_GREEN}; background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:12px; padding-top:32px; margin-top:16px;}} QGroupBox::title{{left:12px; padding:0 8px; font-weight:bold;}}")
        l = QFormLayout()
        l.setSpacing(8)
        
        # 服务器地址
        self.srv_addr_edit = QLineEdit("127.0.0.1:50051")
        self.srv_addr_edit.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        l.addRow("服务器:", self.srv_addr_edit)
        
        # 数据源
        self.source_combo = QComboBox()
        self.source_combo.addItems(["Dummy随机数据", "PushT回放", "MetaWorld回放", "远端Orin(预留)"])
        self.source_combo.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px;")
        l.addRow("数据源:", self.source_combo)
        
        # 状态
        self.client_status = QLabel("⚪ 未连接")
        self.client_status.setStyleSheet(f"color:{C_GRAY}; font-weight:bold; padding:4px 8px; background:{C_BG}; border-radius:4px;")
        l.addRow("状态:", self.client_status)
        
        # 统计
        self.stats_label = QLabel("帧:0 动作:0")
        self.stats_label.setStyleSheet(f"color:{C_GRAY}; font-size:10px;")
        l.addRow("统计:", self.stats_label)
        
        # 独立操作
        btns = QHBoxLayout()
        self.cli_connect = QPushButton("连接")
        self.cli_connect.clicked.connect(self._client_connect)
        self.cli_connect.setStyleSheet(f"background:{C_BLUE}88; color:white; border:none; border-radius:4px; padding:6px 16px;")
        self.cli_stream = QPushButton("开始推流")
        self.cli_stream.clicked.connect(self._client_stream)
        self.cli_stream.setEnabled(False)
        self.cli_stream.setStyleSheet(f"background:{C_GREEN}88; color:white; border:none; border-radius:4px; padding:6px 16px;")
        self.cli_stop = QPushButton("停止")
        self.cli_stop.clicked.connect(self._client_stop)
        self.cli_stop.setEnabled(False)
        self.cli_stop.setStyleSheet(f"background:{C_RED}88; color:white; border:none; border-radius:4px; padding:6px 16px;")
        btns.addWidget(self.cli_connect)
        btns.addWidget(self.cli_stream)
        btns.addWidget(self.cli_stop)
        btns.addStretch()
        l.addRow("操作:", btns)
        
        g.setLayout(l)
        return g
    
    # ── 日志 ──
    def _log(self, prefix, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {prefix} {msg}")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
    
    def _log_server(self, msg): self._log("🖥️", msg)
    def _log_client(self, msg): self._log("📱", msg)
    
    # ── 操作 ──
    def _browse_checkpoint(self):
        from PyQt5.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "选择模型checkpoint", "outputs/")
        if path:
            self.ckpt_edit.setText(path)
    
    def _server_start(self):
        ckpt = self.ckpt_edit.text().strip()
        host = self.host_edit.text().strip()
        port = self.port_spin.value()
        if self.server.start_server(ckpt, host, port):
            self.server_status.setText("🟢 运行中")
            self.server_status.setStyleSheet(f"color:{C_GREEN}; font-weight:bold; padding:4px 8px; background:{C_GREEN}22; border-radius:4px;")
            self.srv_start.setEnabled(False)
            self.srv_stop.setEnabled(True)
            self.stop_btn.setEnabled(True)
    
    def _server_stop(self):
        self.server.stop_server()
        self.server_status.setText("⚪ 未启动")
        self.server_status.setStyleSheet(f"color:{C_GRAY}; font-weight:bold; padding:4px 8px; background:{C_BG}; border-radius:4px;")
        self.srv_start.setEnabled(True)
        self.srv_stop.setEnabled(False)
    
    def _client_connect(self):
        addr = self.srv_addr_edit.text().strip()
        if self.client.connect(addr):
            self.client_status.setText("🟢 已连接")
            self.client_status.setStyleSheet(f"color:{C_GREEN}; font-weight:bold; padding:4px 8px; background:{C_GREEN}22; border-radius:4px;")
            self.cli_connect.setEnabled(False)
            self.cli_stream.setEnabled(True)
            self.cli_stop.setEnabled(True)
            # 自动发送策略
            ckpt = self.ckpt_edit.text().strip()
            self.client.send_policy(ckpt)
            self._log_client(f"策略已发送")
    
    def _client_stream(self):
        src = self.source_combo.currentText()
        if "Dummy" in src:
            self.client.start_dummy_stream(fps=5, duration_sec=10)
        elif "PushT" in src:
            self.client.start_dataset_stream("lerobot/pusht", fps=5, n_frames=30)
        elif "MetaWorld" in src:
            self.client.start_dataset_stream("lerobot/metaworld_mt50", fps=5, n_frames=30)
        else:
            self._log_client("远端Orin模式预留")
            return
        
        self.cli_stream.setEnabled(False)
        # 定时更新统计
        from PyQt5.QtCore import QTimer
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(1000)
    
    def _client_stop(self):
        self.client.stop_stream()
        self.cli_stream.setEnabled(True)
        if hasattr(self, '_stats_timer'):
            self._stats_timer.stop()
    
    def _update_stats(self):
        s = self.client.get_status()
        self.stats_label.setText(f"帧:{s['frames_sent']} 动作:{s['actions']}")
    
    def _full_start(self):
        self._server_start()
        # 等待服务端就绪后自动连接
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(2000, self._client_connect)
        QTimer.singleShot(5000, self._client_stream)
    
    def _full_stop(self):
        self._client_stop()
        self.client.disconnect()
        self._server_stop()
        self.client_status.setText("⚪ 未连接")
        self.client_status.setStyleSheet(f"color:{C_GRAY}; font-weight:bold; padding:4px 8px; background:{C_BG}; border-radius:4px;")
        self.cli_connect.setEnabled(True)
        self.cli_stream.setEnabled(False)
        self.cli_stop.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)


# ============================================================
# 插拔场景模块: Z700 L2基线/L3增强/L4旗舰
# ============================================================
class PluggingSceneModule(SubModuleWidget):
    """Z700插拔场景 — L2基线/L3增强/L4旗舰 三级场景"""

    def __init__(self):
        super().__init__("插拔场景 · Z700", [("Z700", ROI_ACCENT), ("System 0", SYS0_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)
        
        # ── 等级选择Tab ──
        self.scene_tabs = QTabWidget()
        self.scene_tabs.setStyleSheet(f"""
            QTabWidget::pane{{background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:8px;}}
            QTabBar::tab{{background:{C_BG2}; color:{C_GRAY}; padding:8px 20px; font-size:12px; font-weight:bold; border:1px solid {C_BORDER}; border-bottom:none;}}
            QTabBar::tab:selected{{background:{C_CARD}; color:{C_WHITE}; border-bottom:2px solid {ROI_ACCENT};}}
        """)
        
        self.scene_tabs.addTab(self._build_l2_tab(), "🔧 L2 基线版 · 单工序插拔")
        self.scene_tabs.addTab(self._build_l3_tab(), "🤖 L3 增强版 · 多模块自主")
        self.scene_tabs.addTab(self._build_l4_tab(), "🛡️ L4 旗舰版 · 安全全自主")
        
        # Tab切换时更新积木面板高亮
        self.scene_tabs.currentChanged.connect(self._update_brick_highlight)
        
        bl.addWidget(self.scene_tabs)
        
        # ── 🧱 功能积木 · 阶梯进化图 ──
        self.brick_panel, self._brick_rows = self._build_brick_panel()
        bl.addWidget(self.brick_panel)
        
        body.setLayout(bl)
        self._build_shell(body)

    # ═══════ L2 基线版 · 单工序插拔 ═══════
    def _build_l2_tab(self):
        w = QWidget()
        l = QVBoxLayout(); l.setSpacing(10)
        
        # L2 产品迭代策略 — 增高+滚动
        hw = QGroupBox("🖥️ 产品迭代策略 · L2 基线版 — 人工编制流程，实现精细插拔操作")
        hw.setStyleSheet(f"QGroupBox{{color:{ROI_ACCENT}; font-weight:bold; {card_style(C_CARD, ROI_ACCENT, 8, 12)}}}")
        hw.setMinimumHeight(200)
        hl = QVBoxLayout()
        hw_info = QLabel(
            "<b>系统 0 · 分段式 · 标准原子功能库 · 动作(标准接口) · 真实环境</b><br><br>"
            "固定式精密操作具身机器人 · 精密制造智能技工<br><br>"
            "基于 Phase 0 交付物: SR5-C 6轴机械臂 · AGX Orin NX · 双3D相机 · DH夹爪 · TS-T-15触觉<br>"
            "双路急停 · 安全光栅 · 三色塔灯 · 力控闭环 1kHz"
        )
        hw_info.setFont(QFont("Arial", 12)); hw_info.setStyleSheet(f"color:{C_WHITE}; padding:12px;")
        hw_info.setWordWrap(True)
        hl.addWidget(hw_info)
        hw.setLayout(hl); l.addWidget(hw)
        
        # L2工作流程 — 6步对应产品发布PPT
        flow = QGroupBox("📋 L2 基线版 · 人工编制流程 — 6步分段式精细插拔")
        flow.setStyleSheet(f"QGroupBox{{color:{C_GREEN}; font-weight:bold; {card_style(C_CARD, C_GREEN, 8, 12)}}}")
        fl = QHBoxLayout(); fl.setSpacing(4)
        for num, title, desc, color in [
            ("1", "人工流程编排", "人工设定\n工序参数", ROI_ACCENT),
            ("2", "标准原子功能", "取料·扫码\n·定位·插入", C_GREEN),
            ("3", "动作执行", "标准接口\n精准到位", SYS11_COLOR),
            ("4", "力控反馈", "六维力传感器\n力控闭环", SYS12_COLOR),
            ("5", "AOI验证", "逐步确认\n异常停机", C_ORANGE),
            ("6", "成品下料", "取出完成品\n数据记录", SYS2_COLOR),
        ]:
            card = self._make_step_card(num, title, desc, color)
            fl.addWidget(card, 1)
            if num != "6":
                arr = QLabel("→"); arr.setStyleSheet(f"color:{C_DIM}; font-size:12px;"); arr.setFixedWidth(12)
                fl.addWidget(arr)
        flow.setLayout(fl); l.addWidget(flow)
        
        # 特性
        feat = QGroupBox("✅ L2 基线版 · 已实现特性")
        feat.setStyleSheet(f"QGroupBox{{color:{C_GREEN}; font-weight:bold; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        fe = QVBoxLayout()
        ft = QLabel(
            "◈ <b>人工流程编排</b>: 操作员在 XSpace Studio 中设定工序参数，选择标准原子功能<br>"
            "◈ <b>标准原子功能库</b>: 取料、扫码、定位、对准、插入、拔出、检测、分类<br>"
            "◈ <b>动作执行 (标准接口)</b>: 基于 ROS2 Service 接口，点到点精确运动 ±0.05mm<br>"
            "◈ <b>力控反馈</b>: 六维力传感器 1kHz 采样，夹持力自适应<br>"
            "◈ <b>分段式验证</b>: 每个步骤完成确认后才进入下一步 · 异常自动停机<br>"
            "◈ <b>真实环境运行</b>: 苏州实验室 Phase 0 验收通过 · 关键工序良率 ≥99.2%"
        )
        ft.setFont(QFont("Arial", 10)); ft.setStyleSheet(f"color:{C_WHITE}; padding:6px;"); ft.setWordWrap(True)
        fe.addWidget(ft); feat.setLayout(fe); l.addWidget(feat)
        
        w.setLayout(l)
        
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(w)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        outer = QWidget(); ol = QVBoxLayout(); ol.addWidget(scroll); outer.setLayout(ol)
        return outer
    
    # ═══════ L3 增强版 · 多模块自主 ═══════
    def _build_l3_tab(self):
        w = QWidget()
        l = QVBoxLayout(); l.setSpacing(10)
        
        hw = QGroupBox("🤖 L3 增强版 · 多模块自主闭环")
        hw.setStyleSheet(f"QGroupBox{{color:{SYS11_COLOR}; font-weight:bold; padding-top:28px; {card_style(C_CARD, SYS11_COLOR, 8, 12)}}}")
        hl = QVBoxLayout(); hl.setContentsMargins(8,0,8,8)
        info = QLabel(
            "<b>在 L2 硬件基础上，通过 OTA 软件升级实现:</b><br><br>"
            "◈ <b>多模块自主识别</b>: 视觉识别400G/100G/不同封装 · 自动切换夹爪工装<br>"
            "◈ <b>自主闭环工作</b>: 全程无人干预 · 自动上下料+取放+插拔+测试+分类<br>"
            "◈ <b>换线自主换配方</b>: 扫码识别模块SN → 自动加载对应工序配方<br>"
            "◈ <b>异常自恢复</b>: 卡料/偏移/测试失败 → 自动诊断+重试+分类<br>"
            "◈ <b>全工序良率 ≥99.5%</b>"
        )
        info.setFont(QFont("Arial", 11)); info.setStyleSheet(f"color:{C_WHITE}; padding:0 12px 12px 12px;"); info.setWordWrap(True)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(info)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        hl.addWidget(scroll); hw.setLayout(hl); l.addWidget(hw)
        
        # L3 流程 8步
        flow = QGroupBox("L3 增强版 · 8步全自动流程")
        flow.setStyleSheet(f"QGroupBox{{color:{SYS11_COLOR}; font-weight:bold; {card_style(C_CARD, SYS11_COLOR, 8, 12)}}}")
        fl = QHBoxLayout(); fl.setSpacing(4)
        for num, title, desc, color in [
            ("1", "视觉取料", "3D定位\n无序抓取", ROI_ACCENT),
            ("2", "自动扫码", "模块SN\n配方匹配", C_GRAY),
            ("3", "中转定位", "标准姿态\n二次校准", C_GRAY),
            ("4", "力控插拔", "对准插入\n力控闭环", SYS11_COLOR),
            ("5", "并行测试", "双工位\n并行执行", C_ORANGE),
            ("6", "AOI检测", "拔出\n视觉检查", SYS12_COLOR),
            ("7", "P/F分类", "根据结果\n自动分类", SYS2_COLOR),
            ("8", "连续循环", "自动上料\n无人值守", C_GREEN),
        ]:
            card = self._make_step_card(num, title, desc, color)
            fl.addWidget(card, 1)
            if num != "8":
                arr = QLabel("→"); arr.setStyleSheet(f"color:{C_DIM}; font-size:12px;"); arr.setFixedWidth(12)
                fl.addWidget(arr)
        flow.setLayout(fl); l.addWidget(flow)
        
        w.setLayout(l)
        
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(w)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        outer = QWidget(); ol = QVBoxLayout(); ol.addWidget(scroll); outer.setLayout(ol)
        return outer
    
    # ═══════ L4 旗舰版 · 安全全自主 ═══════
    def _build_l4_tab(self):
        w = QWidget()
        l = QVBoxLayout(); l.setSpacing(10)
        
        hw = QGroupBox("🛡️ L4 旗舰版 · AI全自主 + 安全主动保护")
        hw.setStyleSheet(f"QGroupBox{{color:{C_RED}; font-weight:bold; {card_style(C_CARD, C_RED, 8, 12)}}}")
        hw.setMinimumHeight(350)
        hl = QVBoxLayout(); hl.setContentsMargins(0,0,0,0)
        info = QLabel(
            "<b>在 L3 基础上，增加 VLA 智能决策 + 主动安全:</b><br><br>"
            "◈ <b>VLA 视觉语言动作模型</b>: 新模块从未见过 → AI自动适配 · 零编程<br>"
            "◈ <b>主动安全保护</b>: 力传感器超阈值预判 · 碰撞前0.05s自动停机<br>"
            "◈ <b>触觉闭环</b>: TS-T-15实时接触力反馈 · 插入力超2N自动松夹<br>"
            "◈ <b>光幕联动</b>: 人员靠近→自动降速 · 进入危险区→立即停止<br>"
            "◈ <b>自诊断系统</b>: 预测性维护 · 部件寿命预估 · 故障前预警<br>"
            "◈ <b>7×24 无人值守</b> · 零人工干预 · <b>良率 ≥99.9%</b>"
        )
        info.setFont(QFont("Arial", 11)); info.setStyleSheet(f"color:{C_WHITE}; padding:12px;"); info.setWordWrap(True)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(info)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        hl.addWidget(scroll); hw.setLayout(hl); l.addWidget(hw)
        
        # 安全层级
        safe = QGroupBox("🛡️ 安全架构 · 五层主动保护")
        safe.setStyleSheet(f"QGroupBox{{color:{C_RED}; font-weight:bold; {card_style(C_CARD, C_RED, 8, 12)}}}")
        sl = QVBoxLayout()
        for level, name, desc, color in [
            ("L1", "力控预判",      "力传感器1kHz采样 → 接触力超阈值0.05s内停机", SYS11_COLOR),
            ("L2", "触觉闭环",      "TS-T-15实时反馈 → 夹持力>2N自动释放", C_GREEN),
            ("L3", "光幕联动",      "安全光栅检测人员 → 自动降速/分区停机", C_ORANGE),
            ("L4", "自诊断预警",    "电机温度/电流/振动异常 → 提前48h通知维护", ROI_ACCENT),
            ("L5", "AI行为预测",    "LeWorldModel预测未来0.2s状态 → 主动避让", SYS12_COLOR),
        ]:
            row = QHBoxLayout()
            badge = QLabel(level); badge.setFixedSize(30,30)
            badge.setStyleSheet(f"background:{color}; color:white; border-radius:15px; font-weight:bold; font-size:10px;")
            badge.setAlignment(Qt.AlignCenter)
            row.addWidget(badge)
            nl = QLabel(f"<b>{name}</b>")
            nl.setStyleSheet(f"color:{color}; font-size:11px;"); nl.setFixedWidth(100)
            row.addWidget(nl)
            nd = QLabel(desc); nd.setStyleSheet(f"color:{C_GRAY}; font-size:10px;"); nd.setWordWrap(True)
            row.addWidget(nd, 1)
            sl.addLayout(row)
        safe.setLayout(sl); l.addWidget(safe)
        
        w.setLayout(l)
        
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(w)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        outer = QWidget(); ol = QVBoxLayout(); ol.addWidget(scroll); outer.setLayout(ol)
        return outer
    
    def _make_step_card(self, num, title, desc, color):
        card = QFrame()
        card.setStyleSheet(f"background:{C_BG2}; border:1px solid {color}88; border-radius:6px;")
        cl = QVBoxLayout(); cl.setSpacing(2); cl.setContentsMargins(6, 4, 6, 4)
        num_lbl = QLabel(num); num_lbl.setFont(QFont("Consolas", 10, QFont.Bold))
        num_lbl.setStyleSheet(f"color:{color}; background:{color}22; border-radius:3px; padding:1px 4px;")
        num_lbl.setAlignment(Qt.AlignCenter); cl.addWidget(num_lbl)
        title_lbl = QLabel(title); title_lbl.setFont(QFont("Arial", 8, QFont.Bold))
        title_lbl.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        title_lbl.setAlignment(Qt.AlignCenter); cl.addWidget(title_lbl)
        desc_lbl = QLabel(desc); desc_lbl.setFont(QFont("Arial", 7))
        desc_lbl.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        desc_lbl.setAlignment(Qt.AlignCenter); desc_lbl.setWordWrap(True); cl.addWidget(desc_lbl)
        card.setLayout(cl); return card
    
    # ═══════ 🧱 功能积木 · 阶梯进化 ═══════
    def _build_brick_panel(self):
        """乐高积木风格: L2基础 → L3增强 → L4旗舰 功能阶梯"""
        panel = QGroupBox("🧱 功能积木 · 阶梯进化")
        panel.setStyleSheet(f"QGroupBox{{color:{ROI_ACCENT}; font-weight:bold; {card_style(C_CARD, ROI_ACCENT, 8, 12)}}}")
        
        # 内层内容
        inner = QWidget()
        outer = QHBoxLayout(); outer.setSpacing(60)
        
        # 功能模块定义: (名称, L2状态, L3状态, L4状态, 固定颜色)
        # 状态: 'active'=实色 'new'=新增虚线 'keep'=保留暗色
        # 同一功能在三列中用相同颜色
        modules = [
            ("人工流程编排",  'active','keep','keep', ROI_ACCENT),
            ("标准原子功能库", 'active','keep','keep', C_GREEN),
            ("动作执行(ROS2)", 'active','keep','keep', SYS11_COLOR),
            ("力控反馈闭环",   'active','keep','keep', SYS12_COLOR),
            ("AOI验证检测",    'active','keep','keep', C_ORANGE),
            ("成品下料分类",   'active','keep','keep', SYS2_COLOR),
            (None, None, None, None, None),  # 分隔
            ("多模块自主识别",  None,  'new',  'keep', C_GREEN),
            ("自主闭环工作",    None,  'new',  'keep', SYS11_COLOR),
            ("换线自主换配方",  None,  'new',  'keep', C_ORANGE),
            ("异常诊断自恢复",  None,  'new',  'keep', SYS12_COLOR),
            (None, None, None, None, None),  # 分隔
            ("力控预判保护",    None,  None,   'new', C_RED),
            ("触觉闭环反馈",    None,  None,   'new', C_RED),
            ("光幕联动安全",    None,  None,   'new', C_RED),
            ("自诊断预警维护",  None,  None,   'new', C_RED),
            ("AI行为预测避让",  None,  None,   'new', C_RED),
        ]
        
        levels = [
            ("🔧 L2 基线版", "≥99.2%", C_GREEN),
            ("🤖 L3 增强版", "≥99.5%", SYS11_COLOR),
            ("🛡️ L4 旗舰版", "≥99.9%", C_RED),
        ]
        
        brick_rows = []  # [(col, row_idx, brick_widget, state)]
        
        for col_idx, (lvl_name, lvl_yield, lvl_color) in enumerate(levels):
            col = QVBoxLayout(); col.setSpacing(15)
            
            # 列标题
            hdr = QFrame()
            hdr.setStyleSheet(f"background:{lvl_color}22; border:2px solid {lvl_color}; border-radius:8px;")
            hdr.setFixedHeight(70)
            hl = QVBoxLayout(); hl.setContentsMargins(4,2,4,2); hl.setSpacing(0)
            t1 = QLabel(lvl_name); t1.setFont(QFont("Arial", 10, QFont.Bold))
            t1.setStyleSheet(f"color:{lvl_color};"); t1.setAlignment(Qt.AlignCenter)
            t2 = QLabel(lvl_yield); t2.setFont(QFont("Arial", 8))
            t2.setStyleSheet(f"color:white;"); t2.setAlignment(Qt.AlignCenter)
            hl.addWidget(t1); hl.addWidget(t2)
            hdr.setLayout(hl); col.addWidget(hdr)
            
            row_idx = 0
            for name, l2, l3, l4, mod_color in modules:
                if name is None:  # 分隔线
                    sep = QFrame()
                    sep.setFrameShape(QFrame.HLine)
                    sep.setStyleSheet(f"color:{C_BORDER};")
                    sep.setFixedHeight(6)
                    col.addWidget(sep)
                    row_idx += 1
                    continue
                
                status = [l2, l3, l4][col_idx]
                if status is None:
                    col.addSpacing(24)  # 占位
                    row_idx += 1
                    continue
                
                brick = QFrame()
                brick.setFixedHeight(48)
                
                if status == 'active':
                    brick.setStyleSheet(f"background:{mod_color}; border:3px solid {mod_color}; border-radius:6px; margin:3px 0;")
                    txt = QLabel(f"● {name}")
                    txt.setStyleSheet("color:white; font-size:11px; font-weight:bold;")
                    state = 'active'
                elif status == 'new':
                    brick.setStyleSheet(f"background:{mod_color}33; border:2px dashed {mod_color}; border-radius:6px; margin:2px 0;")
                    txt = QLabel(f"✦ {name}")
                    txt.setStyleSheet(f"color:{mod_color}; font-size:11px; font-weight:bold;")
                    state = 'new'
                else:  # keep — 完全无填充，仅文字占位
                    brick.setStyleSheet(f"background:transparent; border:1px solid transparent; border-radius:6px; margin:2px 0;")
                    txt = QLabel(f"  {name}")
                    txt.setStyleSheet(f"color:{mod_color}55; font-size:9px;")
                    state = 'keep'
                
                txt.setAlignment(Qt.AlignCenter)
                bl = QVBoxLayout(); bl.setContentsMargins(3,1,3,1); bl.addWidget(txt)
                brick.setLayout(bl)
                col.addWidget(brick)
                brick_rows.append((col_idx, row_idx, brick, state, mod_color))
                row_idx += 1
            
            col.addStretch()
            outer.addLayout(col, 1)
        
        inner.setLayout(outer)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumHeight(400)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;} QScrollBar:vertical{width:10px;}")
        
        outer_wrap = QVBoxLayout()
        outer_wrap.addWidget(scroll)
        panel.setLayout(outer_wrap)
        return panel, brick_rows
    
    def _update_brick_highlight(self, tab_idx):
        """Tab切换时高亮对应列"""
        if not hasattr(self, '_brick_rows'):
            return
        for col_idx, row_idx, brick, state, mod_color in self._brick_rows:
            if col_idx == tab_idx and state == 'keep':
                brick.setStyleSheet(f"background:{mod_color}18; border:2px solid {mod_color}88; border-radius:5px;")
                txt = brick.findChild(QLabel)
                if txt: txt.setStyleSheet(f"color:{mod_color}; font-size:10px; font-weight:bold;")
            elif state == 'keep':
                brick.setStyleSheet(f"background:transparent; border:1px solid transparent; border-radius:5px;")
                txt = brick.findChild(QLabel)
                if txt: txt.setStyleSheet(f"color:{mod_color}44; font-size:8px;")

    def _spin_style(self):
        return ""  # 已移除ROI计算器
    
    def _make_input_group(self, label_text, widget):
        return QLabel(label_text)  # 已移除ROI
    
    def _calc_roi(self):
        pass  # 已移除ROI计算器


# ============================================================
# 主窗口: 侧边栏 + 堆叠页面
# ============================================================
class StudioMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XSpace Studio — Z-MAX 多模态动作专家")  # 改名：LeRobot Studio → XSpace Studio
        self.setMinimumSize(1280, 820)
        self.resize(1400, 900)
        self._build()

    def _build(self):
        central = QWidget()
        central.setStyleSheet(f"background:{C_BG};")
        self.setCentralWidget(central)

        # ====== 菜单栏 (专业开发环境) ======
        self._build_menubar()

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 侧边栏 (可隐藏)
        self.sidebar = SystemSidebar()
        self.sidebar.layer_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        # 页面堆叠
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{C_BG};")

        # Page 0: 首页
        self.home = HomeWidget()
        self.home.module_clicked.connect(self._on_nav)
        self.stack.addWidget(self.home)

        # Page 1-6: 子模块
        self.modules = {
            "home":       0,
            "dataset":    1,
            "training":   2,
            "evaluation": 3,
            "hardware":   4,
            "config":     5,
            "monitor":    6,
            "plugging":   7,
            "version":    8,
            "inference":  9,
        }

        self.stack.addWidget(DatasetModule())
        self.stack.addWidget(TrainingModule())
        self.stack.addWidget(EvalModule())
        self.stack.addWidget(HardwareModule())
        self.stack.addWidget(ConfigModule())
        self.stack.addWidget(MonitorModule())
        self.stack.addWidget(PluggingSceneModule())

        # Version Sync Module (需要 repo path)
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.stack.addWidget(VersionSyncWidget(repo_path))

        # 推理服务面板
        self.stack.addWidget(InferencePanel())

        root.addWidget(self.stack, 1)
        central.setLayout(root)

        # 系统层级点击映射
        self.layer_map = {
            "sys0":  "hardware",
            "sys11": "training",
            "sys12": "evaluation",
            "sys2":  "dataset",
        }

        # 状态栏
        sb = self.statusBar()
        sb.setStyleSheet(f"background:{C_BG2}; color:{C_GRAY}; border-top:1px solid {C_BORDER};")
        sb.showMessage("● Ready  |  Python 3.12 · PyTorch  |  lerobot v0.5.2  |  smolvla_lew")

    def _on_nav(self, target):
        """导航切换"""
        # 系统层级映射
        if target in self.layer_map:
            target = self.layer_map[target]

        idx = self.modules.get(target, 0)
        self.stack.setCurrentIndex(idx)

        # 更新状态栏
        names = ["首页", "数据集", "训练", "评估", "硬件", "配置", "监控", "插拔场景", "版本同步", "推理服务"]
        self.statusBar().showMessage(f"● {names[idx]}  |  Z-MAX 三层解耦架构  |  Sys-0 + Sys-11 + Sys-12 + Sys-2")

    def _build_menubar(self):
        """构建专业开发环境菜单栏"""
        self.repo_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.docs_path = os.path.join(self.repo_path, "docs")

        mb = self.menuBar()
        mb.setStyleSheet(f"""
            QMenuBar {{
                background: {C_BG2};
                color: {C_WHITE};
                border-bottom: 1px solid {C_BORDER};
                padding: 2px 0;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 6px 12px;
                margin: 0;
            }}
            QMenuBar::item:selected {{
                background: {C_CARD};
                color: {C_BLUE};
            }}
            QMenu {{
                background: {C_CARD};
                color: {C_WHITE};
                border: 1px solid {C_BORDER};
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 30px 6px 15px;
            }}
            QMenu::item:selected {{
                background: {C_BLUE}33;
                color: {C_BLUE};
            }}
            QMenu::separator {{
                height: 1px;
                background: {C_BORDER};
                margin: 4px 12px;
            }}
        """)

        # ====== 文件菜单 ======
        m_file = mb.addMenu("文件(&F)")

        act_open_repo = QAction("打开项目根目录", self)
        act_open_repo.setShortcut("Ctrl+O")
        act_open_repo.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.repo_path)))
        m_file.addAction(act_open_repo)

        m_file.addSeparator()

        act_github = QAction("浏览 GitHub 仓库", self)
        act_github.setShortcut("Ctrl+G")
        act_github.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/MikeBMW/lerobot-smolvla-lew")))
        m_file.addAction(act_github)

        act_push = QAction("同步代码到 GitHub", self)
        act_push.setShortcut("Ctrl+Shift+U")
        act_push.triggered.connect(self._menu_sync_to_github)
        m_file.addAction(act_push)

        m_file.addSeparator()

        act_exit = QAction("退出(&Q)", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        # ====== 视图菜单 ======
        m_view = mb.addMenu("视图(&V)")

        view_targets = [
            ("返回首页", "home"),
            ("数据集管理", "dataset"),
            ("训练控制台", "training"),
            ("评估分析", "evaluation"),
            ("硬件工具箱", "hardware"),
            ("配置中心", "config"),
            ("实时监控", "monitor"),
            ("插拔场景", "plugging"),
            ("版本同步", "version"),
        ]
        for label, target in view_targets:
            act = QAction(label, self)
            act.triggered.connect(self._mk_nav_func(target))
            m_view.addAction(act)

        # ====== 文档菜单（帮助文档） ======
        m_doc = mb.addMenu("帮助文档(&H)")

        # === Git 操作指南 + README（置顶） ===
        m_git = m_doc.addMenu("🔄 Git 推送与拉取指南")
        m_git.addAction(self._mk_doc_action("📖 完整操作指南 (README.md) — 含 git push/pull/clone",
            (["README.md"], "xdg-open")))
        m_git.addSeparator()
        
        # 培训文档 (唯一 MD + PPTX)
        m_doc.addAction(self._mk_doc_action("📖 Z700 F · L2 产品培训手册 (MD)",
            (["Z700F-L2产品培训手册.md"], "xdg-open")))
        m_doc.addAction(self._mk_doc_action("📊 Z700 F · L2 产品培训 (PPTX·PowerPoint)",
            (["Z700F-L2产品培训手册.pptx"], "libreoffice")))
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("🎯 产品等级定义 · L1~L5 自动化标准",
            (["Z-MAX产品等级定义-L1-L5标准.md"], "xdg-open")))
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("🧠 SmolVLA 训练方案 · 数据+方法+路线",
            (["Z-MAX-SmolVLA训练方案.md"], "xdg-open")))
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("📋 用户需求调研问卷 (Word·docx)",
            (["survey/Z-MAX-用户需求调研问卷-v1.0.4.docx"], "libreoffice")))
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("📜 专利交底书 (Word·docx)",
            (["patents/Z-MAX-专利交底书-实用新型-多模态VLA具身机器人精细操作控制系统.docx"], "libreoffice")))
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("💾 数据日志方案 · MCAP vs Rosbag 分析",
            (["Z-MAX数据日志方案-MCAP分析.md"], "xdg-open")))
        m_doc.addSeparator()
        # 在子菜单里添加常用 Git 命令的快捷说明
        act_clone = QAction("📥 克隆项目: git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git", self)
        act_clone.triggered.connect(lambda: self._copy_git_cmd("git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git"))
        m_git.addAction(act_clone)
        act_pull = QAction("📥 拉取更新: git pull origin main", self)
        act_pull.triggered.connect(lambda: self._copy_git_cmd("git pull origin main"))
        m_git.addAction(act_pull)
        act_push = QAction("📤 推送代码: git add -A && git commit -m 'msg' && git push origin main", self)
        act_push.triggered.connect(lambda: self._copy_git_cmd("git add -A && git commit -m 'msg' && git push origin main"))
        m_git.addAction(act_push)
        act_status = QAction("🔍 查看状态: git status", self)
        act_status.triggered.connect(lambda: self._copy_git_cmd("git status"))
        m_git.addAction(act_status)
        act_log = QAction("📜 查看历史: git log --oneline -10", self)
        act_log.triggered.connect(lambda: self._copy_git_cmd("git log --oneline -10"))
        m_git.addAction(act_log)
        act_diff = QAction("🔀 查看差异: git diff --cached", self)
        act_diff.triggered.connect(lambda: self._copy_git_cmd("git diff --cached"))
        m_git.addAction(act_diff)

        m_doc.addSeparator()

        # L1 - 战略层
        m_l1 = m_doc.addMenu("L1 · 战略层文档")
        m_l1.addAction(self._mk_doc_action("📊 Z-MAX 产品发布 PPT (v1.0.4)",
            (["L1-Z-MAX产品发布-v1.0.0.pptx"], "libreoffice")))

        # L2 - 方案层
        m_doc.addSeparator()
        m_l2 = m_doc.addMenu("L2 · 方案层文档")
        m_l2.addAction(self._mk_doc_action("📋 解决方案 MD (v1.0.4)",
            (["L2-Z-MAX解决方案-v1.0.4.md"], "xdg-open")))

        # L3 - 技术层
        m_l3 = m_doc.addMenu("L3 · 技术层文档")
        m_l3.addAction(self._mk_doc_action("🔧 技术路线与代码开发指南 (v1.0.4)",
            (["L3-技术路线与开发指南-v1.0.4.md", "Z-MAX 产品迭代技术路线与代码开发指南.md"], "xdg-open")))

        # === 开发宝典（置顶核心文档） ===
        m_doc.addSeparator()
        m_doc.addAction(self._mk_doc_action("📖 开发宝典 — 全维度参考手册 (v1.0.4)",
            (["HELP-DEVELOPMENT-BIBLE.md"], "xdg-open")))

        # === 运维文档 ===
        m_doc.addSeparator()
        m_ops = m_doc.addMenu("🔧 运维手册")
        m_ops.addAction(self._mk_doc_action("🖥  Orin SSH 运维手册 — 连接/三层永固/故障排除",
            (["Orin运维手册.md"], "xdg-open")))

        # 品牌 & 竞品
        m_doc.addSeparator()
        m_brand = m_doc.addMenu("品牌 · 竞品参考")
        m_brand.addAction(self._mk_doc_action("🏷  品牌注册材料 PPT",
            (["BRAND-品牌注册材料.pptx", "Z-MAX产品注册汇报.pptx"], "libreoffice")))
        m_brand.addAction(self._mk_doc_action("📄 竞品参考 - 轮式双臂机器人项目 (PDF)",
            (["轮式双臂机器人光模块自主插拔项目-20260702.pdf"], "xdg-open")))

        # 版本管理
        m_doc.addSeparator()
        m_admin = m_doc.addMenu("版本管理文档")
        m_admin.addAction(self._mk_doc_action("📦 版本管理规范 VERSION.md",
            (["VERSION.md"], "xdg-open")))
        m_admin.addAction(self._mk_doc_action("🔄 上游同步指南",
            (["Z-MAX-UPSTREAM-SYNC.md"], "xdg-open")))

        # ====== 帮助菜单 ======
        m_help = mb.addMenu("关于(&A)")
        act_about = QAction("关于 Z-MAX", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

        act_lerobot = QAction("LeRobot 官方文档", self)
        act_lerobot.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://huggingface.co/docs/lerobot")))
        m_help.addAction(act_lerobot)
        
        # ── 右上角状态灯 (单灯指示) ──
        status_widget = QWidget()
        status_widget.setStyleSheet("background:transparent;")
        sl = QHBoxLayout()
        sl.setContentsMargins(4, 2, 8, 2)
        sl.setSpacing(4)
        
        self._status_lights = {}
        for color_on, name, tooltip in [
            ("#3fb950", "green",  "Hermes Agent 在线 · 守护进程运行中"),
            ("#d29922", "yellow", "需要紧急处理"),
            ("#f85149", "red",    "Agent 不在线或异常"),
        ]:
            dot = QLabel()
            dot.setFixedSize(14, 14)
            dot.setToolTip(tooltip)
            # 默认: 绿灯实心, 其他空心带边线
            if name == "green":
                dot.setStyleSheet(f"background:{color_on}; border:2px solid {color_on}; border-radius:7px;")
            else:
                dot.setStyleSheet(f"background:transparent; border:2px solid {color_on}; border-radius:7px;")
            sl.addWidget(dot)
            self._status_lights[name] = dot
        
        status_widget.setLayout(sl)
        mb.setCornerWidget(status_widget, Qt.TopRightCorner)

    def _mk_nav_func(self, target):
        """创建导航闭包函数"""
        def nav():
            self._on_nav(target)
        return nav

    def _mk_doc_action(self, label, paths_and_opener):
        """创建文档打开动作（支持多路径回退）"""
        paths, opener = paths_and_opener
        if not isinstance(paths, list):
            paths = [paths]

        def open_doc():
            for rel_path in paths:
                full_path = os.path.join(self.docs_path, rel_path)
                if os.path.exists(full_path):
                    try:
                        if opener == "libreoffice":
                            # WSL: 复制到 Windows 临时目录 → PowerPoint 打开
                            import shutil
                            tmp_name = f"zmax_doc_{os.path.basename(full_path)}"
                            tmp_dir = "/mnt/c/Users/Admin/AppData/Local/Temp"
                            os.makedirs(tmp_dir, exist_ok=True)
                            tmp_path = os.path.join(tmp_dir, tmp_name)
                            shutil.copy2(full_path, tmp_path)
                            win_path = tmp_path.replace("/mnt/c", "C:").replace("/", "\\")
                            # .pptx 用 PowerPoint，其他用默认程序
                            if full_path.endswith(".pptx"):
                                subprocess.Popen(["cmd.exe", "/c", "start", "powerpnt", win_path])
                            else:
                                subprocess.Popen(["explorer.exe", win_path])
                        elif opener == "xdg-open":
                            # WSL: 复制到 Windows 临时目录再打开
                            import shutil
                            ext = os.path.splitext(full_path)[1]
                            tmp_name = f"zmax_doc_{os.path.basename(full_path)}"
                            tmp_dir = "/mnt/c/Users/Admin/AppData/Local/Temp"
                            os.makedirs(tmp_dir, exist_ok=True)
                            tmp_path = os.path.join(tmp_dir, tmp_name)
                            shutil.copy2(full_path, tmp_path)
                            win_path = tmp_path.replace("/mnt/c", "C:").replace("/", "\\")
                            subprocess.Popen(["explorer.exe", win_path])
                        else:
                            subprocess.Popen([opener, full_path])
                        self.statusBar().showMessage(f"已打开: {rel_path}")
                        return
                    except Exception as e:
                        QMessageBox.warning(self, "打开失败", f"无法打开文档:\n{e}")
                        return
            QMessageBox.information(self, "文档未找到",
                f"以下文档均不存在:\n" +
                "\n".join([os.path.join(self.docs_path, p) for p in paths]))

        act = QAction(label, self)
        act.triggered.connect(open_doc)
        return act

    def _copy_git_cmd(self, cmd):
        """将 Git 命令复制到剪贴板并提示用户"""
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(cmd)
            QMessageBox.information(self, "Git 命令已复制",
                f"以下命令已复制到剪贴板：\n\n"
                f"<code>{cmd}</code>\n\n"
                f"粘贴到终端即可执行。\n\n"
                f"完整文档请打开：\n  帮助文档 → Git 推送与拉取指南 → 📖 完整操作指南 (README.md)")
        except Exception as e:
            QMessageBox.warning(self, "复制失败", f"无法复制命令: {e}\n\n{cmd}")

    def _menu_sync_to_github(self):
        """菜单调用的 GitHub 同步（委托给 HomeWidget）"""
        if hasattr(self, 'home'):
            self.home._sync_to_github()

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于 Z-MAX",
            f"""
<b>Z-MAX v1.0.1</b> · 多模态动作专家<br>
<b>Z700 轮式双臂精细操作机器人</b><br>
<br>
<b>核心能力</b><br>
• VTLA 多模态模型 (视觉 + 触觉 + 语言 + 动作)<br>
• 插拔精度: ±0.02mm<br>
• 关键工序良率: 99%+<br>
• 力控带宽: 1kHz<br>
• 双臂协同: 左取料-右插拔<br>
• ROI 回收期: 14~22 个月<br>
<br>
<b>技术路线</b><br>
Phase 0 (L2) → Phase 1 (L3) → Phase 2 (L3+) → Phase 3 (L4) → Phase 4 (L4+)<br>
VLM 规划 + VLA 执行 + HIL 强化学习<br>
<br>
<b>版本</b><br>
LeRobot: v0.5.2 · Z-MAX: zmax-1.0.1<br>
<br>
<b>智蜂创元 · 具身智能</b><br>
github.com/MikeBMW/lerobot-smolvla-lew
""")


# ============================================================
# 入口
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))

    # 全局滚动条样式 + ToolTip样式 + 对话框暗色主题
    app.setStyleSheet(f"""
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: #484f58; border-radius: 4px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
        QToolTip {{ background: {C_BG2}; color: {C_WHITE}; border: 1px solid {C_BORDER}; padding: 4px 8px; }}
        QToolTip:hover {{ background: {C_BG2}; }}

        /* 所有对话框统一暗色主题 */
        QMessageBox, QDialog, QInputDialog {{ 
            background: {C_BG}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER}; 
        }}
        QMessageBox QLabel, QDialog QLabel, QInputDialog QLabel {{ 
            color: {C_WHITE}; 
            background: transparent;
        }}
        QMessageBox QTextEdit {{ 
            background: {C_BG2}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER}; 
            border-radius: 4px; 
            padding: 8px;
        }}
        QInputDialog QLineEdit {{ 
            background: {C_BG2}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER}; 
            border-radius: 4px; 
            padding: 4px 8px;
        }}
        QInputDialog QSpinBox, QInputDialog QDoubleSpinBox, QInputDialog QComboBox {{ 
            background: {C_BG2}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER}; 
            border-radius: 4px; 
            padding: 4px 8px;
        }}
        QMessageBox QPushButton, QDialog QPushButton {{ 
            background: {C_CARD}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER}; 
            border-radius: 4px; 
            padding: 6px 16px;
            min-width: 60px;
        }}
        QMessageBox QPushButton:hover, QDialog QPushButton:hover {{ 
            background: {C_BLUE}33; 
            border-color: {C_BLUE};
        }}
        QMessageBox QPushButton:pressed, QDialog QPushButton:pressed {{ 
            background: {C_BLUE}55; 
        }}

        /* 右键菜单 (QMenu) 统一暗色主题 */
        QMenu {{ 
            background: {C_BG}; 
            color: {C_WHITE}; 
            border: 1px solid {C_BORDER};
        }}
        QMenu::item {{ 
            color: {C_WHITE};
            background: transparent;
            padding: 4px 12px;
        }}
        QMenu::item:selected {{ 
            background: {C_BLUE}44; 
            color: {C_WHITE};
        }}
        QMenu::separator {{ 
            height: 1px;
            background: {C_BORDER};
            margin: 4px 8px;
        }}

        /* QComboBox下拉列表样式 - 简单干净 */
        QComboBox QAbstractItemView {{
            background: {C_BG};
            color: {C_WHITE};
            border: 1px solid {C_BORDER};
            outline: none;
        }}
    """)

    win = StudioMainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
