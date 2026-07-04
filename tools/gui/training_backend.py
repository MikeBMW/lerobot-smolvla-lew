"""
Z-MAX 训练后端模块
负责调用 lerobot-train CLI 启动训练进程
"""

import os
import subprocess
import signal
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QThread


class TrainingOutputReader(QThread):
    """在独立线程中读取训练进程的输出"""
    line_received = pyqtSignal(str)
    process_finished = pyqtSignal(int)

    def __init__(self, process):
        super().__init__()
        self.process = process

    def run(self):
        try:
            for line in self.process.stdout:  # 读取 stdout（stderr 已合并到这里）
                text = line.rstrip()
                if text:
                    self.line_received.emit(text)
            self.process.wait()
            self.process_finished.emit(self.process.returncode)
        except Exception as e:
            self.line_received.emit(f"[输出读取错误] {e}")


class TrainingBackend(QObject):
    """
    训练后端：通过 lerobot-train CLI 启动和管理训练进程
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.reader_thread = None

    def get_repo_root(self):
        """获取仓库根目录：tools/gui/studio.py → tools/gui → tools → repo_root"""
        gui_dir = os.path.dirname(os.path.abspath(__file__))  # tools/gui/
        tools_dir = os.path.dirname(gui_dir)                    # tools/
        repo_root = os.path.dirname(tools_dir)                  # repo_root
        return repo_root

    def start_smolvla_training(self, repo_root, 
                                 # Policy settings
                                 policy_type="smolvla_lew",
                                 freeze_smolvlm=True,
                                 enable_lew_world_model=False,
                                 repeated_diffusion_steps=5,
                                 # Dataset settings
                                 dataset_repo_id="lerobot/pusht",
                                 # Training settings
                                 batch_size=8, 
                                 total_steps=500,
                                 checkpoint_interval=1000,
                                 # Optimizer settings
                                 learning_rate=0.0001,
                                 weight_decay=0.000001,
                                 grad_clip_norm=10.0,
                                 # Scheduler settings
                                 scheduler_type="cosine_decay_with_warmup",
                                 num_warmup_steps=500,
                                 num_decay_steps=500,
                                 peak_lr=0.0001,
                                 decay_lr=0.000001,
                                 # Experiment settings
                                 output_dir="outputs/smolvla_pusht",
                                 eval_freq=500,
                                 push_to_hub=False,
                                 # Callbacks
                                 log_callback=None, 
                                 progress_callback=None):
        """
        启动 SmolVLA 训练
        使用 lerobot-train CLI，参数格式与用户命令行一致
        """
        if self.process and self.process.poll() is None:
            if log_callback:
                log_callback("[警告] 训练已在运行中")
            return False

        # 查找 lerobot-train 命令
        lerobot_train = self._find_lerobot_train(repo_root)
        if not lerobot_train:
            if log_callback:
                log_callback("[错误] 找不到 lerobot-train 命令")
                log_callback("  请确保已安装 lerobot: pip install -e .")
            return False

        # 构建命令（与用户实际使用的命令格式一致）
        cmd = [
            lerobot_train,
            "--policy.type", policy_type,
            "--policy.freeze_smolvlm", str(freeze_smolvlm).lower(),
            "--policy.enable_lew_world_model", str(enable_lew_world_model).lower(),
            "--policy.repeated_diffusion_steps", str(repeated_diffusion_steps),
            "--policy.push_to_hub", str(push_to_hub).lower(),
            "--dataset.repo_id", dataset_repo_id,
            "--steps", str(total_steps),
            "--batch_size", str(batch_size),
            "--eval_freq", str(eval_freq),
            "--save_freq", str(checkpoint_interval),
            "--optimizer.lr", str(learning_rate),
            "--optimizer.weight_decay", str(weight_decay),
            "--optimizer.grad_clip_norm", str(grad_clip_norm),
            "--scheduler.type", scheduler_type,
            "--scheduler.num_warmup_steps", str(num_warmup_steps),
            "--scheduler.num_decay_steps", str(num_decay_steps),
            "--scheduler.peak_lr", str(peak_lr),
            "--scheduler.decay_lr", str(decay_lr),
            "--wandb.enable", "false",
        ]

        if log_callback:
            full_cmd = ' '.join(cmd)
            log_callback(f"[{now()}] 🚀 启动训练进程")
            log_callback(f"[{now()}] 完整命令:\n  {full_cmd}")
            log_callback(f"[{now()}] 工作目录: {repo_root}")

        # 启动子进程
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"  # 确保输出不缓冲

            self.process = subprocess.Popen(
                cmd,
                cwd=repo_root,
                stdout=subprocess.PIPE,    # 正确：stdout 写入 pipe
                stderr=subprocess.STDOUT, # 正确：stderr 合并到 stdout
                text=True,
                bufsize=1,               # 行缓冲
                env=env,
                start_new_session=True,   # 替代 preexec_fn=os.setsid，更安全
            )

            # 启动输出读取线程
            self.reader_thread = TrainingOutputReader(self.process)
            self.reader_thread.line_received.connect(
                lambda line: log_callback(f"[{now()}] {line}") if log_callback else None
            )
            self.reader_thread.process_finished.connect(
                lambda code: self._on_process_finished(code, log_callback, progress_callback)
            )
            self.reader_thread.start()

            if log_callback:
                log_callback(f"[{now()}] 训练已启动 (PID: {self.process.pid})")
            return True

        except Exception as e:
            if log_callback:
                log_callback(f"[{now()}] 启动失败: {e}")
            return False

    def pause_training(self, log_callback=None):
        """暂停训练（发送 SIGSTOP）"""
        if not self.process or self.process.poll() is not None:
            if log_callback:
                log_callback("[警告] 没有正在运行的训练")
            return False
        try:
            if hasattr(os, 'killpg'):
                os.killpg(os.getpgid(self.process.pid), signal.SIGSTOP)
            else:
                os.kill(self.process.pid, signal.SIGSTOP)
            if log_callback:
                log_callback(f"[{now()}] 训练已暂停")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"[{now()}] 暂停失败: {e}")
            return False

    def resume_training(self, log_callback=None):
        """恢复训练（发送 SIGCONT）"""
        if not self.process or self.process.poll() is not None:
            if log_callback:
                log_callback("[警告] 没有正在运行的训练")
            return False
        try:
            if hasattr(os, 'killpg'):
                os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)
            else:
                os.kill(self.process.pid, signal.SIGCONT)
            if log_callback:
                log_callback(f"[{now()}] 训练已恢复")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"[{now()}] 恢复失败: {e}")
            return False

    def stop_training(self, log_callback=None):
        """停止训练（发送 SIGTERM，超时后 SIGKILL）"""
        if not self.process or self.process.poll() is not None:
            if log_callback:
                log_callback("[警告] 没有正在运行的训练")
            return False
        try:
            if log_callback:
                log_callback(f"[{now()}] 正在停止训练 (PID: {self.process.pid})...")
            # 终止整个进程组
            if hasattr(os, 'killpg'):
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:
                self.process.terminate()

            # 等待最多 5 秒
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if log_callback:
                    log_callback(f"[{now()}] 强制终止...")
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait()

            if log_callback:
                log_callback(f"[{now()}] 训练已停止")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"[{now()}] 停止失败: {e}")
            return False

    def _find_lerobot_train(self, repo_root):
        """查找 lerobot-train 可执行命令"""
        # 1. 检查 conda 环境中的 lerobot-train
        for name in ['lerobot-train', 'lerobot_train']:
            path = self._which(name)
            if path:
                return path

        # 2. 检查仓库内的 scripts
        script_path = os.path.join(repo_root, "src", "lerobot", "scripts", "lerobot_train.py")
        if os.path.exists(script_path):
            return f"python {script_path}"

        return None

    def _which(self, name):
        """类似 shell 的 which 命令"""
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            full_path = os.path.join(path_dir, name)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                return full_path
        return None

    def _on_process_finished(self, exit_code, log_callback, progress_callback):
        """训练进程结束回调"""
        if log_callback:
            if exit_code == 0:
                log_callback(f"[{now()}] 训练完成 (exit code: {exit_code})")
            elif exit_code < 0:
                log_callback(f"[{now()}] 训练被信号终止 (signal: {-exit_code})")
            else:
                log_callback(f"[{now()}] 训练异常退出 (exit code: {exit_code})")
        if progress_callback:
            progress_callback(100 if exit_code == 0 else 0)

    def is_process_running(self):
        """返回进程是否在运行"""
        if self.process is None:
            return False
        return self.process.poll() is None


def now():
    return datetime.now().strftime("%H:%M:%S")


# 全局单例
training_backend = TrainingBackend()
