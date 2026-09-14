#!/bin/bash
# 训练守护脚本模板 — 防"多会话互相杀训练" (2026-09-10/11 实证)
#
# 用法:
#   cp 本文件到 /tmp/<name>_daemon.sh, 按仓库实际情况改下面 4 个变量
#   systemd-run --user --unit=<name> --working-directory=<REPO> /bin/bash /tmp/<name>_daemon.sh
#   查: systemctl --user status <name>      停: systemctl --user stop <name>
#   ⚠️ 不要加 --collect (停止后 unit 会被清理, 再启动需重新 systemd-run)
#
# 效果:
#   · 独立于任何 Hermes/agent 会话 → 不会被别的会话误杀带上
#   · 被 SIGTERM 后 10s 自动重启, 最多 100 次
#   · 有 ckpt 自动续训, 无 ckpt 从头训 → 中断最多损失 save_freq 步
#
# 关键坑 (详见 SKILL.md ⑰):
#   · --resume=true 会在 **config 文件所在目录** 找 checkpoint → cfg 放 /tmp 会拼出
#     /tmp/model.safetensors 并报 FileNotFoundError。所以续训用「新 output_dir +
#     checkpoint_path 指向旧 ckpt + policy.pretrained_path 指向其 pretrained_model」,
#     而不是 --resume=true (本模板默认走这条路)。
#   · "Output directory ... already exists and resume is False" → 换新 output_dir。
#   · 必设 save_freq 小值 (500), 否则一崩全丢。

set -u
REPO="/home/ubuntu/lerobot-smolvla-lew"          # ← 改
CFG_FRESH="/tmp/v10_cfg.json"                    # ← 改: 从头训的 config
CFG_RESUME="/tmp/v10_r2_cfg.json"                # ← 改: 指向 ckpt 继续的 config
CKPT_DIR="outputs/train/smolvla_lew_v10/checkpoints"   # ← 改: 用于判断"有没有 ckpt 可续"
LOG="/tmp/smolvla_train_daemon.log"              # ← 改
GUI="gui-venv311/bin/python"                     # ← 改: 解释器路径

cd "$REPO" || exit 1
export PYTHONPATH="$REPO/src"
export HF_HUB_OFFLINE=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export MUJOCO_GL=egl

echo "[daemon] $(date +%F' '%T) 守护启动" >> "$LOG"
for i in $(seq 1 100); do
  if [ -d "$CKPT_DIR/last" ] && [ -f "$CFG_RESUME" ]; then
    echo "[daemon] $(date +%T) 发现 ckpt → 续训 (第 $i 次拉起)" >> "$LOG"
    "$GUI" -u -m lerobot.scripts.lerobot_train --config_path="$CFG_RESUME" >> "$LOG" 2>&1
  else
    echo "[daemon] $(date +%T) 无 ckpt → 从头训 (第 $i 次拉起)" >> "$LOG"
    "$GUI" -u -m lerobot.scripts.lerobot_train --config_path="$CFG_FRESH" >> "$LOG" 2>&1
  fi
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "[daemon] $(date +%T) 训练正常结束 → 守护退出" >> "$LOG"
    break
  fi
  echo "[daemon] $(date +%T) 退出 rc=$rc → 10s 后重启" >> "$LOG"
  sleep 10
done
