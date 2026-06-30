#!/usr/bin/env python3
"""
LeRobot Studio - 可视化开发界面
基于 PyQt5 构建的 LeRobot 工作流管理工具
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QGroupBox, 
    QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QComboBox, QProgressBar, QSplitter, QFrame, QMessageBox,
    QAction, QMenuBar, QStatusBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon


class DatasetTab(QWidget):
    """数据集管理模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 标题
        title = QLabel("数据集管理")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 数据集选择
        select_group = QGroupBox("数据集选择")
        select_layout = QFormLayout()
        self.dataset_combo = QComboBox()
        self.dataset_combo.addItems(["smolvla_dataset_v1", "vla_jepa_dataset", "自定义..."])
        select_layout.addRow("数据集:", self.dataset_combo)
        
        self.browse_btn = QPushButton("浏览数据集目录")
        select_layout.addRow("", self.browse_btn)
        select_group.setLayout(select_layout)
        layout.addWidget(select_group)
        
        # 数据集信息
        info_group = QGroupBox("数据集信息")
        info_layout = QVBoxLayout()
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setPlaceholderText("数据集信息将显示在这里...")
        info_layout.addWidget(self.info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.info_btn = QPushButton("查看信息 (lerobot-info)")
        self.viz_btn = QPushButton("可视化 (lerobot-dataset-viz)")
        self.edit_btn = QPushButton("编辑数据集")
        btn_layout.addWidget(self.info_btn)
        btn_layout.addWidget(self.viz_btn)
        btn_layout.addWidget(self.edit_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)


class TrainingTab(QWidget):
    """训练控制模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        title = QLabel("训练控制台")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 训练参数
        param_group = QGroupBox("训练参数 (TrainPipelineConfig)")
        param_layout = QFormLayout()
        
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 256)
        self.batch_size_spin.setValue(8)
        param_layout.addRow("Batch Size:", self.batch_size_spin)
        
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(100, 1000000)
        self.steps_spin.setValue(100000)
        self.steps_spin.setSingleStep(1000)
        param_layout.addRow("Steps:", self.steps_spin)
        
        self.lr_spin = QDoubleSpinBox()
        self.lr_spin.setRange(0.000001, 0.1)
        self.lr_spin.setValue(0.0001)
        self.lr_spin.setDecimals(6)
        self.lr_spin.setSingleStep(0.00001)
        param_layout.addRow("Learning Rate:", self.lr_spin)
        
        self.num_workers_spin = QSpinBox()
        self.num_workers_spin.setRange(0, 16)
        self.num_workers_spin.setValue(4)
        param_layout.addRow("Num Workers:", self.num_workers_spin)
        
        self.resume_check = QCheckBox("Resume from checkpoint")
        param_layout.addRow("", self.resume_check)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # 训练控制
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ 开始训练")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.pause_btn = QPushButton("⏸ 暂停")
        self.stop_btn = QPushButton("⏹ 停止")
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.stop_btn)
        layout.addLayout(control_layout)
        
        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
        # 训练日志
        log_group = QGroupBox("训练日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        self.setLayout(layout)


class EvaluationTab(QWidget):
    """评估模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        title = QLabel("模型评估")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 检查点选择
        ckpt_group = QGroupBox("模型检查点")
        ckpt_layout = QFormLayout()
        self.ckpt_combo = QComboBox()
        self.ckpt_combo.addItems(["latest", "checkpoint_10000", "checkpoint_50000", "best", "自定义..."])
        ckpt_layout.addRow("Checkpoint:", self.ckpt_combo)
        ckpt_group.setLayout(ckpt_layout)
        layout.addWidget(ckpt_group)
        
        # 评估参数
        eval_group = QGroupBox("评估参数")
        eval_layout = QFormLayout()
        
        self.n_episodes_spin = QSpinBox()
        self.n_episodes_spin.setRange(1, 1000)
        self.n_episodes_spin.setValue(50)
        eval_layout.addRow("Episode数:", self.n_episodes_spin)
        
        self.max_steps_spin = QSpinBox()
        self.max_steps_spin.setRange(100, 10000)
        self.max_steps_spin.setValue(500)
        eval_layout.addRow("Max Steps:", self.max_steps_spin)
        
        eval_group.setLayout(eval_layout)
        layout.addWidget(eval_group)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.eval_btn = QPushButton("运行评估 (lerobot-eval)")
        self.replay_btn = QPushButton("回放 (lerobot-replay)")
        self.rollout_btn = QPushButton("Rollout")
        btn_layout.addWidget(self.eval_btn)
        btn_layout.addWidget(self.replay_btn)
        btn_layout.addWidget(self.rollout_btn)
        layout.addLayout(btn_layout)
        
        # 结果展示
        result_group = QGroupBox("评估结果")
        result_layout = QVBoxLayout()
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("评估结果将显示在这里...")
        result_layout.addWidget(self.result_text)
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)
        
        self.setLayout(layout)


