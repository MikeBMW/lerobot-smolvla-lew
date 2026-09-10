#!/bin/bash
# 七模型训练完 → auto_finalize(rollout+PDF+飞书) → 自动重启 GUI 使修复生效 (2026-08-07)
# 触发条件: 最后一步 expert_policy 曲线出现 + 训练进程消失 + 缓冲 15 分钟
cd /home/xspace/lerobot-smolvla-lew
echo "[$(date +%H:%M)] 监控启动: 等七模型训练完成..."

# 1) 等 expert_policy 曲线 (7 模型最后一步, 最长 3 小时)
for i in $(seq 1 360); do
    if [ -f reports/train_curve_expert_policy.json ]; then
        echo "[$(date +%H:%M)] 官方专家基准完成 (最后一步)"
        break
    fi
    sleep 30
done

# 2) 等训练进程全部消失 (auto_finalize 开始)
for i in $(seq 1 60); do
    if ! pgrep -f 'lerobot_train|train_vla_touch|train_awe_zflow|distill_expert' > /dev/null; then
        echo "[$(date +%H:%M)] 训练进程已全部退出, auto_finalize 进行中"
        break
    fi
    sleep 30
done

# 3) 缓冲 15 分钟: rollout 5 模型 + 拼接 + PDF + 飞书发送
echo "[$(date +%H:%M)] 缓冲 15 分钟 (rollout+PDF+飞书)..."
sleep 900

# 4) 确认 GUI 还在 (auto_finalize 未崩) → 重启
if pgrep -f 'studio.py' > /dev/null; then
    echo "[$(date +%H:%M)] 重启 GUI (新代码: 撤销修复+DiT-B视觉线+七模型布局)..."
    pkill -f 'studio.py'
    sleep 4
    cd /home/xspace/lerobot-smolvla-lew/tools/gui
    ZMAX_AUTO_RUN=1 DISPLAY=:0 nohup bash run_studio.sh > /tmp/studio_autorestart.log 2>&1 &
    sleep 8
    pgrep -f 'studio.py' > /dev/null && echo "[$(date +%H:%M)] ✅ GUI 已重启 PID $(pgrep -f studio.py | head -1)" \
        || echo "[$(date +%H:%M)] ❌ GUI 重启失败, 看 /tmp/studio_autorestart.log"
else
    echo "[$(date +%H:%M)] ⚠️ GUI 已不在, 跳过重启"
fi
echo "[$(date +%H:%M)] 自动重启流程结束"
