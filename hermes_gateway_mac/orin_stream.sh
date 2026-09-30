#!/bin/bash
# ============================================================
# Z-MAX Orin 现场直播推流 · 每秒一帧 RealSense D405 → ECS
# 在 Orin 上执行: bash orin_stream.sh
# 页面: https://datadrive.world/cicd.html (每2秒自动刷新)
# ============================================================
set -u

ECS_HOST="root@39.102.211.79"
ECS_PW="Nix19789"
ECS_DIR="/www/wwwroot/datadrive.world"
TMP="/tmp/zmax_cam"
mkdir -p "$TMP"

echo "📷 Z-MAX Orin 直播推流启动 (Ctrl+C 停止)"
echo "   相机: RealSense D405 → JPEG(压缩) → ECS → 网页"

# 需要 sshpass (Ubuntu: sudo apt install sshpass)
which sshpass >/dev/null 2>&1 || { echo "❌ 缺 sshpass: sudo apt install sshpass"; exit 1; }

# 找 Python 相机脚本
CAM_PY="${TMP}/grab_frame.py"
cat > "$CAM_PY" <<'PYEOF'
#!/usr/bin/env python3
"""抓一帧 RealSense D405 → JPEG 输出到 stdout (压缩)"""
import sys, io, json
try:
    import pyrealsense2 as rs
    import numpy as np
    from PIL import Image

    ctx = rs.context()
    devs = ctx.query_devices()
    if len(devs) == 0:
        # 无相机: 生成占位帧
        img = Image.new("RGB", (640, 480), (20, 30, 45))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=60)
        sys.stdout.buffer.write(buf.getvalue()); sys.exit(0)

    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
    pipe.start(cfg)
    frames = pipe.wait_for_frames()
    color = frames.get_color_frame()
    if not color:
        img = Image.new("RGB", (640, 480), (40, 40, 40))
    else:
        arr = np.asanyarray(color.get_data())
        img = Image.fromarray(arr[:, :, ::-1])  # BGR→RGB
    pipe.stop()

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=65)  # 压缩: 质量65
    sys.stdout.buffer.write(buf.getvalue())
except Exception as e:
    # 兜底占位
    img = Image.new("RGB", (640, 480), (60, 20, 20))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=50)
    sys.stdout.buffer.write(buf.getvalue())
PYEOF

FRAME=0
while true; do
  FRAME=$((FRAME+1))
  # 1. 抓帧压缩
  python3 "$CAM_PY" > "$TMP/frame.jpg" 2>/dev/null
  SZ=$(stat -c%s "$TMP/frame.jpg" 2>/dev/null || echo 0)

  # 2. SCP 推送到 ECS (覆盖 orin_realtime.jpg, 页面直接读取)
  sshpass -p "$ECS_PW" scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "$TMP/frame.jpg" "${ECS_HOST}:${ECS_DIR}/orin_realtime.jpg" 2>/dev/null

  if [ $((FRAME % 10)) -eq 0 ]; then
    echo "  [$(date +%H:%M:%S)] 帧#${FRAME} · ${SZ}KB · 已推送"
  fi
  sleep 1  # 每秒一帧
done