class HardwareTab(QWidget):
    """硬件配置模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        title = QLabel("硬件工具箱")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 校准
        calib_group = QGroupBox("机器人校准")
        calib_layout = QVBoxLayout()
        self.calib_btn = QPushButton("校准机器人 (lerobot-calibrate)")
        self.find_joints_btn = QPushButton("查找关节限位")
        calib_layout.addWidget(self.calib_btn)
        calib_layout.addWidget(self.find_joints_btn)
        calib_group.setLayout(calib_layout)
        layout.addWidget(calib_group)
        
        # 相机
        cam_group = QGroupBox("相机配置")
        cam_layout = QVBoxLayout()
        self.find_cam_btn = QPushButton("发现相机 (lerobot-find-cameras)")
        cam_layout.addWidget(self.find_cam_btn)
        cam_group.setLayout(cam_layout)
        layout.addWidget(cam_group)
        
        # 电机
        motor_group = QGroupBox("电机配置")
        motor_layout = QVBoxLayout()
        self.setup_motor_btn = QPushButton("配置电机 (lerobot-setup-motors)")
        self.find_port_btn = QPushButton("查找端口 (lerobot-find-port)")
        motor_layout.addWidget(self.setup_motor_btn)
        motor_layout.addWidget(self.find_port_btn)
        motor_group.setLayout(motor_layout)
        layout.addWidget(motor_group)
        
        # 遥操作
        tele_group = QGroupBox("数据采集")
        tele_layout = QVBoxLayout()
        self.teleop_btn = QPushButton("实时遥操作 (lerobot-teleoperate)")
        self.record_btn = QPushButton("录制数据集 (lerobot-record)")
        tele_layout.addWidget(self.teleop_btn)
        tele_layout.addWidget(self.record_btn)
        tele_group.setLayout(tele_layout)
        layout.addWidget(tele_group)
        
        # 输出
        output_group = QGroupBox("命令输出")
        output_layout = QVBoxLayout()
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier", 9))
        output_layout.addWidget(self.output_text)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        self.setLayout(layout)


class ConfigTab(QWidget):
    """配置编辑模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        title = QLabel("配置编辑器")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # 策略选择
        policy_group = QGroupBox("策略选择")
        policy_layout = QFormLayout()
        self.policy_combo = QComboBox()
        self.policy_combo.addItems([
            "smolvla_lew",
            "vla_jepa", 
            "smolvla",
            "act",
            "diffusion",
            "pi0",
            "其他..."
        ])
        policy_layout.addRow("策略:", self.policy_combo)
        policy_group.setLayout(policy_layout)
        layout.addWidget(policy_group)
        
        # smolvla_lew 参数
        smolvla_group = QGroupBox("SmolVLALewConfig 参数")
        smolvla_layout = QFormLayout()
        
        self.vlm_combo = QComboBox()
        self.vlm_combo.addItems([
            "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
            "自定义..."
        ])
        smolvla_layout.addRow("VLM模型:", self.vlm_combo)
        
        self.freeze_vlm_check = QCheckBox("冻结VLM主干")
        self.freeze_vlm_check.setChecked(True)
        smolvla_layout.addRow("", self.freeze_vlm_check)
        
        self.enable_lew_check = QCheckBox("启用LeWorldModel")
        smolvla_layout.addRow("", self.enable_lew_check)
        
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(1, 100)
        self.chunk_size_spin.setValue(7)
        smolvla_layout.addRow("Chunk Size:", self.chunk_size_spin)
        
        self.action_model_combo = QComboBox()
        self.action_model_combo.addItems(["DiT-B", "DiT-L", "DiT-test"])
        smolvla_layout.addRow("Action Model:", self.action_model_combo)
        
        self.inference_steps_spin = QSpinBox()
        self.inference_steps_spin.setRange(1, 100)
        self.inference_steps_spin.setValue(4)
        smolvla_layout.addRow("Inference Steps:", self.inference_steps_spin)
        
        self.binarize_gripper_check = QCheckBox("二值化Gripper")
        self.binarize_gripper_check.setChecked(True)
        smolvla_layout.addRow("", self.binarize_gripper_check)
        
        smolvla_group.setLayout(smolvla_layout)
        layout.addWidget(smolvla_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("加载配置")
        self.save_btn = QPushButton("保存配置")
        self.validate_btn = QPushButton("验证配置")
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.validate_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)


