#!/usr/bin/env python3
"""视频叠加模型名水印 (老倪要求: 分清哪个模型对应哪个视频)
用法: python3 tools/watermark_video.py <in.mp4> <模型名> [out.mp4]
"""
import subprocess, sys, os

def watermark(inp, name, outp=None, color="#00d4aa"):
    outp = outp or inp.replace(".mp4", "_wm.mp4")
    # drawtext 滤镜: 左上角模型名 (白底黑字/彩色)
    style = (f"drawtext=text='{name}':fontsize=36:fontcolor={color}:"
             f"borderw=2:bordercolor=black:x=20:y=20:"
             f"box=1:boxcolor=black@0.5:boxborderw=8")
    cmd = ["ffmpeg", "-y", "-i", inp, "-vf", style,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
           "-loglevel", "error", outp]
    subprocess.run(cmd, check=True)
    print(f"✅ 水印: {os.path.basename(inp)} → {os.path.basename(outp)} ({name})")

if __name__ == "__main__":
    watermark(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
