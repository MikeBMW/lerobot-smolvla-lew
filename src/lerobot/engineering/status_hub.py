#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""状态聚合中心 (status_hub) —— 硬件 / 在役模型 / 训练 / 3DGS 资产 → 固定 JSON 契约

对外唯一入口:  GET http://127.0.0.1:8796/status/all   (tools/sam3_seg.py 里的新路由)
本模块只做「真实采集 + 聚合 + 缓存」; 不占端口、不起服务 (8796 归 SAM3 服务)。

设计要点
  ① 真实采集, 不写死: /proc/stat · /proc/loadavg · /proc/meminfo · shutil.disk_usage('/') ·
     nvidia-smi · src/lerobot/engineering/models_manifest.json(版本真源) + 每条模型 probe 真探针 ·
     训练进程 /proc/<pid>/cmdline + 训练日志 · 3DGS 产物目录 (gs.ply/gs.splat/train_report.json)。
  ② 后台线程每 INTERVAL 秒刷新一次快照; /status/all 只读快照 ⇒ 响应 <50ms (绝不每次全量采集)。
  ③ 任一路采样失败 ⇒ 该段字段降级(null / 0) 并附 "err", 绝不抛异常、绝不 500。

契约 (下游 GUI 已按此写死, 勿改字段名/层级):
{
 "ts": <float>,
 "hw": {"gpu":{"util":int,"mem_used_mb":int,"mem_total_mb":int,"temp_c":int,"name":str},
        "cpu":{"util":int,"cores":int,"load1":float},
        "mem":{"used_gb":float,"total_gb":float},
        "disk":{"used_gb":int,"total_gb":int,"pct":int}},
 "models": [{"layer":"L2|L3|L4|L5","name":str,"version":str,"state":"in_service|candidate|untrained","inferring":bool}],
 "training": {"active":bool,"layer":str,"name":str,"version":str,"step":int,"total":int,"pct":int,"eta_s":int,"speed_s_per_step":float},
 "assets": [{"kind":"3DGS","name":str,"version":str,"path":str}]
}
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MANIFEST = os.path.join(ROOT, "src", "lerobot", "engineering", "models_manifest.json")
SS_BYPASS_STATUS = "/home/ubuntu/zmax_data/ss_bypass/status.json"
GS_ASSETS_DIR = "/home/ubuntu/zmax_data/gs_assets"
REPORTS_DIR = os.path.join(ROOT, "reports")
TRAIN_MEM_MB = 1500                     # nvidia-smi 计算进程显存 > 此值 ⇒ 判为训练 (老倪口径)

INTERVAL = 1.0                          # 后台刷新周期 (s)
CACHE_TTL = 1.0                         # 快照对外有效期 (s)

_lock = threading.Lock()
_cache = {"ts": 0.0, "data": None}
_hist = {}                              # 计数器探针历史 {probe_key: [(ts, value), ...]} (窗口内比较)
_prev_cpu = {}                          # /proc/stat 上一跳
_state = {"started": False, "err": None}
_thread = None
COUNTER_WINDOW_S = 3.0                  # 计数器增长判定窗口 (文件类计数器刷新慢, 1s 窗口会漏)


# ──────────────────────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────────────────────
def _int(x, d=0):
    try:
        v = int(round(float(x)))
        return v
    except Exception:
        return d


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _run(cmd, timeout=3):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.stdout or ""


def _expand(p):
    return os.path.expanduser(p) if p else p


def _read_json(path):
    with open(_expand(path), encoding="utf-8") as f:
        return json.load(f)


def _dig(obj, pointer):
    """按点分路径取值 (支持 dict 键; 列表按数字索引)。"""
    cur = obj
    for part in str(pointer).split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    return cur


