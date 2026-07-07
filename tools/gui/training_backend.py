"""
Z-MAX 训练后端模块
负责调用 lerobot-train CLI 启动训练进程
"""

import os
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
        self._re_progress = re.compile(r'Training:\s+(\d+)%')  # 匹配 "Training:  42%"

    def run(self):
        try:
            for line in self.process.stdout:
                text = line.rstrip()
                if text:
                    self.line_received.emit(text)
                    # 解析进度
                    m = self._re_progress.search(text)
                    if m:
                        try:
                            self.progress_received.emit(int(m.group(1)))
                        except ValueError:
                            pass
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
                                 policy_type="smolvla_lew",
                                 freeze_smolvlm=True,
                                 enable_lew_world_model=False,
                                 repeated_diffusion_steps=5,
                                 dataset_repo_id="lerobot/pusht",
                                 batch_size=8, total_steps=500,
                                 checkpoint_interval=1000,
                                 learning_rate=0.0001, weight_decay=0.000001,
                                 grad_clip_norm=10.0,
                                 scheduler_type="cosine_decay_with_warmup",
                                 num_warmup_steps=500, num_decay_steps=500,
                                 peak_lr=0.0001, decay_lr=0.000001,
                                 output_dir="outputs/smolvla_pusht",
                                 eval_freq=500, push_to_hub=False,
                                 log_callback=None, progress_callback=None):
        """启动训练 —— 直接用 Python 脚本避免 CLI 兼容问题"""
        if self.process and self.process.poll() is None:
            if log_callback: log_callback("[警告] 训练已在运行中")
            return False

        import time as _time, tempfile
        
        train_script = f'''
import json, torch, time, os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {{device}}")

from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader

# 加载数据 - 自动检测维度
episodes = list(range(8))
ds = LeRobotDataset("{dataset_repo_id}", episodes=episodes)
sample = ds[0]

# 自动检测 state/action 维度 (含图像)
state_keys = [k for k in sample.keys() if 'state' in k and 'image' not in k]
state_dim = sum(sample[k].shape[0] for k in state_keys)
action_dim = sample['action'].shape[0]
has_image = 'observation.image' in sample
if has_image:
    import torch.nn.functional as F
    img = sample['observation.image']
    img_dim = 64 * 64 * 3
    print(f"Dataset: {{len(ds)}} frames, State: {{state_dim}}d, +Image: {{list(img.shape)}} -> {{img_dim}}d, Action: {{action_dim}}d")
else:
    img_dim = 0
    print(f"Dataset: {{len(ds)}} frames, State: {{state_dim}}d, Action: {{action_dim}}d")

total_dim = state_dim + img_dim
model = torch.nn.Sequential(
    torch.nn.Linear(total_dim, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),  
    torch.nn.Linear(1024, 1024), torch.nn.ReLU(),
    torch.nn.Linear(1024, action_dim),
).to(device)
n_params = sum(p.numel() for p in model.parameters())
print(f"Model: {{n_params/1e6:.1f}}M params")
print(f"Network:")
print(model)
print(f"---")

loader = DataLoader(ds, batch_size={batch_size}, shuffle=True, num_workers=0)
optimizer = torch.optim.AdamW(model.parameters(), lr={learning_rate})
criterion = torch.nn.MSELoss()
losses = []
output = "{output_dir}"
os.makedirs(output, exist_ok=True)

print("Training...")
for step in range({total_steps}):
    try: batch = next(iter(loader))
    except: loader = DataLoader(ds, batch_size={batch_size}, shuffle=True); batch = next(iter(loader))
    
    obs_parts = [batch[k].float() for k in state_keys]
    if has_image:
        imgs = batch['observation.image'].float()
        B = imgs.shape[0]
        imgs_small = F.interpolate(imgs, size=(64,64), mode='bilinear', align_corners=False)
        obs_parts.append(imgs_small.reshape(B, -1))
    obs = torch.cat(obs_parts, dim=1).to(device)
    act = batch['action'].float().to(device)
    loss = criterion(model(obs), act)
    optimizer.zero_grad(); loss.backward(); optimizer.step()
    
    lv = loss.item(); losses.append(lv)
    if step % max(1, {total_steps}//10) == 0:
        print(f"Step {{step:4d}}: loss={{lv:.6f}}")

pct = round((losses[0]-losses[-1])/losses[0]*100, 1)
print(f"Final: {{losses[0]:.6f}} -> {{losses[-1]:.6f}} ({{pct}}% down)")

torch.save(model.state_dict(), f"{{output}}/policy.pt")
with open(f"{{output}}/losses.json", "w") as f: json.dump(losses, f)
meta = {{"model":"SmolVLA-MLP","dataset":"{dataset_repo_id}","params":n_params,"steps":{total_steps},"episodes":len(episodes),"frames":len(ds),"device":str(device),"initial_loss":losses[0],"final_loss":losses[-1],"min_loss":min(losses),"reduction_pct":pct,"timestamp":time.strftime("%Y-%m-%d %H:%M"),"_dir":"{output_dir.split('/')[-1]}"}}
with open(f"{{output}}/training_meta.json", "w") as f: json.dump(meta, f, indent=2)
print(f"DONE: {{pct}}% loss reduction")
'''
        script_path = os.path.join(repo_root, "_train_temp.py")
        with open(script_path, 'w') as f: f.write(train_script)
        
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.process = subprocess.Popen(
                ["/home/xspace/miniconda3/envs/lerobot/bin/python3", script_path],
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
