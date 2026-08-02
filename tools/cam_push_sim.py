#!/usr/bin/env python3
"""Z-MAX 动态推帧服务 v2 · 图形标记不依赖字体
顶部: 红色箭头▲ + 绿色移动方块 | 底部: 蓝色条 + 帧号
"""
import time, io, requests
from PIL import Image, ImageDraw

URL = "https://datadrive.world/api/relay/cam/upload"
frame = 0
print("📹 动态推帧服务 v2 (图形标记)")

while True:
    frame += 1
    img = Image.new("RGB", (640, 480), (18, 24, 40))
    d = ImageDraw.Draw(img)
    # 顶部: 红色三角箭头 (方向锚点)
    d.polygon([(320, 15), (295, 55), (345, 55)], fill=(255, 60, 60))
    # 顶部右侧: 绿色移动方块 (证明在动)
    x = 30 + (frame * 15) % 580
    d.rectangle([x, 25, x + 50, 50], fill=(0, 200, 120))
    # 中部: 帧号方块 (青→蓝渐变)
    d.rectangle([20, 220, 620, 300], fill=(30, 60, 110))
    # 帧号以条码形式 (不依赖字体)
    for i in range(8):
        if (frame >> i) & 1:
            d.rectangle([40 + i * 70, 235, 100 + i * 70, 285], fill=(0, 212, 170))
    # 底部: 蓝色横条 (底部锚点)
    d.rectangle([0, 460, 640, 480], fill=(60, 120, 220))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    data = buf.getvalue()
    try:
        r = requests.post(URL, data=data,
                          headers={"Content-Type": "image/jpeg"}, timeout=15)
        if frame % 5 == 0:
            print(f"[{time.strftime('%H:%M:%S')}] 帧#{frame} {'OK' if r.status_code == 200 else r.status_code}", flush=True)
    except Exception as ex:
        print(f"[{time.strftime('%H:%M:%S')}] 失败: {ex}", flush=True)
    time.sleep(2)
