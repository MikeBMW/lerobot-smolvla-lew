#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎛 训练+部署 控制平台 —— 分层分工的 Web 控制台

老倪 2026-09-24: "训练加部署控制, L2模型训练给小芳, L3以上微调训练给静静, Web你提供控制平台"

分工（硬编码为策略, 平台按此路由）:
  · L2 检测层   → **小芳 (Mac 备份端)** 负责训练（Mac 无 CUDA, 适合小模型/CPU 微调）
  · L3 调度层   → **静静 (4060 工作端)** 负责微调
  · L4 认知层   → **静静** 负责（统一主干 / MOE）
  · L5 规划层   → **静静** 负责（大模型层微调/策略）
  · 部署(晋级/回滚) → 任意端可发起, 但**必须留审计**（谁/何时/从哪个版本到哪个版本）

平台能力:
  ① 总览: 各层模型状态（在役版本 / 最新产物 / 留出指标 / 归属）
  ② 训练控制: 启动/查询（L3+ 本机直接执行; L2 生成"待小芳执行"的处理单）
  ③ 部署控制: 晋级默认档 / 回滚（带审计记录 + 校验 sha256）
  ④ 管道状态: 读 docs/PIPELINE_STATE.json（与画布/CICD 控制台同一真源）

零依赖（标准库）+ 单文件 → 可复制、可运维。
用法:
  python tools/train_deploy_console.py --port 8799            # 启动
  # 浏览器: http://<本机IP>:8799
  # 建议只在内网/白名单访问（与 ECS 主页同一策略）
