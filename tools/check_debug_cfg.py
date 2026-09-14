#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 调试配置一致性自检 (老倪: "把调试配置先改好" 之后的回归闸)

查四件事, 全过才算配置是好的:
  ① 4 个 INTACT 调试配置都指向**稳定指针** `intact_l4_current` (不是写死的轮次/epoch)
     + runtime=root + device=cpu (不抢训练显存)
  ② `intact_l4_current/` 满足官方 `load_pretrained` 的**文件夹**格式要求:
     恰好一个 .pt + config.json  (多个 .pt 会 ValueError: Ambiguous checkpoint)
  ③ 指针能解析到真实文件 (软链没断) 且尺寸合理
  ④ **GUI 生成模板与 .vscode/launch.json 一致** (右键"打开 VSCode"会用模板重写 launch.json,
     两边不一致 → 下次右键就把配置改回去了), 且模板里不再有写死轮次的权重默认值

用法: python3 tools/check_debug_cfg.py     (退出码 0 = PASS)
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LJ = os.path.join(ROOT, ".vscode", "launch.json")
TPL = os.path.join(ROOT, "tools", "gui", "simulink_module.py")
CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
PTR_NAME = "intact_l4_current"
PTR = os.path.join(CACHE, "checkpoints", PTR_NAME)
fails = []


def chk(cond, ok_msg, bad_msg):
    print(("  ✅ " if cond else "  ❌ ") + (ok_msg if cond else bad_msg))
    if not cond:
        fails.append(bad_msg)


print("=== ① 4 个 INTACT 调试配置 ===")
try:
    cfg = json.load(io.open(LJ, encoding="utf-8"))
except Exception as e:
    print(f"  ❌ launch.json 解析失败: {e}")
    sys.exit(2)
ints = [c for c in cfg["configurations"] if "INTACT" in c.get("name", "")]
chk(len(ints) == 4, f"{len(ints)} 个配置 (期望 4)", f"INTACT 调试配置只有 {len(ints)} 个")
for c in ints:
    e = c.get("env") or {}
    a = " ".join(c.get("args") or [])
    pol = e.get("INTACT_POLICY") or (re.search(r"--policy\s+(\S+)", a).group(1) if "--policy" in a else "")
    good = pol == PTR_NAME and e.get("INTACT_RUNTIME") == "root" and e.get("INTACT_DEVICE") == "cpu"
    chk(good, f"{c['name'][:40]}: policy={pol} runtime=root device=cpu",
        f"{c['name'][:40]}: policy={pol or '(空)'} runtime={e.get('INTACT_RUNTIME')} device={e.get('INTACT_DEVICE')}")

print("=== ② 指针目录满足官方文件夹格式 ===")
pts = sorted(glob.glob(os.path.join(PTR, "*.pt")))
chk(len(pts) == 1, f"恰好 1 个 .pt: {[os.path.basename(p) for p in pts]}",
    f"有 {len(pts)} 个 .pt → 官方 _resolve_folder 会报 Ambiguous checkpoint")
chk(os.path.isfile(os.path.join(PTR, "config.json")), "config.json 在位", "缺 config.json → 加载必失败")

print("=== ③ 指针对得上真实文件 ===")
tgt = os.path.realpath(pts[0]) if pts else ""
sz = os.path.getsize(tgt) if tgt and os.path.isfile(tgt) else 0
chk(sz > 1_000_000, f"{os.path.relpath(tgt, CACHE)} ({sz:,} B)", f"软链断了或文件缺失: {tgt}")

print("=== ④ 模板 vs launch.json 一致 ===")
lj, tpl = io.open(LJ, encoding="utf-8").read(), io.open(TPL, encoding="utf-8").read()
# 只比"配置项"本身, 不比注释 (注释里提到指针名/老权重名不算配置 → 上一版自检器就误报在这)
code_lines = [ln for ln in tpl.splitlines() if not ln.lstrip().startswith("#")]
tpl_code = "\n".join(code_lines)
tpl_env = re.findall(r'"INTACT_POLICY"\s*[:,]\s*"([^"]+)"', tpl_code)          # env 条目 + get() 默认
tpl_args = re.findall(r'"--policy",\s*"([^"]+)"', tpl_code)
lj_env = [(c.get("env") or {}).get("INTACT_POLICY") for c in ints]
lj_args = [a for c in ints for a in (c.get("args") or []) if a != "--policy" and "weights" not in a and a != PTR_NAME]
n_lj_env = sum(1 for v in lj_env if v == PTR_NAME)
n_lj_args = sum(1 for c in ints if any(a == PTR_NAME for a in (c.get("args") or [])))
n_tpl_env = sum(1 for v in tpl_env if v == PTR_NAME)
n_tpl_args = sum(1 for v in tpl_args if v == PTR_NAME)
chk(n_lj_env == 4 and n_tpl_env == 5,   # 模板 5 = 4 个 env + 1 个引擎 L4 档默认
    f"env 指针数一致 (launch {n_lj_env}/4 · 模板 {n_tpl_env}/5 含引擎默认)",
    f"env 指针数不一致: launch {n_lj_env}/4 · 模板 {n_tpl_env}/5")
chk(n_lj_args == n_tpl_args == 1,
    f"桥 --policy 参数一致 ({n_lj_args} 处)",
    f"桥 --policy 参数不一致: launch {n_lj_args} · 模板 {n_tpl_args}")
stale_env = sorted({v for v in tpl_env + lj_env if v and v != PTR_NAME})
chk(not stale_env, "无任何写死/过期的 INTACT_POLICY", f"仍写死: {stale_env}")
stale_args = sorted({v for v in tpl_args if v != PTR_NAME})
chk(not stale_args, "无写死 --policy", f"仍写死: {stale_args}")
# 每个配置都必须显式 INTACT_RUNTIME=root —— 曾经漏过一处, 被 GUI 右键重写 launch.json 抹掉后才发现
n_rt_tpl = tpl_code.count('"INTACT_RUNTIME": "root"')
n_rt_lj = sum(1 for c in ints if (c.get("env") or {}).get("INTACT_RUNTIME") == "root")
chk(n_rt_tpl == 4 and n_rt_lj == 4,
    f"INTACT_RUNTIME=root 四处齐全 (模板 {n_rt_tpl} · launch {n_rt_lj})",
    f"INTACT_RUNTIME 缺失: 模板 {n_rt_tpl}/4 · launch {n_rt_lj}/4 (右键重写会抹掉模板里没有的键)")
# 引擎 L4 档默认 (运行路径) 也必须是指针
m = re.search(r'os\.environ\.get\("INTACT_POLICY",\s*"([^"]+)"\)', tpl_code)
chk(bool(m) and m.group(1) == PTR_NAME,
    f"引擎 L4 档默认权重 = {m.group(1) if m else '(未找到)'}",
    f"引擎 L4 档默认权重过期: {m.group(1) if m else '(未找到)'}")

print()
if fails:
    print(f"❌ FAIL · {len(fails)} 项不过")
    sys.exit(1)
print("✅ PASS · 调试配置全部指向稳定指针且两处一致")
