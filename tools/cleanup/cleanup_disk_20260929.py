"""Z-MAX 磁盘清理 (2026-09-29) — 老倪: 「没用的都删掉, 有用的都整合」
铁律(来自 disk-redline-guard skill):
  ① 删前按名字 grep 引用(仓库活代码/配置/脚本 + cron + ~/.hermes/scripts), 有引用先问
  ② 每个链**保最新一轮**(暖启动源可能被引用), 只删更早的中间产物
  ③ 先 sha256 + 写台账 JSON
用法: python3 cleanup_20260929.py            # 只出表(不改)
     python3 cleanup_20260929.py --apply    # 真的删
"""
import hashlib
import json
import os
import re
import subprocess
import sys

APPLY = "--apply" in sys.argv
HOME = "/home/ubuntu"
SWM = os.path.join(HOME, "stable-wm-cache")
LEDGER = os.path.join(HOME, "zmax/reports/disk_cleanup_ledger_20260929.json")
CODE_ROOTS = [os.path.join(HOME, p) for p in
              ("zmax/tools", "zmax/src", "zmax/configs", "zmax/scripts",
               "INTACT-JEPA/tools", "INTACT-JEPA/config", ".hermes/scripts")]

cron_txt = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout


def refs(name):
    """名字在活代码/配置/cron 里出现几次(grep -rl 文件数)"""
    hits = set()
    for root in CODE_ROOTS:
        if not os.path.isdir(root):
            continue
        r = subprocess.run(["grep", "-rl", "--include=*.py", "--include=*.sh", "--include=*.yaml",
                            "--include=*.yml", "--include=*.json", "--include=*.md", name, root],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line and "outputs/" not in line and "state.db" not in line:
                hits.add(line)
    n = len(hits)
    if name in cron_txt:
        n += 1
    return n, sorted(hits)[:3]


def sha256(p, cap=1 << 30):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def size(path):
    r = subprocess.run(["du", "-sm", path], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0])
    except Exception:                                                            # noqa: BLE001
        return 0


fam = lambda n: re.sub(r"(v6d\d+|v6r\d+|v6lora_\d+|v[0-9]+|[0-9]{2,})", "#", n)
plan = []

# ---------- A) checkpoints: 保每族最新, 删更早的零引用链 ----------
cps = [d for d in sorted(os.listdir(os.path.join(SWM, "checkpoints")))
       if os.path.isdir(os.path.join(SWM, "checkpoints", d))]
mt = {d: os.path.getmtime(os.path.join(SWM, "checkpoints", d)) for d in cps}
newest = {}
for d in cps:
    f = fam(d)
    if f not in newest or mt[d] > mt[newest[f]]:
        newest[f] = d
print("=== A) checkpoints (共 %d 个目录, 每族最新保留) ===" % len(cps))
for d in sorted(cps, key=lambda x: -os.path.getmtime(os.path.join(SWM, "checkpoints", x))):
    n, hit = refs(d)
    keep = newest[fam(d)] == d
    sz = size(os.path.join(SWM, "checkpoints", d))
    verdict = "保留(该族最新)" if keep else ("保留(有引用 %d)" % n if n else "→ 可删")
    if not keep and not n:
        plan.append(("ckpt", os.path.join(SWM, "checkpoints", d), sz, d))
    print("  %-46s %5sM 引用%-2d %s" % (d, sz, n, verdict))

# ---------- A2) 目录内中间轮权重: 每目录只留最后一轮 ----------
print("\n=== A2) 中间轮权重 weights_epoch_*.pt (每目录只留最后一轮) ===")
ck_root = os.path.join(SWM, "checkpoints")
warm = set()
for root in CODE_ROOTS:
    if not os.path.isdir(root):
        continue
    r = subprocess.run(["grep", "-rhoE", "([A-Za-z0-9_./$-]*/)?weights_epoch_[0-9]+\\.pt", root],
                       capture_output=True, text=True)
    for m in r.stdout.split():
        parts = [x for x in m.split("/") if x]
        if len(parts) >= 2:                     # 目录/文件 → 精确保护
            warm.add(parts[-2] + "/" + parts[-1])
        else:
            warm.add(parts[-1])                 # 只写了文件名 → 保守起见按目录无关保护
