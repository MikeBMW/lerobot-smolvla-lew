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
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout, QSizePolicy,
    QGraphicsDropShadowEffect, QScrollArea, QStackedWidget,
    QSplitter, QTextEdit, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QProgressBar,
    QTabWidget, QAction, QMenu, QInputDialog, QMessageBox,  # 新增 QInputDialog, QMessageBox
    QRadioButton, QButtonGroup  # 新增：配置中心架构模式选择
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QTimer, QUrl, QDateTime  # 新增 QDateTime 用于时间戳
from PyQt5.QtGui import (
    QFont, QColor, QPainter, QLinearGradient, QBrush,
    QPainterPath, QPen, QDesktopServices, QPixmap  # 新增 QDesktopServices, QPixmap
)


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
        # 使用临时配置目录启动LibreOffice
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
        info = QLabel("v1.4 · smolvla_lew\nlerobot 0.5.2")
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

        # ====== 新增：解决方案文档按钮（保留Markdown按钮） ======
        doc_btn = QPushButton("📋 解决方案v2.0")
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
        doc_btn.clicked.connect(lambda: open_ppt_with_libreoffice(os.path.join(os.path.dirname(__file__), "Z-MAX管理层汇报.pptx")))
        row.addWidget(doc_btn)

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
        """打开解决方案文档 v2.0"""
        try:
            # 从当前文件位置向上两级到项目根目录，然后进入 docs 目录
            doc_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', '具身机器人产品解决方案-工厂精细操作v2.0.md')
            subprocess.run([
                'xdg-open',
                doc_path
            ], check=True)
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"无法打开文档:\n{str(e)}")


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
    def __init__(self):
        super().__init__("数据集管理", [("System 2", SYS2_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)

        info_box = QGroupBox("数据集信息"); info_box.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        il = QFormLayout()
        cb = QComboBox(); cb.addItems(["smolvla_dataset_v1", "vla_jepa_dataset", "自定义..."])
        il.addRow("数据集:", cb)
        info_box.setLayout(il)
        bl.addWidget(info_box)

        btn_row = QHBoxLayout()
        for txt in ["查看信息", "可视化", "编辑数据集"]:
            b = QPushButton(txt)
            b.setStyleSheet(f"""QPushButton{{background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:10px 18px; margin:0;}}
            QPushButton:hover{{border-color:{SYS2_COLOR};}}""")
            btn_row.addWidget(b)
        bl.addLayout(btn_row)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setStyleSheet(f"background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(self.log)
        body.setLayout(bl)
        self._build_shell(body)


class TrainingModule(SubModuleWidget):
    def __init__(self):
        super().__init__("训练控制台", [("Sys-11", SYS11_COLOR), ("Sys-12", SYS12_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)

        # 参数区
        param = QGroupBox("训练参数"); param.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        pl = QFormLayout()
        bs = QSpinBox(); bs.setRange(1, 256); bs.setValue(8)
        pl.addRow("Batch Size:", bs)
        st = QSpinBox(); st.setRange(100, 1000000); st.setValue(100000); st.setSingleStep(1000)
        pl.addRow("Steps:", st)
        lr = QDoubleSpinBox(); lr.setRange(0.000001, 0.1); lr.setValue(0.0001); lr.setDecimals(6)
        pl.addRow("Learning Rate:", lr)
        res = QCheckBox("Resume from checkpoint")
        pl.addRow("", res)
        param.setLayout(pl)
        bl.addWidget(param)

        # 控制按钮
        ctrl = QHBoxLayout()
        start = QPushButton("▶ 开始训练")
        start.setStyleSheet(f"background:{C_GREEN}; color:white; border-radius:6px; padding:10px 24px; font-weight:bold; margin:0;")
        ctrl.addWidget(start)
        for txt in ["⏸ 暂停", "⏹ 停止"]:
            b = QPushButton(txt)
            b.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:10px; margin:0;")
            ctrl.addWidget(b)
        bl.addLayout(ctrl)

        # 进度
        prog = QProgressBar(); prog.setRange(0, 100); prog.setValue(0)
        prog.setStyleSheet(f"QProgressBar{{background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:4px; text-align:center; color:{C_WHITE}; padding:4px;}} QProgressBar::chunk{{background:{SYS11_COLOR}; border-radius:4px;}}")
        bl.addWidget(prog)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setStyleSheet(f"background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(self.log)

        body.setLayout(bl)
        self._build_shell(body)


class EvalModule(SubModuleWidget):
    def __init__(self):
        super().__init__("评估分析", [("Sys-12", SYS12_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)

        ckpt = QGroupBox("检查点"); ckpt.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        cl = QFormLayout()
        cb = QComboBox(); cb.addItems(["latest", "best", "checkpoint_10000", "自定义..."])
        cl.addRow("Checkpoint:", cb)
        ep = QSpinBox(); ep.setRange(1, 1000); ep.setValue(50)
        cl.addRow("Episode数:", ep)
        ckpt.setLayout(cl)
        bl.addWidget(ckpt)

        btn_row = QHBoxLayout()
        for txt in ["运行评估", "动作回放", "Rollout"]:
            b = QPushButton(txt)
            b.setStyleSheet(f"""QPushButton{{background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:10px 18px; margin:0;}}
            QPushButton:hover{{border-color:{SYS12_COLOR};}}""")
            btn_row.addWidget(b)
        bl.addLayout(btn_row)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setStyleSheet(f"background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(self.log)
        body.setLayout(bl)
        self._build_shell(body)


class HardwareModule(SubModuleWidget):
    def __init__(self):
        super().__init__("硬件工具箱", [("System 0", SYS0_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(10)

        sections = [
            ("校准", ["校准机器人", "查找关节限位"]),
            ("相机", ["发现相机", "相机预览"]),
            ("电机", ["配置电机", "查找端口"]),
            ("数据采集", ["实时遥操作", "录制数据集"]),
        ]
        for title, btns in sections:
            g = QGroupBox(title); g.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
            gl = QHBoxLayout()
            for btxt in btns:
                b = QPushButton(btxt)
                b.setStyleSheet(f"""QPushButton{{background:{SYS0_COLOR}22; color:{SYS0_COLOR}; border:1px solid {SYS0_COLOR}44; border-radius:6px; padding:10px 16px; margin:0;}}
                QPushButton:hover{{background:{SYS0_COLOR}44;}}""")
                gl.addWidget(b)
            g.setLayout(gl)
            bl.addWidget(g)

        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setFixedHeight(120)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setStyleSheet(f"background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(self.log)
        body.setLayout(bl)
        self._build_shell(body)


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
    def __init__(self):
        super().__init__("实时监控", [("Sys-11", SYS11_COLOR), ("Sys-12", SYS12_COLOR)])
        body = QWidget()
        bl = QVBoxLayout(); bl.setSpacing(12)

        # GPU
        gpu = QGroupBox("GPU状态"); gpu.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        gl = QVBoxLayout()
        gi = QLabel("NVIDIA RTX 4060 · 8GB"); gi.setFont(QFont("Consolas", 11))
        gi.setStyleSheet(f"color:{C_GREEN}; background:transparent; border:none; margin:0; padding:4px 0;")
        gl.addWidget(gi)
        prog = QProgressBar(); prog.setRange(0, 8192); prog.setValue(3200)
        prog.setFormat("%v / 8192 MB")
        prog.setStyleSheet(f"QProgressBar{{background:{C_BG}; border:1px solid {C_BORDER}; border-radius:4px; color:{C_WHITE}; padding:4px;}} QProgressBar::chunk{{background:{SYS11_COLOR}; border-radius:4px;}}")
        mem_label = QLabel("显存:")
        mem_label.setFont(QFont("Arial", 10))
        mem_label.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none; margin:0; padding:4px 0;")
        gl.addWidget(mem_label)
        gl.addWidget(prog)
        gpu.setLayout(gl)
        bl.addWidget(gpu)

        # 曲线占位
        curve = QGroupBox("训练曲线 (待实现)"); curve.setStyleSheet(f"QGroupBox{{color:{C_WHITE}; {card_style(C_CARD, C_BORDER, 8, 12)}}}")
        ccl = QVBoxLayout()
        pl = QLabel("📊  Action Loss · LeW Loss · Learning Rate · Grad Norm")
        pl.setAlignment(Qt.AlignCenter)
        pl.setFont(QFont("Arial", 12))
        pl.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none; padding:24px; margin:0;")
        ccl.addWidget(pl)
        curve.setLayout(ccl)
        bl.addWidget(curve)

        # 终端
        term = QTextEdit(); term.setReadOnly(True)
        term.setFont(QFont("Consolas", 10))
        term.setStyleSheet(f"background:#0a0e14; color:{C_GREEN}; border:1px solid {C_BORDER}; border-radius:6px; padding:8px;")
        bl.addWidget(term)

        refresh = QPushButton("刷新状态")
        refresh.setStyleSheet(f"background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER}; border-radius:6px; padding:10px 20px; margin:0;")
        bl.addWidget(refresh)

        body.setLayout(bl)
        self._build_shell(body)


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
        }

        self.stack.addWidget(DatasetModule())
        self.stack.addWidget(TrainingModule())
        self.stack.addWidget(EvalModule())
        self.stack.addWidget(HardwareModule())
        self.stack.addWidget(ConfigModule())
        self.stack.addWidget(MonitorModule())

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
        names = ["首页", "数据集", "训练", "评估", "硬件", "配置", "监控"]
        self.statusBar().showMessage(f"● {names[idx]}  |  Z-MAX 三层解耦架构  |  Sys-0 + Sys-11 + Sys-12 + Sys-2")


# ============================================================
# 入口
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))

    # 全局滚动条样式
    app.setStyleSheet("""
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar::handle:vertical { background: #484f58; border-radius: 4px; min-height: 20px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
    """)

    win = StudioMainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
