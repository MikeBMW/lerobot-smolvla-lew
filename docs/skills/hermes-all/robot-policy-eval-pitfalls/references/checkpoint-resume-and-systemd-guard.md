# 训练续训的配置坑 + 防"被并行会话杀掉"的守护式启动 (2026-09-10/11 实测)

> 本文补充 SKILL.md ⑩(SmolVLA-Lew 训练侧: 速度/显存/续训)。
> 起因: 同一天训练被 SIGTERM 杀了 **3 次** (并行会话为腾 GPU 主动杀), 每次都没落 ckpt → 白烧 40+ 分钟 GPU。

---

## 一、`--resume=true` 的正确用法 (两个实测坑)

### 坑 1: 配置放在 `/tmp` 时, `--resume=true` 会去 `/tmp` 找 checkpoint
```
FileNotFoundError: No such file or directory: '/tmp/model.safetensors'
```
框架按 **config 所在目录**解析 ckpt 相对路径 → config 在 `/tmp` 就找不到
`outputs/train/.../checkpoints/last` → 拼出 `/tmp/model.safetensors`。

### 坑 2: 预建 output_dir + `resume=false` 直接被拒
```
FileExistsError: Output directory outputs/train/<name> already exists and resume is False.
```

### ✅ 稳定可用的续训模式 (本仓库实测)
**不用 `--resume=true`**, 改用"从 ckpt 初始化 + 新 output_dir":

```python
cfg['resume'] = False
cfg['checkpoint_path'] = 'outputs/train/<old>/checkpoints/last'          # 老 ckpt (含 optimizer/rng/scheduler state)
cfg['policy']['pretrained_path'] = 'outputs/train/<old>/checkpoints/last/pretrained_model'
cfg['output_dir'] = 'outputs/train/<new>'                                 # 必须是不存在的新目录
cfg['save_freq'] = 500                                                    # 见下节
```
- `ckpt/last/training_state/` 里必须有 `optimizer_state.safetensors` / `rng_state.safetensors` /
  `scheduler_state.json` / `training_step.json` (先 `ls` 确认, 缺了只能当"权重初始化")。
- 续训**必须重设 lr schedule** (见 SKILL.md ⑩: 从 30500 续训而 scheduler 只到 31000 → lr 掉到峰值的 1/40)。

---

## 二、`save_freq` 是保命参数, 不是性能参数
被杀时若没落过 ckpt, **全部进度蒸发**。本会话两次损失 (840 步 / 220 步) 都因为默认 save_freq 太大。
⇒ **长训练一律显式设小** (`save_freq=500`), 最多丢 500 步。

---

## 三、防杀: systemd --user 守护 (脱离任何 Hermes 会话)

并行会话互杀 (各自 `pkill`/腾 GPU) 时, 普通 `terminal(background=true)` 进程**挡不住**。
正解 = systemd 用户级 transient unit + **守护循环** (被杀自动重启 + 有 ckpt 自动续训):

```bash
systemd-run --user --unit=<job> --working-directory=<repo> /bin/bash /tmp/run_<job>_daemon.sh
# 查: systemctl --user status <job>      停: systemctl --user stop <job>
```
守护脚本骨架 (完整模板见本技能 `templates/training_daemon.sh`):
```bash
for i in $(seq 1 100); do
  if [ -d "$OUT/checkpoints/last" ] && [ -f "$RESUME_CFG" ]; then
      "$GUI" -u -m lerobot.scripts.lerobot_train --config_path="$RESUME_CFG" >> "$LOG" 2>&1
  else
      "$GUI" -u -m lerobot.scripts.lerobot_train --config_path=/tmp/<base>_cfg.json >> "$LOG" 2>&1
  fi
  rc=$?; [ $rc -eq 0 ] && break
  echo "[daemon] $(date +%T) 异常退出 rc=$rc → 10s 后重启" >> "$LOG"; sleep 10
done
```

**坑**: `systemd-run --collect` 会在 unit 停止后**清理掉它** → 之后 `systemctl --user start <job>` 报
`Unit <job>.service not found`。要可反复启停就别加 `--collect`, 或每次重新 `systemd-run`。

---

## 四、多会话抢同一张卡的判据与协调
- **占用判据**: `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`
  → 再 `ps -o pid,etime,args -p <pid>` 看是谁(哪个 config/脚本)。
- 实测: 两个训练并存 → 显存 7416/8188 MiB ≈ **91%** (危险), 各自变慢 (4.5 → 6.15 s/step)。
- **"提速"错觉 (真实数据反驳)**: batch 8→1 时 step/s 快 7.9×, 但每步样本数也 ÷8 ⇒
  **吞吐完全一样** (都 ≈7 样本/秒), 而总训练量 ÷16 (8000×32 vs 4000×4 样本 = 1.95 vs 0.12 epoch)
  ⇒ 训出的模型照妖镜相关性 **0.032**, 比 batch=1 的老模型 (0.182) 还差 6 倍。
  **口径: 报"快了多少倍"必须同时给 `样本/秒` 与 `总样本数(= 步数 × 有效 batch)`。**
- 协调原则: 同时只留一个训练; 用 systemd 守护的那个不要被别人 `pkill` 掉。