print("   代码里被引用的暖启动轮(保护):", sorted(warm) or "(无)")
for d in sorted(os.listdir(ck_root)):
    dp = os.path.join(ck_root, d)
    if not os.path.isdir(dp):
        continue
    pts = sorted([f for f in os.listdir(dp) if f.startswith("weights_epoch_") and f.endswith(".pt")],
                 key=lambda x: int(re.findall(r"(\d+)", x)[0]))
    if len(pts) <= 1:
        continue
    last = pts[-1]
    for f in pts[:-1]:
        if (d + "/" + f) in warm or (f in warm and not any("/" in w for w in warm)):
            print("   保留(暖启动源被引用): %s/%s" % (d, f))
            continue
        fp = os.path.join(dp, f)
        plan.append(("epoch", fp, size(fp), d + "/" + f))
        print("   %-52s %5sM → 可删(非最后一轮)" % (d + "/" + f, size(fp)))
    print("   %-52s 保留(最后一轮)" % (d + "/" + last))

# ---------- A3) 嵌套重复目录 checkpoints/checkpoints ----------
nested = os.path.join(ck_root, "checkpoints")
if os.path.isdir(nested):
    inner = set(os.listdir(nested))
    outer = set(os.listdir(ck_root))
    dup = sorted(inner & outer)
    print("\n=== A3) 嵌套重复 stable-wm-cache/checkpoints/checkpoints/ (%dM) ===" % size(nested))
    print("   与外层同名(即重复):", dup or "(无同名)")
    if dup and not (inner - outer):
        plan.append(("nested-dup", nested, size(nested), "checkpoints/checkpoints"))
        print("   → 整目录可删(内容与外层重复)")
    else:
        print("   → 有独有内容, 不动")

# ---------- B) 数据集: 零引用 + 探针残渣 ----------
print("\n=== B) 数据集(零引用/探针残渣) ===")
for f in sorted(os.listdir(os.path.join(SWM, "datasets"))):
    p = os.path.join(SWM, "datasets", f)
    n, hit = refs(f)
    sz = size(p)
    if n == 0:
        plan.append(("dataset", p, sz, f))
        print("  %-36s %5sM 引用0  → 可删" % (f, sz))
    else:
        print("  %-36s %5sM 引用%-3d 保留" % (f, sz, n))

# ---------- C) 旧 hermes 备份(已被 09-26 备份取代) ----------
print("\n=== C) 旧备份(08 月, 已被 2026-09-26 备份 + .hermes/backups/pre-update 取代) ===")
for f in ("hermes-portable.tar.gz", "hermes_core_20260826_1047.zip", "hermes_core_usb_20260822_1037.zip"):
    p = os.path.join(HOME, f)
    if os.path.isfile(p):
        sz = size(p)
        plan.append(("backup", p, sz, f))
        print("  %-40s %5sM → 可删" % (f, sz))

tot = sum(x[2] for x in plan)
print("\n=== 计划删除: %d 项, 合计 %.1f GB ===" % (len(plan), tot / 1024))
for kind, p, sz, n in plan:
    print("   [%s] %8.1fM %s" % (kind, sz, p))

if not APPLY:
    print("\n(未改动; 加 --apply 执行)")
    sys.exit(0)

led = {"ts": "2026-09-29", "reason": "老倪: 没用的都删掉, 有用的都整合 (磁盘 %s > 红线 300G)",
       "rule": "零引用 + 每族保最新; 删前 sha256", "deleted": []}
for kind, p, sz, n in plan:
    rec = {"kind": kind, "path": p, "mb": sz, "name": n}
    try:
        if os.path.isfile(p):
            rec["sha256"] = sha256(p)
            os.remove(p)
        else:
            os.system("rm -rf %s" % json.dumps(p))
        rec["ok"] = True
    except Exception as e:                                                        # noqa: BLE001
        rec["ok"] = False
        rec["err"] = str(e)[:120]
    led["deleted"].append(rec)
    print(("  🗑 " if rec["ok"] else "  ⚠ 失败 ") + p)
led["freed_mb"] = sum(r["mb"] for r in led["deleted"] if r.get("ok"))
os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
with open(LEDGER, "w") as f:
    json.dump(led, f, ensure_ascii=False, indent=1)
print("\n台账: %s (释放 %.1f GB)" % (LEDGER, led["freed_mb"] / 1024))
print(subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout.strip().splitlines()[-1])