class MonitoringTab(QWidget):
    """监控模块"""
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        title = QLabel("实时监控")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        # GPU状态
        gpu_group = QGroupBox("GPU状态")
        gpu_layout = QVBoxLayout()
        
        self.gpu_info = QLabel()
        self.gpu_info.setText("GPU: NVIDIA RTX 4060\n显存: 0 MB / 8192 MB\n利用率: 0%")
        self.gpu_info.setStyleSheet("font-family: Courier; background-color: #f0f0f0; padding: 10px;")
        gpu_layout.addWidget(self.gpu_info)
        
        self.gpu_progress = QProgressBar()
        self.gpu_progress.setRange(0, 100)
        self.gpu_progress.setValue(0)
        gpu_layout.addWidget(QLabel("显存使用:"))
        gpu_layout.addWidget(self.gpu_progress)
        
        gpu_group.setLayout(gpu_layout)
        layout.addWidget(gpu_group)
        
        # 训练曲线 (占位)
        curve_group = QGroupBox("训练曲线 (待实现)")
        curve_layout = QVBoxLayout()
        self.curve_placeholder = QLabel("📊 训练曲线将在这里显示\n(loss, learning_rate, grad_norm)")
        self.curve_placeholder.setAlignment(Qt.AlignCenter)
        self.curve_placeholder.setStyleSheet("font-size: 14px; color: #666;")
        curve_layout.addWidget(self.curve_placeholder)
        curve_group.setLayout(curve_layout)
        layout.addWidget(curve_group)
        
        # 终端输出
        term_group = QGroupBox("终端输出")
        term_layout = QVBoxLayout()
        self.term_text = QTextEdit()
        self.term_text.setReadOnly(True)
        self.term_text.setFont(QFont("Courier", 9))
        self.term_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        term_layout.addWidget(self.term_text)
        term_group.setLayout(term_layout)
        layout.addWidget(term_group)
        
        # 刷新按钮
        self.refresh_btn = QPushButton("刷新状态")
        layout.addWidget(self.refresh_btn)
        
        self.setLayout(layout)


class LeRobotStudio(QMainWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeRobot Studio - 可视化开发界面")
        self.setGeometry(100, 100, 1200, 800)
        
        self.setup_ui()
        self.setup_menus()
        self.setup_statusbar()
    
    def setup_ui(self):
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 欢迎标题
        header = QLabel("🤖 LeRobot Studio")
        header.setFont(QFont("Arial", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("padding: 10px; background-color: #f8f8f8;")
        main_layout.addWidget(header)
        
        # Tab Widget
        self.tabs = QTabWidget()
        
        # 添加各个tab
        self.dataset_tab = DatasetTab()
        self.training_tab = TrainingTab()
        self.eval_tab = EvaluationTab()
        self.hardware_tab = HardwareTab()
        self.config_tab = ConfigTab()
        self.monitor_tab = MonitoringTab()
        
        self.tabs.addTab(self.dataset_tab, "📊 数据集")
        self.tabs.addTab(self.training_tab, "🏋️ 训练")
        self.tabs.addTab(self.eval_tab, "✅ 评估")
        self.tabs.addTab(self.hardware_tab, "🔧 硬件")
        self.tabs.addTab(self.config_tab, "⚙️ 配置")
        self.tabs.addTab(self.monitor_tab, "📈 监控")
        
        main_layout.addWidget(self.tabs)
    
    def setup_menus(self):
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        open_action = QAction("打开项目...", self)
        open_action.setShortcut("Ctrl+O")
        file_menu.addAction(open_action)
        
        save_action = QAction("保存配置", self)
        save_action.setShortcut("Ctrl+S")
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu("工具")
        
        terminal_action = QAction("打开终端", self)
        tools_menu.addAction(terminal_action)
        
        clear_action = QAction("清除日志", self)
        tools_menu.addAction(clear_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        docs_action = QAction("文档", self)
        help_menu.addAction(docs_action)
    
    def setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪")
    
    def show_about(self):
        QMessageBox.about(
            self,
            "关于 LeRobot Studio",
            "LeRobot Studio v0.1\n\n"
            "基于 PyQt5 构建的 LeRobot 可视化开发界面\n\n"
            "功能模块:\n"
            "• 数据集管理\n"
            "• 训练控制\n"
            "• 模型评估\n"
            "• 硬件配置\n"
            "• 参数编辑\n"
            "• 实时监控\n\n"
            "项目: /home/admin/xspace/lerobot-smolvla-lew"
        )


def main():
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    window = LeRobotStudio()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
