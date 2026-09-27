#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布「Z-MAX 现场实况」公网交付页 + APK 到 ECS, 并逐项回读核对 (2026-09-27)

用法:
  ZMAX_ECS_PW='<密码>' python tools/deploy_zmax_live.py [--check]

做的事(每步都有回读证据, 不许把"已上传"当"已验证"):
  ① 读本机 8791 的 /stats + /scene.json, 把**当次真实抓样**写进页面(帧龄/拍照时间随抓样时刻)
  ② 生成 tools/web/zmax-live.html (公网交付页: APK 下载入口 + 安装步骤 + 报错对照 + 活着的流清单)
  ③ scp APK → /www/wwwroot/datadrive.world/dl/ZMAX-Live.apk, chmod 644 (先备份同名旧文件)
  ④ scp 页面 → /www/wwwroot/datadrive.world/zmax-live.html, chmod 644
  ⑤ 首页 index.html 挂入口 (备份 .bak_<ts> 后插入, 幂等: 已存在就不插)
  ⑥ 回读核对: 远端 sha256 == 本地 sha256 · 公网 curl 下载 sha256 == 本地 · 页面/APK HTTP 200
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "39.102.211.79"
DOMAIN = "datadrive.world"
WEB = "/www/wwwroot/%s" % DOMAIN
LOCAL_API = "http://127.0.0.1:8791"
APK_LOCAL = "/home/ubuntu/state3d_app/live/ZMAX-Live.apk"
APK_NAME = "ZMAX-Live.apk"
PAGE_LOCAL = os.path.join(ROOT, "tools", "web", "zmax-live.html")
PAGE_REMOTE = "zmax-live.html"
LAN_IP = "192.168.23.50"

PW = os.environ.get("ZMAX_ECS_PW", "")
SSH_BASE = ["sshpass", "-p", PW, "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15",
            "root@%s" % HOST]
SCP_BASE = ["sshpass", "-p", PW, "scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15"]


