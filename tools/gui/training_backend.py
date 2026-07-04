#!/usr/bin/env python3
"""
Z-MAX Training Backend Module
Responsible for actually calling lerobot training scripts and managing training processes

Features:
- Support for SmolVLA policy training
- Use downloaded HuggingFace datasets (e.g., PushT)
- Process management (start, pause, stop)
- Real-time capture of training logs
"""

import os
import subprocess
import signal
import json
from pathlib import Path
from typing import Optional, Callable


class TrainingBackend:
    """Training process backend manager"""
    
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
        batch_size: int = 8,
        total_steps: int = 500,
        learning_rate: float = 1e-4,
        output_dir: str = "outputs/smolvla_pusht",
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """
        Start SmolVLA policy training
        
        Args:
            repo_root: Path to the lerobot-smolvla-lew repository root directory
            dataset_repo_id: HuggingFace dataset ID
            batch_size: Training batch size
            total_steps: Total training steps
            learning_rate: Learning rate
            output_dir: Output directory (relative to repo_root)
            log_callback: Log output callback function
            progress_callback: Progress update callback function (0-100)
            
        Returns:
            Whether it started successfully
        """
        if self.is_running:
            if log_callback:
                log_callback("⚠️ Training is already running")
            return False
        
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        
        # Build training command
        train_script = os.path.join(repo_root, "src", "lerobot", "scripts", "lerobot_train.py")
        dataset_cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        full_output_dir = os.path.join(repo_root, output_dir)
        
        # Check if the training script exists
        if not os.path.exists(train_script):
            if log_callback:
                log_callback(f"❌ Training script not found: {train_script}")
            return False
        
        # Build command-line arguments
        cmd = [
            "python3.10",  # Use python3.10 (PyQt5 compatible version)
            train_script,
            f"--dataset.repo_id={dataset_repo_id}",
            f"--dataset.root={dataset_cache_dir}",
            f"--policy=smolvla",  # Use SmolVLA policy
            f"--dataset.batch_size={batch_size}",
            f"--training.steps={total_steps}",
            f"--optimizer.lr={learning_rate}",
            f"--output_dir={full_output_dir}",
            "--training.save_checkpoint=true",
            "--training.save_checkpoint_steps=100",
            "--training.log_steps=1",  # Log every step
        ]
        
        if log_callback:
            log_callback(f"🚀 Starting SmolVLA training...")
            log_callback(f"  Dataset: {dataset_repo_id}")
            log_callback(f"  Policy: smolvla")
            log_callback(f"  Batch Size: {batch_size}")
            log_callback(f"  Total Steps: {total_steps}")
            log_callback(f"  Learning Rate: {learning_rate}")
            log_callback(f"  Output: {output_dir}")
            log_callback(f"\nCommand: {' '.join(cmd[:5])}...")
        
        try:
            # Create output directory
            os.makedirs(full_output_dir, exist_ok=True)
            
            # Start training process
            self.process = subprocess.Popen(
                cmd,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid,  # Create a new process group for easy termination
            )
            
            self.is_running = True
            self.is_paused = False
            
            if log_callback:
                log_callback(f"✅ Training process started (PID: {self.process.pid})")
            
            # Start log monitoring thread
            self._monitor_output()
            
            return True
            
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Failed to start training: {str(e)}")
            return False
    
    def pause_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Pause training process (send SIGSTOP signal)"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ No running training process")
            return False
        
        if self.is_paused:
            if log_callback:
                log_callback("⚠️ Training is already paused")
            return False
        
        try:
            # Send SIGSTOP signal to pause the process
            os.killpg(os.getpgid(self.process.pid), signal.SIGSTOP)
            self.is_paused = True
            if log_callback:
                log_callback(f"⏸ Training paused (PID: {self.process.pid})")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Failed to pause training: {str(e)}")
            return False
    
    def resume_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Resume training process (send SIGCONT signal)"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ No running training process")
            return False
        
        if not self.is_paused:
            if log_callback:
                log_callback("⚠️ Training is not paused")
            return False
        
        try:
            # Send SIGCONT signal to resume the process
            os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)
            self.is_paused = False
            if log_callback:
                log_callback(f"▶ Training resumed (PID: {self.process.pid})")
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Failed to resume training: {str(e)}")
            return False
    
    def stop_training(self, log_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Stop training process (send SIGTERM signal, force SIGKILL after timeout)"""
        if not self.is_running or self.process is None:
            if log_callback:
                log_callback("⚠️ No running training process")
            return False
        
        try:
            if log_callback:
                log_callback(f"⏹ Stopping training (PID: {self.process.pid})...")
            
            # If paused, first resume
            if self.is_paused:
                os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)
            
            # Send SIGTERM signal (graceful termination)
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            
            # Wait up to 5 seconds
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # If a timeout occurs, forcibly terminate
                if log_callback:
                    log_callback("⚠️ Forcefully terminating process...")
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                self.process.wait()
            
            self.is_running = False
            self.is_paused = False
            self.process = None
            
            if log_callback:
                log_callback("✅ Training stopped")
            
            return True
            
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Failed to stop training: {str(e)}")
            return False
    
    def _monitor_output(self):
        """Monitor training process output (run in a new thread)"""
        import threading
        
        def reader():
            try:
                while self.is_running and self.process and self.process.stdout:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    
                    line = line.strip()
                    if line and self.log_callback:
                        # Send log to callback
                        self.log_callback(f"📊 {line}")
                        
                        # Try to parse progress
                        # lerobot logs typically contain: "Step X/Y" format
                        if "step" in line.lower() and "/" in line:
                            try:
                                # Parse formats like "Step 10/500"
                                import re
                                match = re.search(r'(\d+)\s*/\s*(\d+)', line)
                                if match:
                                    current = int(match.group(1))
                                    total = int(match.group(2))
                                    progress = int((current / total) * 100)
                                    if self.progress_callback:
                                        self.progress_callback(progress)
                            except:
                                pass
                
                # Check if the process has ended
                if self.process:
                    returncode = self.process.poll()
                    if returncode is not None:
                        if self.log_callback:
                            if returncode == 0:
                                self.log_callback(f"✅ Training completed (exit code: {returncode})")
                            else:
                                self.log_callback(f"⚠️ Training ended (exit code: {returncode})")
                    
                    self.is_running = False
                    if self.progress_callback:
                        self.progress_callback(100 if returncode == 0 else 0)
                        
            except Exception as e:
                if self.log_callback:
                    self.log_callback(f"❌ Log monitor error: {str(e)}")
        
        # Start the monitoring thread
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()


# Singleton instance
training_backend = TrainingBackend()
