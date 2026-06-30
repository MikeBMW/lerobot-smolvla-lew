#!/usr/bin/env python3
"""
LeRobot Studio - 入口首页
参考ROKAE-Brain架构图的层级化设计理念
深色科技风 + 卡片式入口
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout, QSizePolicy,
    QGraphicsDropShadowEffect, QScrollArea, QSpacerItem
)
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import (
    QFont, QColor, QPainter, QLinearGradient, QBrush,
    QFontDatabase, QIcon, QPixmap, QPainterPath, QPen
)


# ============================================================
# 颜色常量
# ============================================================
BG_PRIMARY   = "#0d1117"
BG_SECONDARY = "#161b22"
BG_CARD      = "#1c2333"
BG_CARD_HOVER = "#252d3a"
ACCENT_BLUE  = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_ORANGE= "#d29922"
ACCENT_RED   = "#f85149"
ACCENT_PURPLE= "#bc8cff"
ACCENT_CYAN  = "#39d2c0"
TEXT_PRIMARY  = "#e6edf3"
TEXT_SECONDARY= "#8b949e"
TEXT_MUTED    = "#484f58"
BORDER_COLOR  = "#30363d"


# ============================================================
# 模块卡片组件
# ============================================================
class ModuleCard(QFrame):
    """功能模块入口卡片"""
    clicked = pyqtSignal(str)

    def __init__(self, module_id, icon, title, subtitle, description, accent_color, parent=None):
        super().__init__(parent)
        self.module_id = module_id
        self.accent_color = accent_color
        self.is_hovered = False
        self.setup_ui(icon, title, subtitle, description)

    def setup_ui(self, icon, title, subtitle, description):
        self.setFixedHeight(200)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self.setStyleSheet(f"""
            ModuleCard {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER_COLOR};
                border-radius: 12px;
                padding: 20px;
            }}
        """)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(20, 20, 20, 20)

        # 顶部：图标 + 标识线
        top_layout = QHBoxLayout()
        
        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 28))
        icon_label.setStyleSheet(f"color: {self.accent_color}; background: transparent; border: none;")
        top_layout.addWidget(icon_label)
        top_layout.addStretch()

        # 状态点
        status = QLabel("●")
        status.setFont(QFont("Arial", 8))
        status.setStyleSheet(f"color: {self.accent_color}; background: transparent; border: none;")
        top_layout.addWidget(status)

        layout.addLayout(top_layout)

        # 标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        layout.addWidget(title_label)

        # 副标题
        sub_label = QLabel(subtitle)
        sub_label.setFont(QFont("Arial", 10))
        sub_label.setStyleSheet(f"color: {self.accent_color}; background: transparent; border: none;")
        layout.addWidget(sub_label)

        # 描述
        desc_label = QLabel(description)
        desc_label.setFont(QFont("Arial", 9))
        desc_label.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent; border: none;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addStretch()

        # 底部箭头提示
        arrow_label = QLabel("点击进入 →")
        arrow_label.setFont(QFont("Arial", 9))
        arrow_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
        layout.addWidget(arrow_label)

        self.setLayout(layout)

        # 添加阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

    def enterEvent(self, event):
        self.is_hovered = True
        self.setStyleSheet(f"""
            ModuleCard {{
                background-color: {BG_CARD_HOVER};
                border: 1px solid {self.accent_color};
                border-radius: 12px;
                padding: 20px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.setStyleSheet(f"""
            ModuleCard {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER_COLOR};
                border-radius: 12px;
                padding: 20px;
            }}
        """)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.clicked.emit(self.module_id)
        super().mousePressEvent(event)


# ============================================================
# 系统架构图组件（简化版ROKAE-Brain风格）
# ============================================================
class ArchitectureFlow(QFrame):
    """展示系统架构流程的组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setFixedHeight(120)
        self.setStyleSheet(f"""
            ArchitectureFlow {{
                background-color: {BG_SECONDARY};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
            }}
        """)

        layout = QHBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(20, 15, 20, 15)

        stages = [
            ("📡", "观测/记忆", ACCENT_BLUE),
            ("→", "", TEXT_MUTED),
            ("🧩", "模态融合", ACCENT_CYAN),
            ("→", "", TEXT_MUTED),
            ("🌐", "世界模型", ACCENT_PURPLE),
            ("→", "", TEXT_MUTED),
            ("⚡", "高效推理", ACCENT_GREEN),
            ("→", "", TEXT_MUTED),
            ("🤖", "精细执行", ACCENT_ORANGE),
        ]

        for icon, text, color in stages:
            if text == "":
                arrow = QLabel(icon)
                arrow.setFont(QFont("Arial", 18))
                arrow.setStyleSheet(f"color: {color}; background: transparent; border: none;")
                arrow.setAlignment(Qt.AlignCenter)
                layout.addWidget(arrow)
            else:
                stage_frame = QFrame()
                stage_frame.setStyleSheet(f"""
                    background-color: {BG_CARD};
                    border: 1px solid {color};
                    border-radius: 8px;
                    padding: 8px;
                """)
                stage_layout = QVBoxLayout()
                stage_layout.setSpacing(4)
                stage_layout.setContentsMargins(10, 8, 10, 8)

                icon_lbl = QLabel(icon)
                icon_lbl.setFont(QFont("Segoe UI Emoji", 20))
                icon_lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
                icon_lbl.setAlignment(Qt.AlignCenter)
                stage_layout.addWidget(icon_lbl)

                text_lbl = QLabel(text)
                text_lbl.setFont(QFont("Arial", 10, QFont.Bold))
                text_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
                text_lbl.setAlignment(Qt.AlignCenter)
                stage_layout.addWidget(text_lbl)

                stage_frame.setLayout(stage_layout)
                layout.addWidget(stage_frame)

        self.setLayout(layout)


# ============================================================
# 首页主窗口
# ============================================================
class HomePage(QMainWindow):
    module_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeRobot Studio")
        self.setMinimumSize(1200, 800)
        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background-color: {BG_PRIMARY};")

        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ============ 顶部导航栏 ============
        navbar = self.create_navbar()
        main_layout.addWidget(navbar)

        # ============ 可滚动内容区 ============
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content = QWidget()
        content.setStyleSheet(f"background-color: {BG_PRIMARY};")
        content_layout = QVBoxLayout()
        content_layout.setSpacing(24)
        content_layout.setContentsMargins(48, 32, 48, 32)

        # --- Hero区域 ---
        hero = self.create_hero_section()
        content_layout.addWidget(hero)

        # --- 系统架构流程 ---
        arch_label = QLabel("系统架构  System Architecture")
        arch_label.setFont(QFont("Arial", 12, QFont.Bold))
        arch_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        content_layout.addWidget(arch_label)

        arch_flow = ArchitectureFlow()
        content_layout.addWidget(arch_flow)

        # --- 功能模块卡片 ---
        module_label = QLabel("功能模块  Modules")
        module_label.setFont(QFont("Arial", 12, QFont.Bold))
        module_label.setStyleSheet(f"color: {TEXT_SECONDARY}; margin-top: 8px;")
        content_layout.addWidget(module_label)

        cards_grid = self.create_modules_grid()
        content_layout.addWidget(cards_grid)

        # --- 快速统计 ---
        stats_label = QLabel("项目状态  Project Status")
        stats_label.setFont(QFont("Arial", 12, QFont.Bold))
        stats_label.setStyleSheet(f"color: {TEXT_SECONDARY}; margin-top: 8px;")
        content_layout.addWidget(stats_label)

        stats = self.create_stats_bar()
        content_layout.addWidget(stats)

        content_layout.addStretch()
        content.setLayout(content_layout)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # ============ 底部状态栏 ============
        statusbar = self.create_statusbar()
        main_layout.addWidget(statusbar)

        central.setLayout(main_layout)

    def create_navbar(self):
        """顶部导航栏"""
        nav = QFrame()
        nav.setFixedHeight(56)
        nav.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SECONDARY};
                border-bottom: 1px solid {BORDER_COLOR};
            }}
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(24, 0, 24, 0)

        # Logo + 标题
        logo = QLabel("🤖")
        logo.setFont(QFont("Segoe UI Emoji", 20))
        logo.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(logo)

        title = QLabel("LeRobot Studio")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        layout.addWidget(title)

        version = QLabel("v0.1")
        version.setFont(QFont("Arial", 10))
        version.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
        layout.addWidget(version)

        layout.addStretch()

        # 项目路径
        path_label = QLabel("📂 ~/xspace/lerobot-smolvla-lew")
        path_label.setFont(QFont("Consolas", 9))
        path_label.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent; border: none;")
        layout.addWidget(path_label)

        layout.addSpacing(20)

        # GPU状态
        gpu_label = QLabel("🖥️ RTX 4060 · 8GB")
        gpu_label.setFont(QFont("Arial", 9))
        gpu_label.setStyleSheet(f"color: {ACCENT_GREEN}; background: transparent; border: none;")
        layout.addWidget(gpu_label)

        nav.setLayout(layout)
        return nav

    def create_hero_section(self):
        """Hero区域 - 项目总览"""
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SECONDARY};
                border: 1px solid {BORDER_COLOR};
                border-radius: 12px;
                padding: 24px;
            }}
        """)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(28, 24, 28, 24)

        # 标题行
        title_row = QHBoxLayout()
        
        main_title = QLabel("Z-MAX 多模态动作专家")
        main_title.setFont(QFont("Arial", 24, QFont.Bold))
        main_title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        title_row.addWidget(main_title)

        title_row.addStretch()

        badge = QLabel("● smolvla_lew")
        badge.setFont(QFont("Arial", 10, QFont.Bold))
        badge.setStyleSheet(f"""
            background-color: {ACCENT_PURPLE};
            color: white;
            border-radius: 12px;
            padding: 4px 12px;
        """)
        title_row.addWidget(badge)

        layout.addLayout(title_row)

        # 描述
        desc = QLabel("高速光模块精细操作具身机器人 · L4级全自主操作 · SmolVLM 500M + DiT-B Flow Matching")
        desc.setFont(QFont("Arial", 11))
        desc.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent; border: none;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 关键指标行
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(32)

        metrics = [
            ("±0.02mm", "定位精度", ACCENT_BLUE),
            ("99.2%", "连续成功率", ACCENT_GREEN),
            ("<10ms", "推理延迟", ACCENT_CYAN),
            ("500M", "模型参数", ACCENT_PURPLE),
        ]

        for value, label, color in metrics:
            metric_layout = QVBoxLayout()
            metric_layout.setSpacing(2)
            
            val = QLabel(value)
            val.setFont(QFont("Arial", 18, QFont.Bold))
            val.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            metric_layout.addWidget(val)
            
            lbl = QLabel(label)
            lbl.setFont(QFont("Arial", 9))
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
            metric_layout.addWidget(lbl)
            
            metrics_row.addLayout(metric_layout)

        metrics_row.addStretch()
        layout.addLayout(metrics_row)

        hero.setLayout(layout)
        return hero

    def create_modules_grid(self):
        """6大功能模块卡片网格"""
        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setContentsMargins(0, 0, 0, 0)

        modules = [
            {
                "id": "dataset",
                "icon": "📊",
                "title": "数据集管理",
                "subtitle": "Dataset Manager",
                "description": "浏览、录制、编辑、可视化数据集\n支持 .lrobot 格式与 HF Datasets",
                "color": ACCENT_BLUE,
            },
            {
                "id": "training",
                "icon": "🏋️",
                "title": "训练控制台",
                "subtitle": "Training Console",
                "description": "配置训练参数、启动/监控训练\nSmolVLA + LeWorldModel 联合训练",
                "color": ACCENT_GREEN,
            },
            {
                "id": "evaluation",
                "icon": "✅",
                "title": "评估分析",
                "subtitle": "Evaluation & Analysis",
                "description": "模型评估、动作回放、Rollout仿真\n多维度成功率分析与对比",
                "color": ACCENT_ORANGE,
            },
            {
                "id": "hardware",
                "icon": "🔧",
                "title": "硬件工具箱",
                "subtitle": "Hardware Toolkit",
                "description": "机器人校准、相机配置、电机设置\n遥操作与数据采集",
                "color": ACCENT_RED,
            },
            {
                "id": "config",
                "icon": "⚙️",
                "title": "配置中心",
                "subtitle": "Config Center",
                "description": "策略参数编辑、训练管线配置\nSmolVLALewConfig 可视化管理",
                "color": ACCENT_PURPLE,
            },
            {
                "id": "monitor",
                "icon": "📈",
                "title": "实时监控",
                "subtitle": "Real-time Monitor",
                "description": "训练曲线、GPU状态、终端输出\nLoss/LR/Grad Norm 实时追踪",
                "color": ACCENT_CYAN,
            },
        ]

        self.cards = {}
        for i, mod in enumerate(modules):
            card = ModuleCard(
                module_id=mod["id"],
                icon=mod["icon"],
                title=mod["title"],
                subtitle=mod["subtitle"],
                description=mod["description"],
                accent_color=mod["color"]
            )
            card.clicked.connect(self.on_module_clicked)
            self.cards[mod["id"]] = card
            grid.addWidget(card, i // 3, i % 3)

        grid_widget.setLayout(grid)
        return grid_widget

    def create_stats_bar(self):
        """项目状态统计条"""
        stats_frame = QFrame()
        stats_frame.setFixedHeight(80)
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SECONDARY};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
            }}
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(40)

        stats = [
            ("🗂️ 策略数量", "19"),
            ("📝 脚本数量", "20"),
            ("📦 数据集", "2"),
            ("💾 Checkpoints", "3"),
            ("⏱️ 上次训练", "2h 前"),
            ("🔬 策略选型", "smolvla_lew"),
        ]

        for label, value in stats:
            col = QVBoxLayout()
            col.setSpacing(2)

            lbl = QLabel(label)
            lbl.setFont(QFont("Arial", 9))
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
            col.addWidget(lbl)

            val = QLabel(value)
            val.setFont(QFont("Arial", 12, QFont.Bold))
            val.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
            col.addWidget(val)

            layout.addLayout(col)

        layout.addStretch()
        stats_frame.setLayout(layout)
        return stats_frame

    def create_statusbar(self):
        """底部状态栏"""
        bar = QFrame()
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SECONDARY};
                border-top: 1px solid {BORDER_COLOR};
            }}
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        items = [
            (f"● Ready", ACCENT_GREEN),
            (f"Python 3.12 · PyTorch", TEXT_MUTED),
            (f"lerobot v0.5.2", TEXT_MUTED),
        ]

        for text, color in items:
            lbl = QLabel(text)
            lbl.setFont(QFont("Consolas", 9))
            lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            layout.addWidget(lbl)

        layout.addStretch()

        time_lbl = QLabel("Ctrl+Q 退出 · F1 帮助")
        time_lbl.setFont(QFont("Consolas", 9))
        time_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
        layout.addWidget(time_lbl)

        bar.setLayout(layout)
        return bar

    def on_module_clicked(self, module_id):
        """模块卡片点击回调"""
        print(f"[LeRobot Studio] 进入模块: {module_id}")
        self.module_clicked.emit(module_id)


# ============================================================
# 入口
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 全局字体
    font = QFont("Arial", 10)
    app.setFont(font)

    window = HomePage()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
