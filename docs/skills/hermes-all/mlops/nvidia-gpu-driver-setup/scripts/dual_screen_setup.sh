#!/bin/bash
# 双显卡笔记本 (Intel iGPU + NVIDIA dGPU) 外接屏: 诊断 + reverse PRIME 点亮 (X11)
# 用法: bash dual_screen_setup.sh
# 只在 "外接输出已连线但未点亮" 时动手; 已点亮/线未接 → 只打诊断, 不改布局。
# 前提: nvidia_drm modeset=1 + 装了 xserver-xorg-video-nvidia-<XXX> (见 SKILL.md / references/optimus-external-display.md)
export DISPLAY=${DISPLAY:-:0}
mkdir -p "$HOME/reports"
LOG="$HOME/reports/dual_screen_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG") 2>&1

echo "=== $(date '+%F %T') 双屏诊断 ==="
echo "会话类型: ${XDG_SESSION_TYPE:-?}   Xorg: $(pgrep -a Xorg | head -1)"
echo
echo "--- ① GPU providers ---"
xrandr --listproviders
echo
echo "--- ② 当前所有输出 ---"
xrandr --query | grep -E "^[A-Za-z]+-[0-9]" || xrandr --query

NVP=$(xrandr --listproviders | awk '/NVIDIA/{print $2}' | tr -d ':')
INTP=$(xrandr --listproviders | awk '!/NVIDIA/{print $2}' | tr -d ':' | head -1)
echo
echo "NVIDIA provider=$NVP   Intel provider=$INTP"

# 已连线但未点亮: 该行行尾正好是 " connected" (带分辨率=已点亮)
EXT=$(xrandr --query | awk '/^[A-Za-z]+-[0-9].* connected$/{print $1}' | grep -v eDP | head -1)
echo "外接输出(未点亮)= ${EXT:-无}"

if [ -n "$EXT" ]; then
  echo
  echo "--- ③ NVIDIA provider 的输出源接到 Intel (reverse PRIME) ---"
  [ -n "$NVP" ] && [ -n "$INTP" ] && xrandr --setprovideroutputsource "$NVP" "$INTP"
  sleep 1
  echo "--- ④ 点亮 $EXT 到内置屏右侧 ---"
  xrandr --output "$EXT" --auto --right-of eDP-1
else
  echo "  (无需处理: 外接屏已点亮, 或 HDMI 线未接)"
fi

echo
echo "--- ⑤ 结果 ---"
xrandr --query | grep -E "^[A-Za-z]+-[0-9]"
xrandr --listmonitors 2>/dev/null
echo
echo "日志: $LOG"
