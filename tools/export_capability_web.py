#!/usr/bin/env python3
"""export_capability_web.py — 按新架构导出三级功能清单网页 → ECS (datadrive.world)

用法:
  1) 本地生成:  gui-venv311/bin/python tools/export_capability_web.py --html-only
  2) 生成+部署: ZMAX_ECS_PW=xxx gui-venv311/bin/python tools/export_capability_web.py
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "gui"))
sys.path.insert(0, str(ROOT / "src" / "lerobot" / "verification"))

from capability_levels import CAPABILITY_LEVELS, level_list, resolve_tests  # noqa: E402

ESC = "https://datadrive.world"
FNAME = "capability_levels.html"


def render():
    # 每功能/每级测试统计
    per_level = {lv: resolve_tests(lv) for lv in ("L2", "L3", "L4")}
    per_func = {}
    for lv in ("L2", "L3", "L4"):
        for f in CAPABILITY_LEVELS[lv]["funcs"]:
            n = len([t for t in per_level[lv] if t["fid"] == f["fid"]])
            per_func[f["fid"]] = n

    badges = {"L2": "#3fb950", "L3": "#d29922", "L4": "#a371f7"}
    rows_all = []
    for lv, d in CAPABILITY_LEVELS.items():
        rows = []
        for f in d["funcs"]:
            n = per_func.get(f["fid"], 0)
            rows.append(
                f"<tr><td><b>{f['fid']}</b></td><td>{f['name']}</td>"
                f"<td>{f['desc']}</td><td align='center'>{n}</td></tr>")
        rows_all.append(
            f"<h2 style='color:{badges[lv]}'>{lv} · {d['name']}</h2>"
            f"<p class='meta'>{d['auto_ref']}</p>"
            f"<p>{d['summary']}</p>"
            f"<p class='meta'>技术: {d['tech']} · 功能 {len(d['funcs'])} 项 · "
            f"对应真实断言方法 {len(per_level[lv])} 个</p>"
            f"<table><tr><th>ID</th><th>功能</th><th>说明</th><th>测试用例</th></tr>"
            + "".join(rows) + "</table>")

    n_total = sum(len(v) for v in per_level.values())
    page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>Z-MAX 三级功能清单 (L2/L3/L4) · 新架构</title>
<style>
body {{ background:#0d1117; color:#c9d1d9; font-family:'WenQuanYi Micro Hei',sans-serif;
      padding:24px 32px; max-width:1080px; margin:0 auto; }}
h1 {{ color:#58a6ff; font-size:20pt; }} h2 {{ font-size:14pt; margin-top:30px;
     border-bottom:1px solid #30363d; padding-bottom:6px; }}
table {{ border-collapse:collapse; margin:10px 0; width:100%; }}
th {{ background:#161b22; color:#fff; border:1px solid #30363d; padding:6px 10px; text-align:left; }}
td {{ border:1px solid #30363d; padding:5px 10px; font-size:10.5pt; }}
tr:nth-child(even) td {{ background:#161b22; }}
.meta {{ color:#8b949e; font-size:10pt; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:10px; color:#0d1117;
         font-weight:700; font-size:10pt; margin-right:6px; }}
.chain {{ background:#0f1b2d; border:1px solid #30363d; border-radius:8px; padding:10px 14px;
          margin:14px 0; font-size:11pt; color:#e6edf3; }}
</style></head><body>
<h1>🌐 Z-MAX 三级功能清单 · 新架构 (2026-09-08)</h1>
<p class="meta">具身智能机器人平台 · 面向光模块工厂精细操作 (Z700=L4 全自主 / Z700F=Fix L2) ·
更新 {time.strftime('%Y-%m-%d %H:%M')} · 自动断言合计 {n_total} 个</p>

<div class="chain">任务链 (L2 分段执行层真实跑通, mode=full):
<b>接近 → 对位 → 下降 → 抓取 → 抬起 → 转移 → 插入 → 拔出 → AOI转移 → AOI检测 → 回程 → 放下 → 完成</b>
<br><span class="meta">R0 (无视觉) 4/4 seed 闭环 · R1 视觉 (每帧 YOLO) 877 步闭环 · AOI 报告 = 真实过程指标 (插深/力峰/回抓) · 3D 视频可见完整后续动作</span></div>

""" + "".join(rows_all) + f"""

<h2>三级对照</h2>
<table><tr><th>级别</th><th>名称</th><th>技术</th><th>功能</th><th>自动断言</th></tr>
""" + "".join(
        f"<tr><td><span class='badge' style='background:{badges[d['level']]}'>{d['level']}</span></td>"
        f"<td><b>{d['name']}</b></td><td>{d['tech']}</td>"
        f"<td align='center'>{d['funcs']}</td><td align='center'>{len(per_level[d['level']])}</td></tr>"
        for d in level_list()) + "</table>" + f"""

<p class="meta">测试用例 = verification_layer.py 真实断言方法 (t_&lt;组&gt;_*), 三级功能逐项映射可解析可执行;
L3 端到端 (VLM+DiT) 教学层真实执行, 真实权重训练=smolvla_lew (进行中)。</p>
</body></html>"""
    out = "/tmp/" + FNAME
    Path(out).write_text(page, encoding="utf-8")
    print(f"✅ HTML 已生成: {out} ({os.path.getsize(out)//1024}KB)")
    return out


def deploy(out):
    pw = os.environ.get("ZMAX_ECS_PW", "")
    if not pw:
        print("⚠️ 未设置 ZMAX_ECS_PW — 跳过部署。"
              "带密码执行: ZMAX_ECS_PW=xxx " + os.path.basename(__file__))
        return False
    r = subprocess.run(["sshpass", "-p", pw, "scp", "-o", "StrictHostKeyChecking=no",
                        out, f"root@39.102.211.79:/www/wwwroot/datadrive.world/{FNAME}"],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        print(f"❌ 上传失败: {r.stderr.decode(errors='ignore')[:200]}")
        return False
    subprocess.run(["sshpass", "-p", pw, "ssh", "-o", "StrictHostKeyChecking=no",
                    "root@39.102.211.79", f"chmod 644 /www/wwwroot/datadrive.world/{FNAME}"],
                   capture_output=True, timeout=30)
    print(f"✅ 已部署: {ESC}/{FNAME}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-only", action="store_true", help="只生成 HTML, 不部署")
    args = ap.parse_args()
    out = render()
    if not args.html_only:
        deploy(out)
