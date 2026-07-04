#!/usr/bin/env python3
"""
Z-MAX 训练后端模块
负责调用实际的 lerobot 训练脚本并管理训练进程

功能：
- 支持 SmolVLA / smolvla_lew policy 训练
- 使用下载的 HuggingFace 数据集（如 PushT）
- 进程管理（启动、暂停、停止）
- 实时捕获训练日志
"""

import os
import subprocess
import signal
import threading
from typing import Optional, Callable, Dict


class TrainingBackend:
    """训练进程后端管理器"""
    
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.is_paused = False
        self.log_callback: Optional[Callable[[str], None]] = None
        self.progress_callback: Optional[Callable[[int], None]] = None
        
    def start_smolvla_training(
        self,
        repo_root: str,
        dataset_repo_id: str = "lerobot/pusht",
        batch_size: int = 16,
        total_steps: int = 5000,
        learning_rate: float = 1e-4,
        output_dir: str = "outputs/smolvla_pusht",
        checkpoint_interval: int = 1000,
        eval_freq: int = 500,
        freeze_smolvlm: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """
        启动 SmolVLA 训练
        
        使用 lerobot-train CLI，与用户实际使用的命令一致：
        lerobot-train --policy.type smolvla_lew --dataset.repo_id lerobot/pusht ...
        
        Args:
            repo_root: lerobot 仓库根目录路径
            dataset_repo_id: HuggingFace 数据集 ID
            batch_size: 训练批次大小
            total_steps: 总训练步数
            learning_rate: 学习率
            output_dir: 输出目录
            checkpoint_interval: checkpoint 保存间隔
            eval_freq: 评估频率
            freeze_smolvlm: 是否冻结 SmolVLM
            log_callback: 日志输出回调函数
            progress_callback: 进度更新回调函数 (0-100)
            
        Returns:
            是否成功启动
        """
        if self.is_running:
            if log_callback:
                log_callback("⚠️ 训练已在运行中")
            return False
        
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        
        # 构建训练命令 - 使用 lerobot-train CLI
        cmd = [
            "lerobot-train",
            "--policy.type", "smolvla_lew",
            f"--policy.freeze_smolvlm", str(freeze_smolvlm).lower(),
            "--policy.enable_lew_world_model", "false",
            "--policy.repeated_diffusion_steps", "5",
            "--policy.push_to_hub", "false",
            f"--dataset.repo_id", dataset_repo_id,
            f"--steps", str(total_steps),
            f"--batch_size", str(batch_size),
            f"--eval_freq", str(eval_freq),
            f"--save_freq", str(checkpoint_interval),
            f"--optimizer.lr", str(learning_rate),
            "--optimizer.weight_decay", "1e-6",
            "--scheduler.type", "cosine_decay_with_warmup",
            "--scheduler.num_warmup_steps", "500",
            f"--scheduler.num_decay_steps", str(total_steps),
            f"--scheduler.peak_lr", str(learning_rate),
            "--scheduler.decay_lr", "1e-6",
            "--wandb.enable", "false",
        ]
        
        if log_callback:
            log_callback(f"🚀 启动 SmolVLA 训练...")
            log_callback(f"  命令: {' '.join(cmd[:6])} ...")
            log_callback(f"  数据集: {dataset_repo_id}")
            log_callback(f"  批次大小: {batch_size}")
            log_callback(f"  总步数: {total_steps}")
            log_callback(f"  学习率: {learning_rate}")
            log_callback(f"  输出目录: {output_dir}")
            log_callback("")
        
        try:
            # 启动训练进程
            self.process = subprocess.Popen(
                cmd,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
            
            self.is_running = True
            self.is_paused = False
            
            if log_callback:
                log_callback(f"✅ 训练进程已启动 (PID: {self.process.pid})")
            
            # 启动日志捕获线程
            self._start_log_capture(total_steps)
            
            return True
            
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 启动训练失败: {e}")
            return False
    
    def pause_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """暂停训练进程"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ 没有正在运行的训练")
            return False
        
        if self.is_paused:
            if log_callback:
                log_callback("⚠️ 训练已经暂停")
            return False
        
        try:
            if os.name != 'nt':
                os.killpg(os.getpgid(self.process.pid), signal.SIGSTOP)
            else:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            self.is_paused = True
            if log_callback:
                log_callback("⏸ 训练已暂停")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 暂停失败: {e}")
            return False
    
    def resume_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """恢复训练进程"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ 没有正在运行的训练")
            return False
        
        if not self.is_paused:
            if log_callback:
                log_callback("⚠️ 训练未暂停")
            return False
        
        try:
            if os.name != 'nt':
                os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)
            else:
                self.process.send_signal(signal.CTRL_C_EVENT)
            self.is_paused = False
            if log_callback:
                log_callback("▶ 训练已恢复")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 恢复失败: {e}")
            return False
    
    def stop_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """停止训练进程"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ 没有正在运行的训练")
            return False
        
        try:
            if log_callback:
                log_callback(f"⏹ 停止训练 (PID: {self.process.pid})...")
            
            # 如果已暂停，先恢复
            if self.is_paused:
                if os.name != 'nt':
                    os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)
                else:
                    self.process.send_signal(signal.CTRL_C_EVENT)
                self.is_paused = False
            
            # 发送终止信号
            if os.name != 'nt':
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:
                self.process.terminate()
            
            # 等待进程结束
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if log_callback:
                    log_callback("⚠️ 进程未响应，强制终止...")
                if os.name != 'nt':
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait()
            
            self.is_running = False
            self.is_paused = False
            self.process = None
            
            if log_callback:
                log_callback("✅ 训练已停止")
            return True
            
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 停止失败: {e}")
            return False
    
    def _start_log_capture(self, total_steps: int):
        """启动日志捕获线程"""
        def capture_logs():
            try:
                while self.is_running and self.process and self.process.stdout:
                    line = self.process.stdout.readline()
                    if not line:
                        if self.process.poll() is not None:
                            break
                        continue
                    
                    line = line.rstrip()
                    if not line:
                        continue
                    
                    # 发送给日志回调
                    if self.log_callback:
                        self.log_callback(line)
                    
                    # 解析进度信息
                    # 格式: "Training:   0%|          | 0/5000 [00:00<00:00, 0.00step/s]"
                    if "Training:" in line and "/" in line and "[" in line:
                        try:
                            # 提取进度数字
                            import re
                            match = re.search(r'(\d+)/(\d+)', line)
                            if match:
                                current = int(match.group(1))
                                total = int(match.group(2))
                                progress = int((current / total) * 100)
                                if self.progress_callback:
                                    self.progress_callback(progress)
                        except Exception:
                            pass
                    
                    # 检测训练完成
                    if "Training complete" in line or "训练完成" in line:
                        if self.progress_callback:
                            self.progress_callback(100)
                
                # 进程结束
                self.is_running = False
                if self.process:
                    exit_code = self.process.poll()
                    if self.log_callback:
                        if exit_code == 0:
                            self.log_callback("✅ 训练完成")
                        elif exit_code == -signal.SIGTERM:
                            self.log_callback("⏹ 训练被用户停止")
                        else:
                            self.log_callback(f"⚠️ 训练进程退出 (exit code: {exit_code})")
            except Exception as e:
                if self.log_callback:
                    self.log_callback(f"❌ 日志捕获错误: {e}")
                self.is_running = False
        
        thread = threading.Thread(target=capture_logs, daemon=True)
        thread.start()


# 全局单例
training_backend = TrainingBackend()
