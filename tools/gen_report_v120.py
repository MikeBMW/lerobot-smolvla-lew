#!/usr/bin/env python3
"""生成 Z-MAX v1.2.0 中版本迭代报告"""
import json, time, subprocess
from pathlib import Path

REPORT = Path.home() / "lerobot-smolvla-lew" / "docs" / "CICD_REPORT_v1.2.0.html"
REPORT.parent.mkdir(parents=True, exist_ok=True)

features = [
    ("📹 现场视频直播", "✅", "cicd.html 实时画面 · 归档快照优先 · 2秒刷新 · 方向锚点"),
    ("🖼 快照自动归档", "✅", "Orin快照(1s/帧)→archive自动落盘 · 不占训练队列 · 983+帧可回溯"),
    ("🔍 peek 归档兜底", "✅", "队列空时返回最新快照(current_state+图像) · 页面状态机实时"),
    ("📡 联调自动监控", "✅", "30s轮询队列 · 过滤快照 · 检测stage_act动作标签→自动训练"),
    ("🏋️ ACT 模型迭代", "✅", "基线300步→v2 3000步 · MSE -8.18% · loss 1.339"),
    ("🔬 基线对比工具", "✅", "同数据公平对比(MSE/成功率/延迟) · 自动判定提升"),
    ("🔄 自动迭代循环", "✅", "训练→对比→判断→未达标改进重训(步数+lr衰减)"),
    ("🤖 Orin 全量状态", "✅", "CPU/GPU/内存/温度/ROS2节点/关节 · 心跳内嵌sys上报"),
    ("🗂 数据路径透明", "✅", "队列/归档/实时帧三目录 · 包数实时可查"),
]

rows = "".join(f'<tr><td>{n}</td><td style="text-align:center">{s}</td><td>{d}</td></tr>' for n, s, d in features)
git_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, cwd=str(REPORT.parent.parent)).stdout.strip()

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Z-MAX v1.2.0 中版本报告</title>
<style>
body{{font-family:Consolas,monospace;background:#0d1117;color:#c9d1d9;padding:32px;max-width:900px;margin:0 auto}}
h1{{color:#58a6ff;border-bottom:2px solid #30363d;padding-bottom:8px}}
h2{{color:#00d4aa;margin-top:28px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}
td,th{{border:1px solid #30363d;padding:10px 12px;font-size:13px;text-align:left}}
.badge{{display:inline-block;padding:4px 16px;border-radius:12px;background:#1f6feb;color:#fff;font-weight:700}}
.meta{{color:#8b949e;font-size:12px}}
.up{{color:#2ea043}}
</style></head><body>
<h1>🚀 Z-MAX <span class="badge">v1.2.0</span> 中版本迭代报告</h1>
<p class="meta">时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · commit <span class="badge">{git_sha}</span></p>
<p>v1.1.0 → v1.2.0 · 本轮主题: <b>现场直播 + 数据链路透明 + 自动迭代联调</b></p>

<h2>✨ 新功能 (9 项)</h2>
<table><tr><th style="width:200px">功能</th><th style="width:50px">状态</th><th>说明</th></tr>{rows}</table>

<h2>📈 模型迭代对比</h2>
<table>
<tr><th>版本</th><th>Steps</th><th>MSE</th><th>提升</th></tr>
<tr><td>基线 (act_metaworld)</td><td>300</td><td>12037.8</td><td>—</td></tr>
<tr><td>v1.1.0 (2000步)</td><td>2000</td><td>11155.0</td><td class="up">+7.33%</td></tr>
<tr><td><b>v2 (3000步+lr调优)</b></td><td>3000</td><td><b>11053.3</b></td><td class="up"><b>+8.18%</b></td></tr>
</table>

<h2>📊 数据链路 (透明可查)</h2>
<table>
<tr><th>环节</th><th>路径</th><th>状态</th></tr>
<tr><td>训练队列</td><td>ECS /root/zmax-relay/data/</td><td>只留可训练数据包</td></tr>
<tr><td>快照归档</td><td>ECS /root/zmax-relay/archive/</td><td>983+ 帧 (1s/帧)</td></tr>
<tr><td>实时帧</td><td>/api/relay/cam/latest.jpg</td><td>页面视频流</td></tr>
<tr><td>本地训练</td><td>/home/xspace/lerobot-smolvla-lew/outputs/train/</td><td>3.7G · 6模型</td></tr>
</table>

<p class="meta" style="margin-top:24px">— Z-MAX CICD · 静静(4060) 自动生成 —</p>
</body></html>"""

REPORT.write_text(html, encoding="utf-8")
print(f"✅ 报告生成: {REPORT} ({REPORT.stat().st_size//1024}KB)")
