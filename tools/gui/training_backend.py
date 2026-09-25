"""
Z-MAX 训练后端模块
负责调用 lerobot-train CLI 启动训练进程
"""

import os
import sys
import re
import subprocess
import signal
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QThread


class TrainingOutputReader(QThread):
    """在独立线程中读取训练进程的输出，并解析进度"""
    line_received = pyqtSignal(str)
    progress_received = pyqtSignal(int)  # 新增：进度信号 (0-100)
    process_finished = pyqtSignal(int)

    def __init__(self, process):
        super().__init__()
        self.process = process
        # ⚠️ 2026-09-25 修: 原正则 r'Training:\s+(\d+)%' 与训练脚本实际输出
        #    ('Step N: loss=…' / 'Final: …' / 'DONE: x%') **完全不匹配**
        #    → 进度条永远 0% = 假进度 (老倪: "进度条是真的")
        #    现兼容三种: ① Training: 42%  ② Step 42/100  ③ 预训练 epoch 42/100
        self._re_progress = re.compile(
            r'Training:\s*(\d+(?:\.\d+)?)%'
            r'|Step\s+(\d+)\s*/\s*(\d+)'
            r'|epoch\s*(\d+)\s*/\s*(\d+)',
            re.I)
        self._last_pct = -1

    def run(self):
        try:
            for line in self.process.stdout:
                text = line.rstrip()
                if text:
                    self.line_received.emit(text)
                    # 解析进度 (三种格式, 见 __init__ 注释)
                    m = self._re_progress.search(text)
                    if m:
                        pct = None
                        try:
                            if m.group(1) is not None:            # Training: 42%
                                pct = float(m.group(1))
                            elif m.group(2) is not None:          # Step 42/100
                                a, b = int(m.group(2)), int(m.group(3) or 0)
                                pct = (a / b * 100) if b > 0 else None
                            elif m.group(4) is not None:          # epoch 42/100
                                a, b = int(m.group(4)), int(m.group(5) or 0)
                                pct = (a / b * 100) if b > 0 else None
                        except (ValueError, ZeroDivisionError):
                            pct = None
                        if pct is not None:
                            pv = int(max(0, min(100, pct)))
                            if pv != self._last_pct:               # 去重: 同值不重复发
                                self._last_pct = pv
                                self.progress_received.emit(pv)
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
        """获取仓库根目录 (frozen exe → PyInstaller _MEIPASS; 源码 → tools/gui → tools → repo_root)"""
        if getattr(sys, "frozen", False):
            return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        gui_dir = os.path.dirname(os.path.abspath(__file__))  # tools/gui/
        tools_dir = os.path.dirname(gui_dir)                    # tools/
        repo_root = os.path.dirname(tools_dir)                  # repo_root
        return repo_root

    def resolve_python(self, repo_root=None) -> str:
        """跨平台解析训练用解释器 (老倪 2026-09-25「训练要保证是真实模型训练」)

        ⚠️ 原代码写死 "/home/xspace/miniconda3/envs/lerobot/bin/python3" ——
           只在静安的 WSL2 上存在, Mac / Windows 打包版一律
           FileNotFoundError → 训练从未真正启动 (日志只有"❌ Failed to start")

        解析顺序:
          ZMAX_TRAIN_PYTHON 环境变量
          → <repo>/.venv/bin/python            (Mac/Linux 标准 venv)
          → <repo>/gui-venv311/bin/python      (Windows 分支)
          → <repo>/.venv/Scripts/python.exe    (Windows venv)
          → shutil.which("python3"/"python")
          → sys.executable                     (兜底)
        """
        import shutil
        root = repo_root or self.get_repo_root()
        cands = [
            os.environ.get("ZMAX_TRAIN_PYTHON"),
            os.path.join(root, ".venv", "bin", "python"),
            os.path.join(root, "gui-venv311", "bin", "python"),
            os.path.join(root, ".venv", "Scripts", "python.exe"),
            os.path.join(root, "gui-venv311", "Scripts", "python.exe"),
            shutil.which("python3"),
            shutil.which("python"),
            sys.executable,
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
        return sys.executable

    def start_real_training(self, task="manifold", repo_root=None,
                            steps=220, epochs=30, batch=4,
                            clean=14, jitter=4, run_name="zmax_app_train",
                            config="", log_callback=None, progress_callback=None):
        """**真实模型训练**入口 (老倪令: 「训练控制节点 app 的训练要保证是真实模型训练」)

        经 tools/gui/train_runner.py 执行真训练链:
          manifold  流形引擎 (训练总目标) — 真仿真采集 + 真反向传播 + 真 LOSO R²
          yolo      L2 YOLO 域适应微调 (需真机标注数据)
          smolvla   L3 SmolVLA (lerobot 原生训练)
          demo      小规模**真跑**冒烟

        进度来源: 训练进程真实输出 (Training: N% / ZMAX_METRIC / ZMAX_RESULT),
                 不是定时器假走 —— 进程停了进度就停。
        """
        root = repo_root or self.get_repo_root()
        if self.process and self.process.poll() is None:
            if log_callback:
                log_callback("[警告] 训练已在运行中")
            return False
        runner = os.path.join(root, "tools", "gui", "train_runner.py")
        if not os.path.exists(runner):
            if log_callback:
                log_callback(f"❌ 缺真训练执行器: {runner}")
            return False
        py = self.resolve_python(root)
        cmd = [py, runner, "--task", str(task), "--workdir", root,
               "--steps", str(steps), "--epochs", str(epochs), "--batch", str(batch),
               "--clean", str(clean), "--jitter", str(jitter), "--run-name", str(run_name)]
        if config:
            cmd += ["--config", str(config)]
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env.setdefault("MUJOCO_GL", "glfw")      # Mac 必须 glfw (非 egl)
            env.setdefault("OMP_NUM_THREADS", "4")
            if log_callback:
                log_callback(f"🚀 真训练启动: task={task} · 解释器={py}")
                log_callback(f"   $ {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env, start_new_session=True)
            self.reader_thread = TrainingOutputReader(self.process)
            if log_callback:
                self.reader_thread.line_received.connect(
                    lambda line: log_callback(f"[{now()}] {line}"))
            if progress_callback:
                self.reader_thread.progress_received.connect(progress_callback)
            self.reader_thread.start()
            return True
        except Exception as e:
            if log_callback:
                log_callback(f"❌ 真训练启动失败: {type(e).__name__}: {e}")
            return False

    def start_smolvla_training(self, repo_root, 
                                 dataset_repo_id="lerobot/pusht",
                                 output_dir="outputs/smolvla_pusht",
                                 **params):
        """Start SmolVLA training with all configuration parameters from GUI"""
        # Extract callbacks first
        log_callback = params.pop("log_callback", None)
        progress_callback = params.pop("progress_callback", None)

        if self.process and self.process.poll() is None:
            if log_callback: log_callback("[警告] 训练已在运行中")
            return False

        # Extract params with defaults matching SmolVLAConfig
        freeze_smolvlm = params.get("freeze_smolvlm", True)
        n_obs_steps = params.get("n_obs_steps", 1)
        chunk_size = params.get("chunk_size", 50)
        max_state_dim = params.get("max_state_dim", 32)
        max_action_dim = params.get("max_action_dim", 32)
        batch_size = params.get("batch_size", 1)
        total_steps = params.get("total_steps", 500)
        learning_rate = params.get("learning_rate", 0.0001)
        weight_decay = params.get("weight_decay", 1e-10)
        grad_clip_norm = params.get("grad_clip_norm", 10.0)
        repeated_diffusion_steps = params.get("repeated_diffusion_steps", 5)
        num_vlm_layers = params.get("num_vlm_layers", 16)

        import time as _time
        
        train_script = f"""
import json, torch, time, os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {{device}}")

from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

print("Loading SmolVLA base (Flow Matching)...")
policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
policy.to(device)

for name, param in policy.named_parameters():
    if "smolvlm" in name or "vlm" in name.lower():
        param.requires_grad = False

trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
total = sum(p.numel() for p in policy.parameters())
print(f"SmolVLA: {{total/1e6:.0f}}M total, {{trainable/1e6:.0f}}M trainable (VLM frozen)")

episodes = list(range(3))
ds = LeRobotDataset("{dataset_repo_id}", episodes=episodes)
print(f"Dataset: {{len(ds)}} frames, {{ds.num_episodes}} episodes")

loader = DataLoader(ds, batch_size=1, shuffle=True, num_workers=0)
optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, policy.parameters()), lr={learning_rate})
losses = []
output = "{output_dir}"
os.makedirs(output, exist_ok=True)

print("Training (SmolVLA Flow Matching, batch=1)...")
policy.train()
for step in range({total_steps}):
    try: batch = next(iter(loader))
    except: loader = DataLoader(ds, batch_size=1, shuffle=True); batch = next(iter(loader))
    batch = {{k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}}
    loss = policy.forward(batch)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    lv = loss.item(); losses.append(lv)
    if step % max(1, {total_steps}//10) == 0:
        print(f"Step {{step:4d}}: loss={{lv:.6f}}")

pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
print(f"Final: {{losses[0]:.6f}} -> {{losses[-1]:.6f}} ({{pct}}% down)")

torch.save(policy.state_dict(), f"{{output}}/policy.pt")
with open(f"{{output}}/losses.json", "w") as f: json.dump(losses, f)
meta = {{"model":"SmolVLA-FlowMatching","dataset":"{dataset_repo_id}","params":int(trainable),"total_params":int(total),"steps":{total_steps},"episodes":len(episodes),"frames":len(ds),"device":str(device),"initial_loss":losses[0],"final_loss":losses[-1],"min_loss":min(losses),"reduction_pct":pct,"timestamp":time.strftime("%Y-%m-%d %H:%M"),"_dir":"{output_dir.split('/')[-1]}"}}
with open(f"{{output}}/training_meta.json", "w") as f: json.dump(meta, f, indent=2)
print(f"DONE: {{pct}}% loss (SmolVLA原生Flow Matching)")
"""
        script_path = os.path.join(repo_root, "experiments", "train", "_train_temp.py")
        with open(script_path, 'w') as f: f.write(train_script)
        
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            # ⚠️ 2026-09-25 修: 原写死 "/home/xspace/miniconda3/envs/lerobot/bin/python3"
            #    (只在静安 WSL2 存在) → Mac/Win 打包版必然 FileNotFoundError
            _py = self.resolve_python(repo_root)
            if log_callback:
                log_callback(f"训练解释器: {_py}")
            self.process = subprocess.Popen(
                [_py, script_path],
                cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env, start_new_session=True
            )
            self.reader_thread = TrainingOutputReader(self.process)
            if log_callback:
                self.reader_thread.line_received.connect(lambda line: log_callback(f"[{now()}] {line}"))
            if progress_callback:
                self.reader_thread.progress_received.connect(progress_callback)
            self.reader_thread.start()
            return True
        except Exception as e:
            if log_callback: log_callback(f"启动失败: {e}")
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
        """查找 lerobot-train 可执行命令，优先 conda lerobot 环境"""
        # 1. 优先检查 conda lerobot 环境
        conda_bin = os.path.expanduser("~/miniconda3/envs/lerobot/bin")
        for name in ['lerobot-train', 'lerobot_train']:
            path = os.path.join(conda_bin, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        # 2. 检查 PATH 中的 lerobot-train
        for name in ['lerobot-train', 'lerobot_train']:
            path = self._which(name)
            if path:
                return path

        # 3. 使用当前 Python 解释器运行仓库脚本
        script_path = os.path.join(repo_root, "src", "lerobot", "scripts", "lerobot_train.py")
        if os.path.exists(script_path):
            import sys
            return f"{sys.executable} {script_path}"

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