# ──────────────────────────────────────────────────────────────────────────────
# ① 硬件
# ──────────────────────────────────────────────────────────────────────────────
def collect_gpu() -> dict:
    """nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name"""
    out: dict = {"util": 0, "mem_used_mb": 0, "mem_total_mb": 0, "temp_c": 0, "name": "unknown"}
    errs = []
    try:
        line = _run(["nvidia-smi",
                     "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                     "--format=csv,noheader"]).strip().splitlines()
        if not line:
            raise RuntimeError("nvidia-smi 无输出")
        row = line[0]
        parts = [p.strip() for p in row.split(",", 4)]
        if len(parts) < 5:
            raise RuntimeError("无法解析 nvidia-smi 行: %r" % row)
        out["util"] = _int(parts[0].replace("%", ""))
        out["mem_used_mb"] = _int(parts[1].replace("MiB", ""))
        out["mem_total_mb"] = _int(parts[2].replace("MiB", ""))
        out["temp_c"] = _int(parts[3].replace("C", ""))
        out["name"] = parts[4]
    except Exception as e:                                            # noqa: BLE001
        errs.append("gpu: %s: %s" % (type(e).__name__, e))
    if errs:
        out["err"] = "; ".join(errs)
    return out


def collect_cpu_mem() -> dict:
    """CPU 利用率 = /proc/stat 两跳差值; 内存 = /proc/meminfo。"""
    cpu = {"util": 0, "cores": os.cpu_count() or 0, "load1": 0.0}
    mem = {"used_gb": 0.0, "total_gb": 0.0}
    errs = []
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = [int(x) for x in parts[1:11]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        with _lock:
            p = _prev_cpu.get("stat")
            _prev_cpu["stat"] = (total, idle)
        if p:
            dt = total - p[0]
            di = idle - p[1]
            if dt > 0:
                cpu["util"] = max(0, min(100, _int(100.0 * (dt - di) / dt)))
        try:
            cpu["load1"] = round(_f(open("/proc/loadavg").read().split()[0]), 2)
        except Exception:                                             # noqa: BLE001
            cpu["load1"] = 0.0
    except Exception as e:                                            # noqa: BLE001
        errs.append("cpu: %s: %s" % (type(e).__name__, e))
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, _, v = ln.partition(":")
                info[k.strip()] = v.strip()
        tot = _f(info.get("MemTotal", "0 kB").split()[0]) / 1048576.0
        avail = _f(info.get("MemAvailable", "0 kB").split()[0]) / 1048576.0
        mem["total_gb"] = round(tot, 1)
        mem["used_gb"] = round(max(0.0, tot - avail), 1)
    except Exception as e:                                            # noqa: BLE001
        errs.append("mem: %s: %s" % (type(e).__name__, e))
    if errs:
        cpu["err"] = "; ".join(errs)
    return {"cpu": cpu, "mem": mem}


def collect_disk() -> dict:
    """shutil.disk_usage('/')"""
    out: dict = {"used_gb": 0, "total_gb": 0, "pct": 0}
    try:
        u = shutil.disk_usage("/")
        out["used_gb"] = _int(u.used / 1000000000.0)
        out["total_gb"] = _int(u.total / 1000000000.0)
        out["pct"] = _int(round(100.0 * u.used / u.total)) if u.total else 0
    except Exception as e:                                            # noqa: BLE001
        out["err"] = "disk: %s: %s" % (type(e).__name__, e)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ② 在役/候选模型 (+ 是否在推理: 真探针)
# ──────────────────────────────────────────────────────────────────────────────
def _manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def _counter_growing(key, cur, window_s=COUNTER_WINDOW_S):
    """把计数值存入窗口历史, 判断「窗口前的值 → 现在」是否增长 (慢刷新文件也能判)。"""
    now = time.time()
    with _lock:
        hist = _hist.setdefault(key, [])
        hist.append((now, cur))
        del hist[:-12]
        ref = None
        for t, v in hist:
            if now - t >= window_s:
                ref = v                                  # 取窗口内最早的那个样本做基准
                break
        if ref is None:
            ref = hist[0][1]                            # 窗口未满: 退化用最早样本
    return cur > ref


def _probe_inferring(probe, key, errs):
    """真探针 ⇒ bool。counter 类看窗口内计数是否增长; file/ts/age 类看新鲜度。"""
    t = (probe or {}).get("type", "none")
    try:
        if t == "http_counter":
            url, field = probe["url"], probe["field"]
            with urllib.request.urlopen(url, timeout=0.6) as r:
                obj = json.loads(r.read().decode("utf-8", "replace"))
            cur = _int(_dig(obj, field), -1)
            return _counter_growing(key, cur, float(probe.get("window_s", COUNTER_WINDOW_S)))
        if t == "json_counter":
            cur = _int(_dig(_read_json(probe["path"]), probe["pointer"]), -1)
            return _counter_growing(key, cur, float(probe.get("window_s", COUNTER_WINDOW_S)))
        if t == "http_ts":
            # 指向一个 unix 时间戳字段 (如最近一次真实调用时刻)
            url, field = probe["url"], probe["field"]
            with urllib.request.urlopen(url, timeout=0.6) as r:
                obj = json.loads(r.read().decode("utf-8", "replace"))
            ts, ok = _f(_dig(obj, field), 0.0), _dig(obj, field)
            return bool(ok) and ts > 0 and (time.time() - ts) <= float(probe.get("max_age_s", 60))
        if t == "file_fresh":
            st = os.stat(_expand(probe["path"]))
            return (time.time() - st.st_mtime) <= float(probe.get("max_age_s", 10))
        if t == "json_age":
            # 指向一个「年龄(秒)」字段 (如 DDS 主题 age_s): <= 阈值 ⇒ 该层在跑
            age = _f(_dig(_read_json(probe["path"]), probe["pointer"]), 1e9)
            return age <= float(probe.get("max_age_s", 2))
        return False
    except Exception as e:                                            # noqa: BLE001
        errs.append("probe[%s]: %s: %s" % (key, type(e).__name__, e))
        return False


def collect_models() -> list:
    """读 models_manifest.json (版本真源) + 每条 probe 真探针 ⇒ models[]"""
    out, errs = [], []
    try:
        man = _manifest()
    except Exception as e:                                            # noqa: BLE001
        return [{"layer": "L2", "name": "manifest 读取失败", "version": "unknown",
                 "state": "untrained", "inferring": False,
                 "err": "manifest: %s: %s" % (type(e).__name__, e)}]
    for layer in ("L2", "L3", "L4", "L5"):
        for i, m in enumerate(man.get("layers", {}).get(layer, [])):
            key = "%s/%d/%s" % (layer, i, m.get("name", "")[:24])
            sub = []
            inf = _probe_inferring(m.get("probe"), key, sub)
            item = {"layer": layer,
                    "name": m.get("name", "unknown")[:60],
                    "version": m.get("version", "unknown"),
                    "state": m.get("state", "unknown"),
                    "inferring": bool(inf)}
            if sub:
                item["err"] = "; ".join(sub)[:180]
            out.append(item)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ③ 训练 (进程真检测 + 日志真进度)
# ──────────────────────────────────────────────────────────────────────────────
_LAYER_BY_CMD = (
    ("lerobot.scripts.lerobot_train", "L3", "smolvla"),
    ("lerobot_train", "L3", "smolvla"),
    ("sam3_finetune", "L2", "sam3"),
    ("yolo_annot_train", "L2", "yolo"),
    ("intact", "L4", "intact"),
    ("train.py", "L4", "intact"),
)
_TQDM_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*\[([^\]]*)\]")
_INFO_STEP_RE = re.compile(r"\bstep:(\d+)")
_SPEED_RE = re.compile(r"([\d.]+)\s*s/step")
_UPDT_RE = re.compile(r"updt_s:([\d.]+)")
_INTACT_RE = re.compile(r"\[Epoch\s+\d+/\d+\]\s+step\s+(\d+)/(\d+)\s+\(([\d.]+)\s*it/s\)")
_YOLO_RE = re.compile(r"(?:\r|\n|^)[^\r\n]{0,16}?(\d+)/(\d+)\s+([\d.]+)G")


def _cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except Exception:                                                 # noqa: BLE001
        return ""


def _classify(cmd):
    low = cmd.lower()
    for needle, layer, kind in _LAYER_BY_CMD:
        if needle in low:
            return layer, kind
    return "", ""


def _parse_progress(text, layer):
    """从训练日志文本里抠出 (step,total,speed)。多个匹配取最后一次。

    覆盖系统里真实存在的三种训练日志口径:
      · lerobot (L3): tqdm `Training: 98%|...| 197/200 [08:34<00:07, 2.58s/step]` + `step:200 ... updt_s:2.571`
      · INTACT  (L4): `[Epoch 0/1] step 150/200 (1.5 it/s)`
      · ultralytics (L2): `      29/30      1.28G     1.001 ...` (逐 epoch)
      · SAM3 微调: jsonl `{"step": 540, ... "s_per_step": 0.67}`
    """
    step = total = 0
    speed = 0.0
    for m in _TQDM_RE.finditer(text):
        step, total = int(m.group(1)), int(m.group(2))
        s = _SPEED_RE.search(m.group(3))
        if s:
            speed = _f(s.group(1))
    for m in _INFO_STEP_RE.finditer(text):
        if int(m.group(1)) >= step:
            step = int(m.group(1))
            u = _UPDT_RE.search(text[max(0, m.start() - 20):m.start() + 400])
            if u:
                speed = _f(u.group(1))
    for m in re.finditer(r"\{[^\n]*\"step\":\s*(\d+)[^\n]*\}", text):
        try:
            row = json.loads(m.group(0))
        except Exception:                                             # noqa: BLE001
            continue
        if _int(row.get("step")) >= step:
            step = _int(row.get("step"))
            speed = _f(row.get("s_per_step"), speed)
    for m in _INTACT_RE.finditer(text):                               # L4 INTACT
        step, total = int(m.group(1)), int(m.group(2))
        its = _f(m.group(3))
        if its > 0:
            speed = 1.0 / its
    for m in _YOLO_RE.finditer(text):                                 # L2 ultralytics (epoch 粒度)
        e, n = int(m.group(1)), int(m.group(2))
        if e >= step:
            step, total = e, n
    return step, total, speed


def _log_hint_total(text):
    """从命令/配置文本里给总步数线索 (如 limit_train_batches / steps / epochs)。"""
    for pat in (r"limit_train_batches[=\s]+(\d+)", r"(?:^|\s)steps[=\s]+(\d+)",
                r"--epochs\s+(\d+)", r"--steps\s+(\d+)"):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return 0


def _hint_total(kind, version, cmd):
    """按训练种类去真实产物里读总步数 (命令行读不到时)。"""
    try:
        if kind == "sam3" and version and version != "unknown":
            p = os.path.join(ROOT, "outputs", "sam3_finetune", version, "run_report.json")
            if os.path.exists(p):
                return _int(_read_json(p).get("steps"))
        if kind == "smolvla":
            m = re.search(r"--config_path=(\S+)", cmd)
            if m and os.path.exists(m.group(1)):
                with open(m.group(1), encoding="utf-8") as f:
                    t = f.read()
                mm = re.search(r"^\s*steps:\s*(\d+)", t, re.M)
                if mm:
                    return int(mm.group(1))
    except Exception:                                                 # noqa: BLE001
        pass
    return _log_hint_total(cmd)


def _newest_log(kind, layer):
    """找最近被写过的训练日志 (reports/joint_train_*/ 或 outputs/sam3_finetune/ 下)。"""
    cands = []
    if kind == "sam3":                                                # SAM3 微调日志在产物目录里
        base = os.path.join(ROOT, "outputs", "sam3_finetune")
        try:
            for d in os.listdir(base):
                p = os.path.join(base, d, "train_log.jsonl")
                if os.path.exists(p):
                    cands.append((os.path.getmtime(p), p))
        except Exception:                                             # noqa: BLE001
            pass
    try:
        for d in os.listdir(REPORTS_DIR):
            if not d.startswith("joint_train_"):
                continue
            p = os.path.join(REPORTS_DIR, d)
            for fn in os.listdir(p):
                if not fn.endswith(".log"):
                    continue
                low = fn.lower()
                want = {"smolvla": "l3", "intact": "l4", "yolo": "l2", "sam3": "l2"}.get(kind, "")
                if want and want not in low:
                    continue
                fp = os.path.join(p, fn)
                cands.append((os.path.getmtime(fp), fp))
    except Exception:                                                 # noqa: BLE001
        pass
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


def collect_training() -> dict:
    out = {"active": False, "layer": "", "name": "", "version": "",
           "step": 0, "total": 0, "pct": 0, "eta_s": 0, "speed_s_per_step": 0.0}
    errs = []
    try:
        rows = _run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                     "--format=csv,noheader"]).strip().splitlines()
        procs = []
        for r in rows:
            if not r.strip():
                continue
            parts = [x.strip() for x in r.split(",")]
            if len(parts) < 2:
                continue
            pid, mb = _int(parts[0]), _int(parts[1].replace("MiB", ""))
            if mb >= TRAIN_MEM_MB:
                procs.append(pid)
        hit = None
        for pid in procs:
            cmd = _cmdline(pid)
            layer, kind = _classify(cmd)
            if layer:
                hit = (pid, cmd, layer, kind)
                break
        if not hit:
            out["note"] = "无 >%dMiB 的计算进程 ⇒ 未在训练" % TRAIN_MEM_MB
            return out

        pid, cmd, layer, kind = hit
        out["active"] = True
        out["layer"] = layer
        out["name"] = {"smolvla": "SmolVLA+LEW 长程规划 LoRA", "intact": "INTACT 世界模型光模块插入 LoRA",
                       "yolo": "YOLO 检测域适应微调", "sam3": "SAM3 开放词汇分割适配器"}.get(kind, kind or layer)
        # 版本号: 优先输出目录名 (真实产物路径)
        m = re.search(r"--config_path=(\S+)", cmd) or re.search(r"output_model_name=(\S+)", cmd) \
            or re.search(r"--name\s+(\S+)", cmd)
        out["version"] = os.path.basename(m.group(1)) if m else "unknown"
        for tok in cmd.split():
            if "outputs/train/" in tok:
                out["version"] = os.path.basename(tok.rstrip("/"))
                break

        log = _newest_log(kind, layer)
        if log:
            try:
                size = os.path.getsize(log)
                with open(log, "rb") as f:
                    f.seek(max(0, size - 400000))
                    text = f.read().decode("utf-8", "replace")
                step, total, speed = _parse_progress(text, layer)
                if not total:
                    total = _hint_total(kind, out["version"], cmd)
                out["step"] = step
                out["total"] = total
                out["speed_s_per_step"] = round(speed, 3)
                if total > 0:
                    out["pct"] = max(0, min(100, _int(round(100.0 * step / total))))
                    out["eta_s"] = _int(round(max(0, total - step) * speed)) if speed > 0 else 0
            except Exception as e:                                    # noqa: BLE001
                errs.append("progress: %s: %s" % (type(e).__name__, e))
        else:
            errs.append("progress: 未找到 %s 训练日志 ⇒ step/total 降级为 0" % layer)
    except Exception as e:                                            # noqa: BLE001
        errs.append("training: %s: %s" % (type(e).__name__, e))
        out["active"] = False
    if errs:
        out["err"] = "; ".join(errs)[:200]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ④ 3DGS 资产 (真源: ~/zmax_data/gs_assets/<scene>/gs.ply|gs.splat + train_report.json)