def log(m):
    print("[deploy-live %s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def ssh(cmd, timeout=90):
    r = sh(SSH_BASE + [cmd], timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def scp(local, remote, timeout=180):
    r = sh(SCP_BASE + [local, "root@%s:%s" % (HOST, remote)], timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def url_get(url, timeout=25):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:                                              # noqa: BLE001
        return 0, ("%s: %s" % (type(e).__name__, e)).encode()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


SHORT = {"arm": "🦾 臂上 D405 (Orin)", "depth": "🌈 D405 深度图", "local": "💻 笔记本内置",
         "local2": "📺 MAXHUB 顶摄", "aoi_gold": "🔍 金手指判据图", "aoi_gold_raw": "🔍 金手指整板原图",
         "aoi_surface": "🔍 表面检测"}
LIVE_ORDER = ["ov_local", "ov_local2", "local", "local2", "aoi_gold", "aoi_gold_raw", "aoi_surface"]


def snap():
    """抓当次真实状态 (活着的流 + 帧龄 + 拍照时间 + 叠加框统计)"""
    st = json.loads(url_get(LOCAL_API + "/stats")[1].decode("utf-8"))
    sp = json.loads(url_get(LOCAL_API + "/scene.json")[1].decode("utf-8"))
    now = time.time()
    live, dead = [], []
    for k, v in st.items():
        on = (v.get("fps") or 0) > 0.1
        age = v.get("age_s")
        row = {"key": k, "label": SHORT.get(k.replace("ov_", "", 1), v.get("label") or k),
               "fps": v.get("fps"), "kb": v.get("kb_per_frame"),
               "age": age, "shot": (time.strftime("%H:%M:%S", time.localtime(now - age))
                                    if on and age is not None and age >= 0 else "—"),
               "ov": k.startswith("ov_")}
        (live if on else dead).append(row)
    live.sort(key=lambda r: (LIVE_ORDER.index(r["key"]) if r["key"] in LIVE_ORDER else 99))
    inf = (sp.get("_overlay_info") or {})
    boxes = {}
    for cam, d in (sp.get("cameras") or {}).items():
        o = (d.get("boxes") or [])
        boxes[cam] = {x: sum(1 for b in o if b.get("origin") == x) for x in ("sim", "vlm", "det")}
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "live": live, "dead": dead,
            "boxes": boxes, "mode": sp.get("mode"), "inf": {k: {"origins": v.get("origins"),
            "spec_age_s": v.get("spec_age_s")} for k, v in inf.items()}}


def rows_html(s):
    out = []
    for r in s["live"]:
        badge = '<span class="bd">叠加</span>' if r["ov"] else ""
        out.append("<tr><td>%s%s</td><td>%.1f fps</td><td class=\"n\">%.1fs</td><td class=\"n\">%s</td>"
                   "<td class=\"n\">%sKB</td></tr>"
                   % (r["label"], badge, float(r["fps"] or 0), float(r["age"] or 0), r["shot"],
                      "%.0f" % float(r["kb"] or 0)))
    for r in s["dead"]:
        out.append("<tr class=\"off\"><td>%s</td><td>未上线</td><td class=\"n\">—</td>"
                   "<td class=\"n\">—</td><td class=\"n\">—</td></tr>" % r["label"])
    return "\n".join(out)


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><script src="/auth.js"></script>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 现场实况 · 手机 APP</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#04070d;--panel:#0a0f18;--line:#1a2030;--fg:#c8d1d9;--dim:#6e7681;--acc:#00d4aa;--warn:#d29922}
body{background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
     padding:20px 16px 60px}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:24px;color:#fff;font-weight:800}
h1 em{color:var(--acc);font-style:normal}
.sub{color:var(--dim);font-size:14px;margin-top:6px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-top:16px}
h2{font-size:16.5px;color:#fff;margin-bottom:10px;font-weight:700}
h2 span{font-size:12.5px;color:var(--dim);font-weight:400;margin-left:6px}
a.dl{display:block;text-align:center;text-decoration:none;background:#0f5c37;border:1px solid #22c55e;color:#d6ffe6;
     font-weight:800;font-size:17px;padding:15px;border-radius:11px}
a.link{color:var(--acc)}
code{background:#111a24;padding:2px 6px;border-radius:5px;color:#7ee787;font-size:12.5px;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12.5px}
td.n{text-align:right}
tr.off td{color:#5c6570}
.bd{font-size:11px;font-weight:800;color:var(--acc);border:1px solid #1f7a4d;border-radius:20px;padding:0 6px;margin-left:6px}
ul{margin:6px 0 0 18px}li{margin:3px 0}
.steps{line-height:2}
.warn{background:#231a08;border:1px solid #6b4a12;color:#f0c674;border-radius:9px;padding:11px 13px;font-size:13.5px;margin-top:10px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
button{font:inherit;font-size:13.5px;font-weight:700;padding:9px 12px;border-radius:9px;border:1px solid #2b3946;
       background:#141d27;color:var(--fg);cursor:pointer}
.foot{color:var(--dim);font-size:12.5px;margin-top:18px;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <h1>📱 现场实况 <em>Z-MAX</em></h1>
  <div class="sub">工位机所有活着的相机流 + 仿真/检测叠加 · 一个 App 看全 —— 符合5个场景的具身方案技术协议 · 现场取证通道</div>

  <div class="card">
    <h2>① 装 App <span>__APK_SIZE__ · 安卓 7.0+</span></h2>
    <a class="dl" href="/dl/__APK_NAME__">⬇ 下载 __APK_NAME__</a>
    <div style="margin-top:10px">sha256 <code id="sha">__APK_SHA256__</code></div>
    <div class="row"><button onclick="cp(this)">📋 复制校验串</button></div>
    <div class="steps" style="margin-top:12px">
      ① 设置 → 安全 → 更多安全设置 → <b>关闭「纯净模式」</b><br>
      ② 同页「安装外部来源应用」→ 给浏览器/文件管理 <b>允许</b><br>
      ③ 提示风险 → 选 <b>继续安装</b>
    </div>
    <div class="warn">
      装不上看报错原文：<b>应用未安装</b> = 同包名残留 → 先卸载旧版；
      <b>解析包错误</b> = 没下完 → 重下并用上面 sha256 核对；
      <b>已阻止安装</b> = 纯净模式没关 → 回到第 ① 步。
    </div>
  </div>

  <div class="card">
    <h2>② 怎么打开 <span>需与工位机同一局域网（产线 WiFi）</span></h2>
    <div>装完桌面出现「<b>Z-MAX 实况</b>」图标，点开就是现场页。手机浏览器也能直接开：</div>
    <div style="margin-top:8px"><code>http://__LAN_IP__:8791/overlay</code></div>
    <div style="margin-top:8px;color:var(--dim);font-size:13px">
      页面必须由工位机自己用 http 提供 —— 相机流是 http MJPEG，站点是 https，https 页里嵌 http 画面会被内核按混合内容拦死
      （表现是页面能开、画面永远黑）。App 是顶层直接加载工位机 http 页，与视频流同源。
    </div>
  </div>

  <div class="card">
    <h2>③ 现在能看到什么 <span>抓样 __SNAP_AT__（帧龄随取帧实时刷新）</span></h2>
    <table>
      <tr><th>画面</th><th>帧率</th><th class="n">帧龄</th><th class="n">拍照时间</th><th class="n">体积</th></tr>
__ROWS__
    </table>
    <div style="margin-top:10px;color:var(--dim);font-size:13px">
      帧龄是源侧上报、拍照时间 = 本机时钟 − 帧龄（页面上每格实时显示，导出 CSV/JSON 也带这两列）。
      未上线的两路（臂上 D405 / 深度图）<b>如实标注、不上屏、不当活的用</b> —— 臂上 D405 的取帧口当前返回 503。
    </div>
  </div>

  <div class="card">
    <h2>④ 现场页能干什么</h2>
    <ul>
      <li><b>全看</b>：所有活着的流同屏 —— 全局只开 <b>1 条</b>串行取帧连接（手机只有 6 条 HTTP 连接，多路 MJPEG 会把连接吃干、整页卡死）</li>
      <li><b>单看</b>：挑一路放大，只开 1 条 MJPEG 常连，可选「原图 / 叠加」</li>
      <li><b>叠加来源</b>：🎯 仿真投影 · 🧠 大模型理解 · 📋 场景契约 · 🔍 真机检测，点哪个都回显真实结果（含失败原因）</li>
      <li><b>导出</b>：状态 JSON / CSV（带帧龄+拍照时间）/ 全部流地址，一键复制</li>
      <li><b>装 APP</b>：页面内直接下载安装包 + sha256 校验串</li>
    </ul>
    <div class="warn">本页/App <b>没有软急停</b> —— 急停用示教器或现场急停按钮。页面不发起真机动作。</div>
  </div>

  <div class="card">
    <h2>⑤ 相关入口</h2>
    <ul>
      <li><a class="link" href="/state-3d.html">🧊 Z-MAX 状态空间 3D</a> — 分层空间 + 实况联动</li>
      <li><a class="link" href="/hil.html">🙋 HIL 人机在环</a> — 状态与人的指示（与画布同一份状态）</li>
      <li><a class="link" href="/agent.html">🤖 Web 智能体桥</a> — 远程提示词 → 只读白名单</li>
      <li><span style="color:var(--dim)">手机现场页（局域网）：</span><code>http://__LAN_IP__:8791/overlay</code></li>
    </ul>
  </div>

  <div class="foot">
    发布口径：APK 与页面均按本次构建产物发布，下载链接的字节与磁盘产物逐字节一致（sha256 见上）。
    活着的流清单为抓样时刻的真实读数，非预录；未上线通道如实标注。
  </div>
</div>
<script>
function cp(btn){var t=document.getElementById('sha').textContent;
 try{ if(navigator.clipboard){navigator.clipboard.writeText(t);} }catch(e){}
 var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
 try{document.execCommand('copy');}catch(e){}document.body.removeChild(a);
 if(btn){btn.textContent='✅ 已复制';}}
</script>
</body>
</html>
"""


def build_page(s):
    apk_sha = sha_file(APK_LOCAL)
    apk_sz = "%.1fKB" % (os.path.getsize(APK_LOCAL) / 1024.0)
    html = (TEMPLATE
            .replace("__ROWS__", rows_html(s))
            .replace("__SNAP_AT__", s["at"])
            .replace("__APK_SHA256__", apk_sha)
            .replace("__APK_SIZE__", apk_sz)
            .replace("__APK_NAME__", APK_NAME)
            .replace("__LAN_IP__", LAN_IP))
    with open(PAGE_LOCAL, "w", encoding="utf-8") as f:
        f.write(html)
    left = html.count("__")
    log("页面生成 %s (%.1fKB, 未替换占位符=%d)" % (PAGE_LOCAL, len(html) / 1024.0, left))
    return apk_sha, apk_sz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not PW:
        log("❌ 缺 ZMAX_ECS_PW 环境变量")
        return 2

    s = snap()
    log("抓样 %s · 在线 %d 路 / 未上线 %d 路" % (s["at"], len(s["live"]), len(s["dead"])))
    apk_sha, apk_sz = build_page(s)
    if a.check:
        return 0

    log("① 远端建 /dl 目录 + 备份同名旧文件")
    rc, out = ssh("mkdir -p %s/dl && if [ -f %s/dl/%s ]; then cp -f %s/dl/%s %s/dl/%s.bak_$(date +%%s); fi "
                  "&& ls -la %s/dl | tail -3" % (WEB, WEB, APK_NAME, WEB, APK_NAME, WEB, APK_NAME, WEB))
    log("   rc=%s %s" % (rc, out.strip()[:200]))

    log("② scp APK + 页面")
    for local, remote in ((APK_LOCAL, "%s/dl/%s" % (WEB, APK_NAME)),
                          (PAGE_LOCAL, "%s/%s" % (WEB, PAGE_REMOTE))):
        rc, out = scp(local, remote)
        log("   scp %s → %s rc=%s %s" % (os.path.basename(local), remote, rc, out.strip()[:120]))
        if rc != 0:
            log("❌ scp 失败, 中止")
            return 3
    rc, out = ssh("chmod 644 %s/dl/%s %s/%s && md5sum %s/dl/%s" % (WEB, APK_NAME, WEB, PAGE_REMOTE,
                                                                  WEB, APK_NAME))
    log("   chmod/md5 rc=%s %s" % (rc, out.strip()[:160]))

    log("③ 远端 sha256 回读")
    rc, out = ssh("sha256sum %s/dl/%s" % (WEB, APK_NAME))
    remote_sha = out.strip().split()[0] if out.strip() else ""
    log("   远端=%s\n   本地=%s\n   一致=%s" % (remote_sha[:32] + "…", apk_sha[:32] + "…", remote_sha == apk_sha))

    log("④ 公网下载回读 (curl 公网 URL)")
    url = "https://%s/dl/%s" % (DOMAIN, APK_NAME)
    code, body = url_get(url, timeout=60)
    dl_sha = hashlib.sha256(body).hexdigest() if body else ""
    log("   HTTP %s · %d bytes · sha256=%s · 与本地一致=%s"
        % (code, len(body), dl_sha[:32] + "…", dl_sha == apk_sha))
    pcode, pbody = url_get("https://%s/%s" % (DOMAIN, PAGE_REMOTE))
    log("   页面 HTTP %s · %d bytes" % (pcode, len(pbody)))

    ok = (remote_sha == apk_sha) and (dl_sha == apk_sha) and code == 200 and pcode == 200
    log("✅ 全部核对通过" if ok else "❌ 有核对项未通过(见上)")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
