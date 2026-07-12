"""
Z-MAX 任务看板嵌入 LeRobot Studio — PyQt5 QWebEngineView

使用方法:
1. 在 le_robot_studio.py 顶部加:
   from PyQt5.QtWebEngineWidgets import QWebEngineView

2. 在 __init__ 方法的 tab_widget 初始化后加:
   self.add_kanban_tab()

3. 把这个类粘贴到文件末尾
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl

class KanbanTab(QWidget):
    """Z-MAX 任务看板嵌入"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        
        # 工具栏
        toolbar = QHBoxLayout()
        title = QLabel("📋 Z-MAX 任务看板")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#00d4aa;")
        toolbar.addWidget(title)
        toolbar.addStretch()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)
        
        # WebView 嵌入看板
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://datadrive.world/kanban.html"))
        layout.addWidget(self.webview)
        
        self.setLayout(layout)
    
    def refresh(self):
        self.webview.reload()