# ──────────────────────────────────────────────────────────────────────────────
def _gs_version(d):
    """mtime + 大小 + 训练配置 → 短哈希 (内容/产物变了版本号才变)。"""
    h = hashlib.sha1()
    rep = {}
    try:
        rep = _read_json(os.path.join(d, "train_report.json"))
    except Exception:                                                 # noqa: BLE001
        pass
    h.update(os.path.basename(d).encode())
    for k in ("steps", "n_gaussians", "psnr_holdout_db"):
        if k in rep:
            h.update(("%s=%s" % (k, rep[k])).encode())
    for fn in ("gs.ply", "gs.splat"):
        fp = os.path.join(d, fn)
        try:
            st = os.stat(fp)
            h.update(("%s|%d|%d|" % (fn, st.st_size, int(st.st_mtime))).encode())
        except Exception:                                             # noqa: BLE001
            pass
    day = time.strftime("%Y%m%d", time.localtime(os.path.getmtime(d)))
    return "v%s-%s" % (day, h.hexdigest()[:8])


def collect_assets() -> list:
    out, errs = [], []
    try:
        found = []
        for name in sorted(os.listdir(GS_ASSETS_DIR)):
            d = os.path.join(GS_ASSETS_DIR, name)
            if not os.path.isdir(d):
                continue
            ply = os.path.join(d, "gs.ply")
            rep = os.path.join(d, "train_report.json")
            if not (os.path.exists(ply) and os.path.exists(rep)):
                continue                                  # 只有真产出 ply+report 才算「资产」
            found.append((os.path.getmtime(ply), d))
        found.sort(reverse=True)
        for mt, d in found[:5]:                                       # 只报最近 5 个
            try:
                rep = _read_json(os.path.join(d, "train_report.json"))
            except Exception:                                         # noqa: BLE001
                rep = {}
            ng = rep.get("n_gaussians")
            label = os.path.basename(d) + (" · %s 高斯" % ng if ng else "")
            out.append({"kind": "3DGS",
                        "name": label[:70],
                        "version": _gs_version(d),
                        "path": os.path.join(d, "gs.splat")})
    except Exception as e:                                            # noqa: BLE001
        errs.append("assets: %s: %s" % (type(e).__name__, e))
    if errs:
        out.append({"kind": "3DGS", "name": "3DGS 资产采集降级", "version": "unknown",
                    "path": "", "err": "; ".join(errs)[:180]})
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 聚合 + 后台刷新 + 快照
# ──────────────────────────────────────────────────────────────────────────────
def _collect_all() -> dict:
    d = {"ts": time.time(), "errs": []}
    try:
        d["hw"] = {"gpu": collect_gpu()}
    except Exception as e:                                            # noqa: BLE001
        d["hw"] = {"gpu": {"util": 0, "mem_used_mb": 0, "mem_total_mb": 0, "temp_c": 0,
                           "name": "unknown", "err": str(e)[:120]}}
        d["errs"].append("hw.gpu")
    try:
        d["hw"].update(collect_cpu_mem())
    except Exception as e:                                            # noqa: BLE001
        d["hw"].update({"cpu": {"util": 0, "cores": 0, "load1": 0.0, "err": str(e)[:120]},
                        "mem": {"used_gb": 0.0, "total_gb": 0.0}})
        d["errs"].append("hw.cpu_mem")
    try:
        d["hw"]["disk"] = collect_disk()
    except Exception as e:                                            # noqa: BLE001
        d["hw"]["disk"] = {"used_gb": 0, "total_gb": 0, "pct": 0, "err": str(e)[:120]}
        d["errs"].append("hw.disk")
    try:
        d["models"] = collect_models()
    except Exception as e:                                            # noqa: BLE001
        d["models"] = [{"layer": "L2", "name": "models 采集降级", "version": "unknown",
                        "state": "untrained", "inferring": False, "err": str(e)[:120]}]
        d["errs"].append("models")
    try:
        d["training"] = collect_training()
    except Exception as e:                                            # noqa: BLE001
        d["training"] = {"active": False, "layer": "", "name": "", "version": "",
                         "step": 0, "total": 0, "pct": 0, "eta_s": 0,
                         "speed_s_per_step": 0.0, "err": str(e)[:120]}
        d["errs"].append("training")
    try:
        d["assets"] = collect_assets()
    except Exception as e:                                            # noqa: BLE001
        d["assets"] = [{"kind": "3DGS", "name": "assets 采集降级", "version": "unknown",
                        "path": "", "err": str(e)[:120]}]
        d["errs"].append("assets")
    if not d["errs"]:
        d.pop("errs")
    else:
        d["err"] = "降级: " + ",".join(d["errs"])
    return d


