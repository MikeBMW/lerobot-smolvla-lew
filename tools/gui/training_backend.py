"""
Z-MAX Training Backend Module
Handles subprocess management for LeRobot training scripts
"""

import os
import sys
import subprocess
import threading
from PyQt5.QtCore import QObject, pyqtSignal
from pathlib import Path


class TrainingBackend(QObject):
    """Backend process manager for training operations"""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.is_running = False
        self.is_paused = False
        self.monitor_thread = None
    
    def start_training(self, repo_root: str, dataset_repo_id: str, policy_name: str,
                       batch_size: int, total_steps: int, learning_rate: float,
                       checkpoint_interval: int, output_dir: str = "outputs"):
        """
        启动训练进程
        
        Args:
            repo_root: XSpace Studio仓库根目录
            dataset_repo_id: 数据集仓库ID (如 lerobot/pusht)
            policy_name: 策略名称 (smolvla 或 smolvla_lew)
            batch_size: 批次大小
            total_steps: 总训练步数
            learning_rate: 学习率
            checkpoint_interval: 检查点间隔
            output_dir: 输出目录
        """
        if self.is_running:
            self.log_signal.emit("⚠️ 训练已在运行中")
            return False
        
        # 构建训练命令
        # 使用 lerobot-train CLI 命令（用户实际在用的）
        training_script = Path(repo_root) / "src" / "lerobot" / "scripts" / "lerobot_train.py"
        
        if not training_script.exists():
            self.log_signal.emit(f"❌ 训练脚本不存在: {training_script}")
            return False
        
        # 构建命令参数
        cmd = [
            sys.executable, str(training_script),
            "--config.dataset_repo_id", dataset_repo_id,
            "--config.policy", policy_name,
            "--config.batch_size", str(batch_size),
            "--config.total_steps", str(total_steps),
            "--config.learning_rate", str(learning_rate),
            "--config.checkpoint_interval", str(checkpoint_interval),
            "--config.output_dir", str(output_dir),
        ]
        
        self.log_signal.emit("=" * 60)
        self.log_signal.emit(f"🚀 启动训练进程")
        self.log_signal.emit(f"   Python: {sys.executable}")
        self.log_signal.emit(f"   Script: {training_script}")
        self.log_signal.emit(f"   Dataset: {dataset_repo_id}")
        self.log_signal.emit(f"   Policy: {policy_name}")
        self.log_signal.emit(f"   Batch Size: {batch_size}")
        self.log_signal.emit(f"   Total Steps: {total_steps}")
        self.log_signal.emit(f"   Learning Rate: {learning_rate}")
        self.log_signal.emit(f"   Output Dir: {output_dir}")
        self.log_signal.emit("=" * 60)
        self.log_signal.emit(f"命令: {' '.join(cmd)}")
        self.log_signal.emit("")
        
        try:
            # 设置环境变量，确保Python能找到所需模块
            env = os.environ.copy()
            env['PYTHONPATH'] = f"{repo_root}/src:{env.get('PYTHONPATH', '')}"
            env['CUDA_VISIBLE_DEVICES'] = '0'  # 使用第一个GPU
            
            # 启动子进程
            self.process = subprocess.Popen(
                cmd,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并stderr到stdout
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
            )
            
            self.is_running = True
            self.is_paused = False
            
            self.log_signal.emit(f"✅ 进程已启动 (PID: {self.process.pid})")
            
            # 启动监控线程
            self.monitor_thread = threading.Thread(
                target=self._monitor_output,
                daemon=True
            )
            self.monitor_thread.start()
            
            return True
            
        except Exception as e:
            self.log_signal.emit(f"❌ 启动失败: {e}")
            return False
    
    def pause_training(self):
        """暂停训练进程"""
        if not self.is_running or not self.process:
            return False
        
        if self.is_paused:
            self.log_signal.emit("⚠️ 训练已经暂停")
            return False
        
        try:
            import signal
            os.kill(self.process.pid, signal.SIGSTOP)
            self.is_paused = True
            self.log_signal.emit("⏸️ 训练已暂停")
            return True
        except Exception as e:
            self.log_signal.emit(f"❌ 暂停失败: {e}")
            return False
    
    def resume_training(self):
        """恢复训练进程"""
        if not self.is_running or not self.process:
            return False
        
        if not self.is_paused:
            self.log_signal.emit("⚠️ 训练未暂停")
            return False
        
        try:
            import signal
            os.kill(self.process.pid, signal.SIGCONT)
            self.is_paused = False
            self.log_signal.emit("▶️ 训练已恢复")
            return True
        except Exception as e:
            self.log_signal.emit(f"❌ 恢复失败: {e}")
            return False
    
    def stop_training(self):
        """停止训练进程"""
        if not self.is_running or not self.process:
            return False
        
        try:
            self.log_signal.emit("🛑 停止训练...")
            
            # 先尝试优雅终止
            self.process.terminate()
            
            try:
                self.process.wait(timeout=5)
                self.log_signal.emit("✅ 训练已停止")
            except subprocess.TimeoutExpired:
                # 强制杀死
                self.log_signal.emit("⚠️ 进程未响应，强制终止")
                self.process.kill()
                self.process.wait()
                self.log_signal.emit("✅ 训练已强制停止")
            
            self.is_running = False
            self.is_paused = False
            self.process = None
            
            return True
            
        except Exception as e:
            self.log_signal.emit(f"❌ 停止失败: {e}")
            return False
    
    def _monitor_output(self):
        """监控训练进程输出"""
        try:
            while self.is_running and self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if line:
                    output = line.strip()
                    
                    # 发送日志信号
                    self.log_signal.emit(output)
                    
                    # 尝试解析进度信息
                    # 格式: Training: X/Y [time]
                    if "Training:" in output:
                        try:
                            import re
                            match = re.search(r'Training:\s*(\d+)/(\d+)', output)
                            if match:
                                current = int(match.group(1))
                                total = int(match.group(2))
                                progress = int((current / total) * 100)
                                self.progress_signal.emit(progress)
                        except Exception:
                            pass
            
            # 进程结束，检查退出码
            if self.process:
                exit_code = self.process.wait()
                
                if exit_code == 0:
                    self.log_signal.emit("")
                    self.log_signal.emit("✅ 训练完成")
                    self.finished_signal.emit(True, "训练成功完成")
                elif exit_code == -9:  # SIGKILL
                    self.log_signal.emit("")
                    self.log_signal.emit("⚠️ 训练被强制终止")
                    self.finished_signal.emit(False, "训练被强制终止")
                else:
                    self.log_signal.emit("")
                    self.log_signal.emit(f"❌ 训练失败 (退出码: {exit_code})")
                    self.finished_signal.emit(False, f"训练失败 (退出码: {exit_code})")
            
            self.is_running = False
            
        except Exception as e:
            self.log_signal.emit(f"❌ 监控线程错误: {e}")
            self.finished_signal.emit(False, f"监控错误: {e}")
            self.is_running = False
    
    def is_process_alive(self):
        """检查进程是否仍在运行"""
        if self.process is None:
            return False
        
        return self.process.poll() is None


# Global instance
training_backend = TrainingBackend()