"""
import argparse
import sys
import glob
import hashlib
import json
import os
import shlex
import subprocess
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWM = "/home/ubuntu/stable-wm-cache"
CKPT = os.path.join(SWM, "checkpoints")
STATE = os.path.join(REPO, "docs", "PIPELINE_STATE.json")
AUDIT = os.path.join(REPO, "docs", "deploy_audit.jsonl")
MANIFOLD = os.path.join(REPO, "docs", "manifold_view.json")
VENV = os.path.join(REPO, "gui-venv311", "bin", "python")

# ─────── 分工策略（老倪 2026-09-24 定）───────
OWNERSHIP = {
    "L2": {"owner": "小芳", "host": "Mac 备份端", "mode": "remote",
           "why": "L2=检测层(YOLO), 小模型可在 Mac CPU 微调; 分担工作端负载"},
    "L3": {"owner": "静静", "host": "4060 工作端", "mode": "local",
           "why": "L3=状态调度, 需与 L4 表征联动微调"},
    "L4": {"owner": "静静", "host": "4060 工作端", "mode": "local",
           "why": "L4=认知层, 统一主干/MOE, 需 CUDA"},
    "L5": {"owner": "静静", "host": "4060 工作端", "mode": "local",
           "why": "L5=规划层(大模型), 微调需显存"},
    "MEM": {"owner": "静静", "host": "4060 工作端", "mode": "local", "why": "记忆层构建"},
}

# 可训练层的命令模板（本机执行用）
TRAIN_CMDS = {
    "L4": "{v} tools/joint_unified_backbone.py --steps {n} --batch 64 --workers 3 --stats 250 "
          "--aug 1 --aug-scale 0.90,1.10 --cache-gb 6 "
          "--holdout {swm}/datasets/v6_holdout_rand.h5 "
          "--files {swm}/datasets/v6_sub25k.h5,{swm}/datasets/l5_new_sub12k.h5 "
          "--progress-file {swm}/reports/progress_{jid}.json --progress-every 10 "
          "--save {swm}/checkpoints/unified_web",
    "L4moe": "{v} tools/stage_moe_backbone.py --steps {n} --batch 64 --workers 3 --stats 250 "
             "--route prior --aug 1 --aug-scale 0.90,1.10 --cache-gb 5 "
             "--holdout {swm}/datasets/v6_holdout_rand.h5 "
             "--files {swm}/datasets/v6_sub25k.h5 "
             "--progress-file {swm}/reports/progress_{jid}.json --progress-every 10 "
             "--save {swm}/checkpoints/stage_moe_web",
    # L2 归小芳 → 平台只生成"处理单", 不本机执行
    "L2": "# 【待小芳执行 · Mac】L2 检测层微调\n"
          "# 1) 拉取最新数据切片: <网盘/relay 链接>\n"
          "# 2) cd lerobot-smolvla-lew && .venv-arm/bin/python tools/yolo_finetune.py \\\n"
          "#      --data <你的数据> --epochs 30 --imgsz 640 --device mps --out runs/l2_web\n"
          "# 3) 回传: 产物 + 留出指标(与基线对比) → 群里报",
}

JOBS = {}          # 运行中的训练 job
DEFAULT_CKPT = os.path.join(REPO, "models", "model_default.json")


def _sha16(p):
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()[:16]
    except Exception:
        return "-"


def _audit(ev):
    ev["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def status():
    """汇总: 各层归属 + 在役/最新产物 + 指标 + 管道阶段状态"""
    out = {"ownership": OWNERSHIP, "layers": {}, "pipeline": {}, "jobs": {}, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    # 各层最新产物
    for lyr in ("L2", "L3", "L4", "L5"):
        pats = {"L2": ["*yolo*", "*l2*"], "L3": ["*l3*", "*dispatch*"],
                "L4": ["unified*", "stage_moe*"], "L5": ["*l5*", "*planner*"]}[lyr]
        found = []
        for p in pats:
            for d in glob.glob(os.path.join(CKPT, p)):
                for f in glob.glob(os.path.join(d, "*.pt")) + glob.glob(os.path.join(d, "*.pth")):
                    found.append({"name": os.path.basename(os.path.dirname(f)), "file": os.path.basename(f),
                                  "mb": round(os.path.getsize(f) / 1048576, 1),
                                  "mtime": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(f))),
                                  "sha16": _sha16(f)})
        found.sort(key=lambda x: x["mtime"], reverse=True)
        out["layers"][lyr] = {"owner": OWNERSHIP.get(lyr, {}).get("owner", "?"),
                              "artifacts": found[:5], "has_train_cmd": lyr in TRAIN_CMDS}
    # 在役默认档
    if os.path.isfile(DEFAULT_CKPT):
        try:
            out["deployed"] = json.load(open(DEFAULT_CKPT, encoding="utf-8"))
        except Exception:
            out["deployed"] = {}
    # 管道状态（与画布/CICD 同一真源）
    if os.path.isfile(STATE):
        try:
            d = json.load(open(STATE, encoding="utf-8"))
            out["pipeline"] = {"stage": d.get("stage"), "state": d.get("state"),
                               "stages": d.get("stages", {})}
        except Exception:
            pass
    out["jobs"] = {k: {"layer": v["layer"], "status": v["status"], "t0": v["t0"],
                       "log": v["log"]} for k, v in JOBS.items()}
    return out


def start_train(layer, steps):
    if layer not in TRAIN_CMDS:
        return {"ok": False, "msg": "该层无本机训练命令（L2 归属小芳 → 见处理单）",
                "dispatch": TRAIN_CMDS.get("L2", "")}
    own = OWNERSHIP.get(layer, {})
    if own.get("mode") == "remote":
        _audit({"ev": "dispatch_remote", "layer": layer, "to": own.get("owner")})
        return {"ok": True, "msg": "已生成处理单（归属 %s）" % own.get("owner"),
                "dispatch": TRAIN_CMDS[layer]}
    jid = "job_%s_%d" % (layer.lower(), int(time.time()))
    log = "/tmp/web_%s.log" % jid
    cmd = TRAIN_CMDS[layer].format(v=VENV, n=int(steps), swm=SWM, jid=jid)
    try:
        f = open(log, "w")
        p = subprocess.Popen(cmd, shell=True, cwd=REPO, stdout=f, stderr=subprocess.STDOUT)
        JOBS[jid] = {"layer": layer, "status": "running", "t0": time.time(), "log": log, "pid": p.pid, "cmd": cmd}
        _audit({"ev": "train_start", "layer": layer, "steps": steps, "jid": jid, "pid": p.pid})
        return {"ok": True, "jid": jid, "pid": p.pid, "log": log, "msg": "已启动 %s 训练 %d 步" % (layer, steps)}
    except Exception as e:                                                # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:120])}


def deploy(layer, ckpt_dir, note=""):
    """晋级为默认档（带审计 + sha256）"""
    f = None
    for cand in ("unified.pt", "moe.pt", "model.pt", "best.pt"):
        p = os.path.join(CKPT, ckpt_dir, cand)
        if os.path.isfile(p):
            f = p
            break
    if f is None:
        return {"ok": False, "msg": "目录里没有可部署产物: %s" % ckpt_dir}
    prev = {}
    if os.path.isfile(DEFAULT_CKPT):
        try:
            prev = json.load(open(DEFAULT_CKPT, encoding="utf-8"))
        except Exception:
            prev = {}
    rec = dict(prev)
    rec[layer] = {"dir": ckpt_dir, "file": os.path.basename(f), "sha16": _sha16(f),
                  "mb": round(os.path.getsize(f) / 1048576, 1),
                  "at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
    os.makedirs(os.path.dirname(DEFAULT_CKPT), exist_ok=True)
    json.dump(rec, open(DEFAULT_CKPT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _audit({"ev": "deploy", "layer": layer, "dir": ckpt_dir, "sha16": rec[layer]["sha16"],
            "prev": prev.get(layer, {}).get("dir"), "note": note})
    return {"ok": True, "msg": "✅ %s 已晋级默认档: %s (%s)" % (layer, ckpt_dir, rec[layer]["sha16"]),
            "record": rec[layer]}


PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 训练 · 部署控制台</title>
<style>
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:18px}
h1{font-size:19px;margin:0 0 4px} .sub{color:#8b949e;font-size:12px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px}
.card h2{font-size:14px;margin:0 0 8px;color:#58a6ff}
.own{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;background:#1f6feb33;border:1px solid #1f6feb}
.own.mac{background:#bb800933;border-color:#bb8009}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:4px 6px;border-bottom:1px solid #21262d;text-align:left}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:6px 11px;font-size:12px;cursor:pointer;margin:2px}
button.grey{background:#30363d} button.red{background:#8b2c2c}
input{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:5px;width:70px;font-size:12px}
pre{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;font-size:11px;overflow:auto;max-height:220px;white-space:pre-wrap}
.st{color:#3fb950} .run{color:#00d4aa} .bad{color:#ff7b72}
</style></head><body>
<h1>🎛 Z-MAX 训练 · 部署控制台</h1>
<div class="sub" id="sub">加载中…</div>
<div class="grid" id="grid"></div>
<div class="card" style="margin-top:12px"><h2>📈 训练进度 + 能力提升（实测指标）</h2>
<div class="sub" id="pgsub">加载中…</div>
<div id="pgbar"></div>
<div style="font-size:12px;color:#8b949e;margin:10px 0 4px">能力提升（相对平凡基线: 观测恒均 0.0366 / 动作恒均 0.0955）</div>
<table id="cap"><tr><th>能力</th><th>指标</th><th>当前</th><th>基线</th><th>提升</th></tr></table></div>
<div class="card" style="margin-top:12px"><h2>🌀 结构化流形（真实计算 · 由 SU(2) 流形引擎产出）</h2>
<div class="sub" id="mfsub">加载中…</div>
<div style="display:flex;gap:16px;flex-wrap:wrap">
 <div style="flex:1;min-width:240px"><div style="font-size:12px;color:#8b949e">θ(t) 场景测地演化</div><canvas id="mfc" width="520" height="120" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px"></canvas></div>
 <div style="flex:1;min-width:240px"><div style="font-size:12px;color:#8b949e">各层 θ（末帧）</div><div id="mfl" style="font-size:12px;padding-top:6px"></div></div>
</div>
<div style="font-size:12px;color:#8b949e;margin-top:8px">层间不可交换性 ‖[U_i,U_j]‖（耦合强度）</div>
<pre id="mfcpl">—</pre></div>
<div class="card" style="margin-top:12px"><h2>📜 操作审计（最近 12 条）</h2><pre id="audit">—</pre></div>
<script>
const OWN={L2:['小芳','mac'],L3:['静静',''],L4:['静静',''],L5:['静静',''],MEM:['静静','']};
async function j(u,o){const r=await fetch(u,o);return r.json()}
async function load(){
 const s=await j('/api/status');
 document.getElementById('sub').textContent=`${s.ts} · 管道: ${s.pipeline.state||'-'} (阶段 ${s.pipeline.stage||'-'})`;
 let h='';
 for(const L of ['L2','L3','L4','L5']){
  const o=OWN[L]||['?','']; const lay=s.layers[L]||{};
  h+=`<div class="card"><h2>${L} <span class="own ${o[1]}">${o[0]} 负责</span></h2>`;
  h+=`<div style="font-size:11px;color:#8b949e;margin-bottom:6px">${(s.ownership[L]||{}).why||''}</div>`;
  h+=`<table><tr><th>产物</th><th>MB</th><th>时间</th></tr>`;
  (lay.artifacts||[]).slice(0,4).forEach(a=>{h+=`<tr><td>${a.name}</td><td>${a.mb}</td><td>${a.mtime}</td></tr>`});
  if(!(lay.artifacts||[]).length) h+='<tr><td colspan=3 style="color:#8b949e">无产物</td></tr>';
  h+='</table>';
  if(lay.has_train_cmd) h+=`<div style="margin-top:8px">步数 <input id="n_${L}" value="2500">
     <button onclick="tr('${L}')">▶ 启动训练</button>
     <button class="grey" onclick="dep('${L}')">⬆ 晋级默认</button></div>`;
  else h+=`<div style="margin-top:8px;font-size:11px;color:#d29922">↗ 归属备份端 → 平台生成处理单</div>
     <button class="grey" onclick="tr('${L}')">生成处理单</button>`;
  h+='</div>';
 }
 document.getElementById('grid').innerHTML=h;
 const pg=await j('/api/progress');
 if(pg && pg.jobs){
  // ★ 优先用**实时进度文件**(真·10步一跳), 回退到日志解析
  const lv=(pg.live||[]).find(x=>x.running && !x.stale);
  const run=lv? {log:lv.file, running:true, step:lv.step, total:lv.total, pct:lv.pct,
                 sps:lv.sps, loss:lv.loss, eta_s:(lv.total-lv.step)/Math.max(1e-6,lv.sps||1),
                 holdout_obs:(lv.best_obs!=null?lv.best_obs:'—'), holdout_act:'(见日志)',
                 best_obs:(lv.best_obs!=null?lv.best_obs:'—'), best_act:'—',
                 gain_obs: pg.jobs[0]?pg.jobs[0].gain_obs:'—', gain_act: pg.jobs[0]?pg.jobs[0].gain_act:'—',
                 live:true} : (pg.jobs.find(x=>x.running)||pg.jobs[0]);
  document.getElementById('pgsub').textContent = run?
    `${run.log} · ${run.running?'🔴 训练中':'已结束'} · ${run.step}/${run.total} 步 · ${run.sps} 步/s · loss ${run.loss} · ETA ${Math.round((run.eta_s||0)/60)} 分钟` : '无训练日志';
  if(run){
   document.getElementById('pgbar').innerHTML =
    `<div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;height:16px;margin-top:6px">
      <div style="width:${run.pct}%;height:100%;background:linear-gradient(90deg,#238636,#3fb950);border-radius:5px"></div></div>
     <div style="font-size:11px;color:#8b949e;margin-top:3px">${run.pct}% · 留出 观测 ${run.holdout_obs} / 动作 ${run.holdout_act}（best ${run.best_obs}/${run.best_act}）</div>
     <div style="font-size:12px;margin-top:4px">📊 本训练提升: 观测 <b class="st">+${run.gain_obs}%</b> · 动作 <b class="st">+${run.gain_act}%</b>（vs 平凡基线）</div>`;
  }
  document.getElementById('cap').innerHTML = '<tr><th>能力</th><th>指标</th><th>当前</th><th>基线</th><th>提升</th></tr>' +
   (pg.capability||[]).map(r=>`<tr><td>${r.name}</td><td>${r.metric}</td><td>${r.value}</td><td>${r.baseline}</td>
     <td class="${r.gain_pct>0?'st':'bad'}">${r.gain_pct>0?'+':''}${r.gain_pct}%</td></tr>`).join('');
 }
 const mf=await j('/api/manifold');
 if(mf && mf.theta_series){
  document.getElementById('mfsub').textContent=`${mf.n_steps} 步 · θ: min ${mf.theta_stats.min} max ${mf.theta_stats.max} mean ${mf.theta_stats.mean} std ${mf.theta_stats.std}`;
  const cv=document.getElementById('mfc'), g=cv.getContext('2d'), s=mf.theta_series;
  const mn=Math.min(...s), mx=Math.max(...s), W=cv.width, H=cv.height;
  g.clearRect(0,0,W,H); g.strokeStyle='#00d4aa'; g.lineWidth=2; g.beginPath();
  s.forEach((v,i)=>{const x=i/(s.length-1)*W, y=H-(v-mn)/Math.max(1e-9,mx-mn)*(H-16)-8; i?g.lineTo(x,y):g.moveTo(x,y)}); g.stroke();
  const L=mf.per_step[mf.per_step.length-1].layer_theta;
  document.getElementById('mfl').innerHTML=Object.entries(L).map(([k,v])=>
    `<div style="margin:3px 0">${k} <span style="display:inline-block;height:9px;width:${Math.min(100,v/3.15*100)}%;background:#58a6ff;border-radius:3px"></span> ${v.toFixed(4)}</div>`).join('')
    + `<div style="color:#8b949e;margin-top:4px">L5=0 → 未接 LLM（诚实标注）</div>`;
  const nz=Object.entries(mf.coupling||{}).filter(([k,v])=>v>1e-9);
  document.getElementById('mfcpl').textContent = nz.length? nz.map(([k,v])=>k+'  '+v).join('\n') : '（全零：各层元素可交换 → 无耦合）';
 } else { document.getElementById('mfsub').textContent='尚无流形数据 → 跑 python tools/manifold_train_view.py'; }
 const a=await j('/api/audit'); document.getElementById('audit').textContent=a.lines.join('\\n')||'（暂无）';
}
async function tr(L){const n=(document.getElementById('n_'+L)||{}).value||2500;
 const r=await j('/api/train',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layer:L,steps:n})});
 alert(r.msg + (r.dispatch? '\\n\\n处理单:\\n'+r.dispatch : (r.log? '\\n日志: '+r.log:''))); load();}
async function dep(L){const d=prompt(`${L} 晋级哪个产物目录？`,'unified_simreal'); if(!d)return;
 const r=await j('/api/deploy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layer:L,dir:d})});
 alert(r.msg); load();}
load(); setInterval(load, 5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):        # 静默（不刷屏）
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/status":
            return self._send(200, json.dumps(status(), ensure_ascii=False))
        if u.path == "/api/progress":
            try:
                sys.path.insert(0, os.path.join(REPO, "tools"))
                import train_progress_view as _tpv
                return self._send(200, json.dumps(_tpv.collect(), ensure_ascii=False))
            except Exception as e:                                        # noqa: BLE001
                return self._send(200, json.dumps({"err": "%s: %s" % (type(e).__name__, str(e)[:90])},
                                                  ensure_ascii=False))
        if u.path == "/api/manifold":
            d = {}
            if os.path.isfile(MANIFOLD):
                try:
                    d = json.load(open(MANIFOLD, encoding="utf-8"))
                except Exception as e:                                    # noqa: BLE001
                    d = {"err": "%s: %s" % (type(e).__name__, str(e)[:80])}
            return self._send(200, json.dumps(d, ensure_ascii=False))
        if u.path == "/api/audit":
            lines = []
            if os.path.isfile(AUDIT):
                lines = open(AUDIT, encoding="utf-8").read().strip().splitlines()[-12:]
            return self._send(200, json.dumps({"lines": lines}, ensure_ascii=False))
        return self._send(404, json.dumps({"err": "not found"}))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            d = {}
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/train":
            return self._send(200, json.dumps(start_train(d.get("layer", ""), d.get("steps", 2500)),
                                              ensure_ascii=False))
        if u.path == "/api/deploy":
            return self._send(200, json.dumps(deploy(d.get("layer", ""), d.get("dir", ""), d.get("note", "")),
                                              ensure_ascii=False))
        return self._send(404, json.dumps({"err": "not found"}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--status", action="store_true", help="只打印状态 JSON 后退出")
    a = ap.parse_args()
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return 0
    print("🎛 Z-MAX 训练·部署控制台 → http://%s:%d" % (a.host, a.port))
    print("   分工: L2→小芳(Mac) · L3/L4/L5→静静(4060) · 审计: %s" % os.path.relpath(AUDIT, REPO))
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
