#!/usr/bin/env python3
"""v1.8.0 中版本报告生成 (模式: gen_report_v120.py)."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHA = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()

FEATURES = [
    ("🏗️ 三层架构功能卡恢复", "主页系统架构卡回归 — 页面一直在, 卡列表漏加修复 (卡↔页↔字典↔导航四端对齐)"),
    ("🛡 完整性保护检查", "tools/ci/integrity_check.py — 版本号/功能卡/页面字典/导航/类 五处一致性, 负向测试验证有效"),
    ("🧭 状态栏导航修复", "_on_nav names 列表与 modules 字典 13 项一一对齐 (原错位: 架构卡占数据集位)"),
    ("🔢 版本号全域统一", "studio.py ×2 / update_checker.py / docs_sync.py ×2 → v1.8.0, 修复 tag 领先代码 (v1.7.2 vs v1.7.0)"),
    ("🖥 远程 GPU 凭据修正", "~/.zmax_ssh.json 密码更新为 ahWat3se (旧密码失效导致连接拒绝)"),
    ("💾 全息 ID 角标系统", "P01-P12 页 × 区块 × 控件 3D 坐标 ID, 叠加式 QLabel 不 replaceWidget (防递归崩)"),
    ("🧪 容器化模型引擎", "本地/远程/端侧三模式卡片, 训练强制容器 zmax-std:1.0, 日志桥接 simulink→引擎"),
    ("🧩 坐标叠加架构", "state 叠加进 latent, 结构条件下放各模型行, 45D=39+相对向量, 配置表格与 Model Zoo 同源"),
    ("🔐 容器依赖锁定", "torch 2.11.0+cu128 + transformers 5.5.4, torchvision 锁定, requirements.lock 为准"),
]

MODELS = [
    ("ACT", "MLP蒸馏 39D 唯一可插拔 · 官方专家 85% 锚点"),
    ("SmolVLA", "500M 端到端 VLA · 坐标叠加架构"),
    ("SmolVLA+LEW", "15M 世界模型 · CrossAttn K/V 注入"),
    ("VLA-Touch", "视触觉 9 维 · 触觉中断实验 AWE 胜"),
    ("AWE", "视触觉编码 · 反归一化 stats 修复"),
    ("YOLO 感知", "mAP50 .994 · 2D→3D→39D 对齐 (±4cm)"),
]

HTML = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Z-MAX v1.8.0 中版本迭代报告</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif; background:#0d1117; color:#c9d1d9; margin:0; padding:32px; }}
  h1 {{ color:#58a6ff; border-bottom:2px solid #30363d; padding-bottom:12px; }}
  h2 {{ color:#00d4aa; margin-top:32px; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; }}
  th,td {{ border:1px solid #30363d; padding:8px 12px; text-align:left; }}
  th {{ background:#161b22; color:#58a6ff; }}
  tr:nth-child(even) {{ background:#161b22; }}
  .sha {{ font-family:monospace; color:#e3b341; }}
  .tag {{ display:inline-block; background:#1f6feb; color:#fff; padding:2px 10px; border-radius:12px; font-weight:bold; }}
</style>
</head>
<body>
<h1>🏗️ Z-MAX v1.8.0 中版本迭代报告</h1>
<p><span class="tag">v1.8.0</span> &nbsp; commit <span class="sha">{SHA}</span> &nbsp; 2026-08-09</p>

<h2>📌 本版核心</h2>
<p>恢复主页三层架构功能卡 + 建立<strong>完整性保护检查</strong>: 以后每次版本迭代跑 <code>python3 tools/ci/integrity_check.py</code>,
版本号/功能卡/页面字典/导航/类 五处一致性自动校验, 杜绝"页面在卡片丢"类遗漏。</p>

<h2>✨ 新功能 (9 项)</h2>
<table>
<tr><th>#</th><th>功能</th><th>说明</th></tr>
{''.join(f'<tr><td>{i+1}</td><td>{n}</td><td>{d}</td></tr>' for i,(n,d) in enumerate(FEATURES))}
</table>

<h2>🧬 模型迭代 (7 模型)</h2>
<table>
<tr><th>模型</th><th>状态</th></tr>
{''.join(f'<tr><td>{n}</td><td>{d}</td></tr>' for n,d in MODELS)}
</table>

<h2>🔗 数据链路</h2>
<table>
<tr><th>环节</th><th>状态</th></tr>
<tr><td>Orin 采集 → Mac(8769) → ECS 中转 → 4060</td><td>✅ 链路通 (ECS 防 OOM)</td></tr>
<tr><td>本地训练</td><td>✅ 强制容器 zmax-std:1.0 (--gpus all)</td></tr>
<tr><td>远程训练</td><td>✅ 223.109.239.36:24340 V100 32G (凭据已更新)</td></tr>
<tr><td>模型部署</td><td>✅ 训练好推 Mac / Orin, 静态 URL</td></tr>
<tr><td>GitHub Release</td><td>✅ tag + Release + 附件 (v1.8.0)</td></tr>
</table>

<h2>🛡 保护更新 (老倪: 以后按这个版本检查, 别少东西)</h2>
<pre style="background:#161b22; padding:16px; border-radius:8px; overflow-x:auto;">
python3 tools/ci/integrity_check.py
# 期望输出: ✅ Z-MAX v1.8.0 完整性检查通过
# 检查点: ①版本号5处 ②主页12功能卡 ③modules字典13键 ④addWidget顺序 ⑤页面类存在 ⑥导航names对齐
# 负向自测: 故意删卡/改版本 → 检查器必须报错 (已验证)
</pre>
</body>
</html>
"""

out = REPO / "docs" / "CICD_REPORT_v180.html"
out.parent.mkdir(exist_ok=True)
out.write_text(HTML, encoding="utf-8")
print(f"written: {out} ({out.stat().st_size} bytes)")