def _loop():
    while True:
        try:
            data = _collect_all()
            with _lock:
                _cache["ts"] = time.time()
                _cache["data"] = data
                _state["err"] = None
        except Exception as e:                                        # noqa: BLE001
            with _lock:
                _state["err"] = "%s: %s" % (type(e).__name__, e)
        time.sleep(INTERVAL)


def start():
    """起后台刷新线程 (幂等)。sam3_seg 服务启动时调一次。"""
    global _thread
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    _thread = threading.Thread(target=_loop, name="status-hub", daemon=True)
    _thread.start()


def snapshot(ttl: float = CACHE_TTL) -> dict:
    """/status/all 用: 只读快照 (<50ms)。缓存过期才同步补一次 (保险, 正常走后台线程)。"""
    start()
    with _lock:
        data, ts = _cache["data"], _cache["ts"]
    if data is not None and (time.time() - ts) <= max(ttl, 2.0):
        return data
    try:                                                              # 后台没跑起来时的兜底
        data = _collect_all()
        with _lock:
            _cache["ts"] = time.time()
            _cache["data"] = data
        return data
    except Exception as e:                                            # noqa: BLE001
        # 极端兜底: 返回一份全降级契约, 绝不抛异常
        return {"ts": time.time(),
                "hw": {"gpu": {"util": 0, "mem_used_mb": 0, "mem_total_mb": 0, "temp_c": 0, "name": "unknown"},
                       "cpu": {"util": 0, "cores": os.cpu_count() or 0, "load1": 0.0},
                       "mem": {"used_gb": 0.0, "total_gb": 0.0},
                       "disk": {"used_gb": 0, "total_gb": 0, "pct": 0}},
                "models": [{"layer": "L2", "name": "status_hub 兜底", "version": "unknown",
                            "state": "untrained", "inferring": False}],
                "training": {"active": False, "layer": "", "name": "", "version": "", "step": 0,
                             "total": 0, "pct": 0, "eta_s": 0, "speed_s_per_step": 0.0},
                "assets": [],
                "err": "snapshot: %s: %s" % (type(e).__name__, e)}


if __name__ == "__main__":
    import pprint
    pprint.pprint(_collect_all())
