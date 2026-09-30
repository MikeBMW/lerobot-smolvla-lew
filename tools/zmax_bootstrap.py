#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 基线自检 / 首次 clone 初始化 (Linux 工位机)

一句话: 把 zmax 仓库 clone 下来之后跑这个, 它告诉你「哪些模型/数据本机已经有了(绝不重下)、
哪些缺、缺的怎么取」, 并把运行时目录骨架和本机路径约定铺好。

用法:
  python3 tools/zmax_bootstrap.py                 # 只体检+识别, 不动任何东西 (默认)
  python3 tools/zmax_bootstrap.py --apply         # 建目录骨架 + 写 zmax_paths.env + 采纳旧路径(软链)
  python3 tools/zmax_bootstrap.py --download      # 只下"缺失且必需"的资产(走 hf-mirror)
  python3 tools/zmax_bootstrap.py --apply --smoke # 铺好后跑状态空间功能自检
  python3 tools/zmax_bootstrap.py --secrets       # 生成本机密钥占位文件(不含真值)
  python3 tools/zmax_bootstrap.py --systemd       # 装 systemd 单元(需 sudo)

设计口径:
  · **只读优先**: 不带 --apply 时一个字节都不写。
  · **已下载的绝不重下**: 默认路径没有就看 alt_paths(老机器上的历史位置) → 报"可采纳", --apply 时软链过去。
  · 缺的东西: 打印**确切的下载命令**, 不偷偷下 100G。
  · 退出码: 必需资产齐了 0; 有必需项缺 → 1 (方便 CI/脚本判)。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # /home/ubuntu/zmax
MANIFEST = os.path.join(HERE, "zmax_assets.json")

C_OK, C_WARN, C_BAD, C_DIM, C_END = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)


def env_paths():
    """路径约定: 环境变量优先, 否则用 /home/ubuntu 下的标准位置。"""
    data = os.environ.get("ZMAX_DATA") or "/home/ubuntu/zmax_data"
    p = {
        "ZMAX_CODE": os.environ.get("ZMAX_CODE") or ROOT,
        "ZMAX_DATA": data,
        "ZMAX_MODELS": os.environ.get("ZMAX_MODELS") or os.path.join(data, "models"),
        "ZMAX_HF_HOME": os.environ.get("ZMAX_HF_HOME") or os.path.join(data, "hf_cache"),
        "STABLEWM_HOME": os.environ.get("STABLEWM_HOME") or os.path.join(data, "stable-wm-cache"),
        "ZMAX_SECRETS": os.environ.get("ZMAX_SECRETS") or os.path.join(data, "secrets"),
        "ZMAX_REPOS": os.environ.get("ZMAX_REPOS") or "/home/ubuntu",
    }
    return p


def expand(s, P):
    for k, v in P.items():
        s = s.replace("${%s}" % k, v)
    return os.path.expanduser(s)


def size_of(p):
    """人类可读体积(文件=stat, 目录=du -sh)。"""
    if os.path.isfile(p):
        b = os.path.getsize(p)
    elif os.path.isdir(p):
        out = sh(["du", "-sb", p]).stdout.split()
        b = int(out[0]) if out and out[0].isdigit() else 0
    else:
        return None
    for u, s in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if b >= s:
            return "%.1f%s" % (b / s, u)
    return "%dB" % b


def hf_bin():
    for c in (os.path.join(ROOT, "gui-venv311", "bin", "hf"), "/home/ubuntu/lerobot-venv/bin/hf",
              "/home/ubuntu/dds-venv/bin/hf", shutil.which("hf") or ""):
        if c and os.path.exists(c):
            return c
    return ""


def check_asset(a, P):
    """返回 (状态, 说明, 采纳来源) —— 状态 ∈ default/alt/missing。"""
    d = expand(a["path"], P)
    if os.path.exists(d) and (not os.path.isdir(d) or os.listdir(d)):
        return "default", d, ""
    for g in a.get("alt_globs") or []:            # 先看精确文件命中(glob), 再看目录型老位置
        import glob as _g
        hits = [h for h in sorted(_g.glob(expand(g, P), recursive=True)) if os.path.isfile(h)]
        if hits:
            return "alt", d, hits[0]
    for alt in a.get("alt_paths") or []:
        ap = expand(alt, P)
        if os.path.exists(ap) and (not os.path.isdir(ap) or os.listdir(ap)):
            return "alt", d, ap
    # HF 缓存类: 老机器的 ~/.cache/huggingface 也算已下载
    if "hf_cache" in a["path"] or "huggingface" in a.get("path", "") or "huggingface" in " ".join(a.get("alt_paths") or []):
        legacy = os.path.expanduser("~/.cache/huggingface")
        rel = os.path.basename(d)
        if os.path.isdir(os.path.join(legacy, "hub", rel)):
            return "alt", d, os.path.join(legacy, "hub", rel)
    return "missing", d, ""


def display(a, st, dest, src, P):
    """体积/状态展示: env 类资产报"版本/数量", 运行目录报子目录数, 不报误导性的 du。"""
    k = a.get("kind")
    if k == "venv" or a["id"] == "venvs":
        vers = []
        for p in [os.path.join(ROOT, "gui-venv311"), "/home/ubuntu/lerobot-venv", "/home/ubuntu/dds-venv"]:
            b = os.path.join(p, "bin", "python")
            if os.path.exists(b):
                vers.append(sh([b, "--version"]).stdout.strip().replace("Python ", "py"))
        return "已建 venv: " + ("/".join(vers) if vers else "无(需 python3 -m venv)")
    if k == "runtime":
        n = sum(os.path.isdir(expand(os.path.join(P["ZMAX_DATA"], x), P)) for x in (a.get("fetch") or {}).get("dirs") or [])
        return "目录骨架 %d/13 就位" % n
    if a["id"] == "systemd_units":
        sd = os.path.join(ROOT, "tools", "systemd")
        return "%d 个单元源在库" % len([x for x in os.listdir(sd) if x.endswith(".service")]) if os.path.isdir(sd) else "缺"
    if st == "missing":
        return "0 (缺)"
    return size_of(dest if st == "default" else src) or "?"


def fetch_cmd(a, P, dest):
    f = a.get("fetch") or {}
    m = f.get("method")
    hf = hf_bin()
    if m == "hf":
        parts = ['HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"', "HF_HOME=%s" % P["ZMAX_HF_HOME"]]
        inc = " ".join("--include '%s'" % i for i in (f.get("include") or []))
        cmd = "%s %s download %s%s --local-dir %s" % (" ".join(parts), hf or "hf", f["repo"], (" " + inc) if inc else "", dest)
        if f.get("gated"):
            cmd = "HF_TOKEN=<你的HF令牌> " + cmd
        return cmd
    if m == "hf-dataset":
        return "HF_ENDPOINT=\"${HF_ENDPOINT:-https://hf-mirror.com}\" %s download %s %s --local-dir %s" % (
            hf or "hf", f["repo"], f.get("file", ""), expand(str(f.get("unpack_to", dest)), P))
    if m == "url":
        return "curl -L --retry 3 -o %s %s" % (dest, (f.get("urls") or [""])[0])
    if m == "mkdir":
        return "mkdir -p " + " ".join(expand(os.path.join(P["ZMAX_DATA"], d), P) for d in f.get("dirs") or [])
    if m == "venv":
        return "python3 -m venv --system-site-packages /home/ubuntu/lerobot-venv && /home/ubuntu/lerobot-venv/bin/pip install -r requirements-train.txt"
    if m == "systemd":
        return "sudo cp tools/systemd/*.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    return ""


def smoke(P):
    """状态空间功能自检: 代码能不能导入、关键文件在不在、服务端口通不通。"""
    print("\n状态空间功能自检")
    cands = [os.path.join(P["ZMAX_CODE"], "gui-venv311", "bin", "python"),
             os.environ.get("ZMAX_PY") or "", "/home/ubuntu/lerobot-venv/bin/python",
             "/home/ubuntu/gui-venv311/bin/python", sys.executable]
    py = next((c for c in cands if c and os.path.exists(c)), sys.executable)
    print("  解释器: %s" % py)
    mods = [
        ("左右脑-左脑建模", "lerobot.policies.left_right.modeling_left_right"),
        ("状态空间-规划器(L5)", "lerobot.policies.left_right.state_space.planner"),
        ("状态空间-安全闸", "lerobot.policies.left_right.state_space.safety"),
        ("状态空间-执行(L2收口)", "lerobot.policies.left_right.state_space.execution"),
        ("状态空间-认知(L4)", "lerobot.policies.left_right.state_space.cognition"),
        ("状态空间-场景VLM", "lerobot.policies.left_right.state_space.scene_vlm"),
        ("状态空间-动力学/李雅普诺夫", "lerobot.policies.left_right.state_space.dynamics"),
        ("SU(2) 统一表示", "lerobot.policies.left_right.state_space.su2"),
        ("原子技能", "lerobot.policies.left_right.state_space.skills.atomic_skills"),
        ("网页agent桥", "lerobot.policies.left_right.state_space.web_agent_bridge"),
    ]
    code = ("import sys; sys.path.insert(0,'%s/src');" % P["ZMAX_CODE"]) + \
           ";".join("import %s" % m for _, m in mods) + ";print('ALL_OK')"
    r = sh([py, "-c", code], cwd=P["ZMAX_CODE"])
    ok_all = "ALL_OK" in (r.stdout or "")
    for name, m in mods:
        rr = sh([py, "-c", "import sys;sys.path.insert(0,'%s/src');import %s" % (P["ZMAX_CODE"], m)], cwd=P["ZMAX_CODE"])
        err = (rr.stderr or "").strip().splitlines()
        mark = "%s✅%s" % (C_OK, C_END) if rr.returncode == 0 else "%s❌%s" % (C_BAD, C_END)
        tail = "" if rr.returncode == 0 else "   ← %s" % (err[-1][:90] if err else "导入失败")
        print("  %s %-26s %s%s" % (mark, name, m, tail))
    files = [("工位总览页面", "tools/web/station.html"), ("agent 通道", "tools/agent_hub.py"),
             ("站控命令", "tools/station_cmd.py"), ("相机守护", "tools/cam_stream_guard.py"),
             ("状态空间画布", "flows/state_space_obs.json"), ("左右脑配置", "configs/policies/config_left_right.yaml")]
    for name, rel in files:
        p = os.path.join(P["ZMAX_CODE"], rel)
        print("  %s %-26s %s" % ("%s✅%s" % (C_OK, C_END) if os.path.exists(p) else "%s❌%s" % (C_BAD, C_END), name, rel))
    for port, what in ((8793, "工位总览"), (8794, "agent 通道"), (8790, "状态空间"), (8791, "推流")):
        out = sh(["ss", "-ltn"]).stdout
        up = (":%d " % port) in out or (":%d\n" % port) in out
        print("  %s %-26s 端口 %d %s" % ("%s✅%s" % (C_OK, C_END) if up else "%s·%s" % (C_DIM, C_END), what, port, "在听" if up else "(未起, 正常: 需 --apply 后由 systemd 拉起)"))
    return ok_all


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 基线自检/首次 clone 初始化")
    ap.add_argument("--apply", action="store_true", help="建目录骨架 + 写 zmax_paths.env + 采纳旧路径")
    ap.add_argument("--download", action="store_true", help="下缺失的必需资产")
    ap.add_argument("--secrets", action="store_true", help="生成本机密钥占位文件")
    ap.add_argument("--systemd", action="store_true", help="装 systemd 单元")
    ap.add_argument("--smoke", action="store_true", help="状态空间功能自检")
    a = ap.parse_args()

    P = env_paths()
    man = json.load(open(MANIFEST, encoding="utf-8"))
    print("Z-MAX 基线自检   %s   代码根=%s" % (sh("date '+%F %H:%M'").stdout.strip(), P["ZMAX_CODE"]))
    print("%s约定: 模型→%s   HF缓存→%s   数据集→%s%s" % (C_DIM, P["ZMAX_MODELS"], P["ZMAX_HF_HOME"], P["STABLEWM_HOME"], C_END))
    print("%s      缺省可用环境变量覆盖(ZMAX_DATA / ZMAX_MODELS / HF_HOME / STABLEWM_HOME)%s\n" % (C_DIM, C_END))

    if a.secrets:
        os.makedirs(P["ZMAX_SECRETS"], mode=0o700, exist_ok=True)
        f = os.path.join(P["ZMAX_SECRETS"], "zmax.env")
        if os.path.exists(f):
            print("① 密钥文件已存在, 未覆盖: %s" % f)
        else:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("# Z-MAX 本机密钥 (不进代码库). 真值由现场填。\n"
                         "ZMAX_AGENT_TOKEN=<agent 通道 token, 逗号可多值>\n"
                         "ZMAX_ECS_PW=<ECS relay 口令>\n"
                         "ZMAX_TUNNEL_TOKEN=<公网隧道 token(只读 /ov /st)>\n"
                         "# HF_TOKEN=hf_xxx   # 下 gated 模型(facebook/sam3)用\n")
            os.chmod(f, 0o600)
            print("① 已生成密钥占位文件: %s (600, 请填真值; 不填则 agent 通道 fail-closed 不启动)" % f)

    rows, need_dl, missing_req = [], [], []
    for at in man["assets"]:
        st, dest, src = check_asset(at, P)
        sz = display(at, st, dest, src, P)
        tag = {"default": "%s✅已有%s" % (C_OK, C_END), "alt": "%s🔗可采纳%s" % (C_WARN, C_END), "missing": "%s⬇️缺%s" % (C_BAD, C_END)}[st]
        rows.append((at["id"], ",".join(at.get("needed_by") or [])[:22], dest, tag, sz, st, at))
        if st == "missing" and at.get("required"):
            missing_req.append(at)
        if st == "missing" and (at.get("fetch") or {}).get("method") in ("hf", "hf-dataset", "url"):
            need_dl.append(at)

    print("%-26s %-24s %-10s %s" % ("资产", "谁要用", "状态", "体积/默认路径"))
    print("-" * 118)
    for _id, by, dest, tag, sz, st, _ in rows:
        print("%-26s %-24s %-18s %6s  %s" % (_id, by, tag, sz, dest))

    print("\n结论: %d 项资产, 已有 %d, 可采纳(老位置) %d, 缺 %d" % (
        len(rows), sum(r[5] == "default" for r in rows), sum(r[5] == "alt" for r in rows), sum(r[5] == "missing" for r in rows)))
    if missing_req:
        auto = [x["id"] for x in missing_req if (x.get("fetch") or {}).get("method") == "mkdir"]
        print("%s❌ 必需项缺 %d 个: %s%s" % (C_BAD, len(missing_req), ", ".join(x["id"] for x in missing_req), C_END))
        if auto:
            print("   (%s 是目录骨架, 跑 --apply 会立刻建好)" % ", ".join(auto))
    else:
        print("%s✅ 必需项齐全%s" % (C_OK, C_END))

    if a.apply:
        print("\n--apply: 铺运行时骨架 + 路径约定 (只增不改不删)")
        for at in man["assets"]:
            if (at.get("fetch") or {}).get("method") == "mkdir":
                for d in at["fetch"]["dirs"]:
                    p = expand(os.path.join(P["ZMAX_DATA"], d), P)
                    os.makedirs(p, exist_ok=True)
                print("  ✅ 目录骨架 %s (%d 个)" % (P["ZMAX_DATA"], len(at["fetch"]["dirs"])))
        envf = os.path.join(P["ZMAX_DATA"], "zmax_paths.env")
        with open(envf, "w", encoding="utf-8") as fh:
            fh.write("# Z-MAX 本机路径约定 (由 tools/zmax_bootstrap.py --apply 生成)\n"
                     "# 用法: source 它, 之后所有脚本/服务都用同一套路径; 换盘只改这一个文件。\n")
            for k, v in P.items():
                fh.write("export %s=%s\n" % (k, v))
            fh.write("# 模型下载默认落这里(与 ZMAX_HF_HOME 同一套布局 hub/…)\n"
                     "export HF_HOME=%s\n" % P["ZMAX_HF_HOME"])
            fh.write("export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}\n"
                     "# 数据集/训练缓存: stable_worldmodel 读这个\n"
                     "export STABLEWM_HOME=%s\n" % P["STABLEWM_HOME"])
        print("  ✅ 已写 %s (source 一下就有全部路径变量)" % envf)
        n_link = 0
        for at in man["assets"]:
            st, dest, src = check_asset(at, P)
            if at.get("kind") in ("venv", "env") and st == "alt":
                print("  ⓘ %s: 本机已有同类环境(%s), venv 内部路径写死不能软链 —— 复用原处, 或按 %s 重建" % (
                    at["id"], src, (at.get("fetch") or {}).get("note", "")[:60]))
                continue
            if st == "alt" and src and not os.path.exists(dest):
                try:
                    if os.path.isfile(dest) or os.path.isdir(dest):
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.symlink(src, dest)
                    print("  🔗 采纳: %s → %s" % (dest, src))
                    n_link += 1
                except OSError as e:
                    print("  %s🔗 采纳失败%s %s (%s)" % (C_WARN, C_END, dest, e))
        print("  采纳软链 %d 条 (老机器上已下载的模型/数据不用重下)" % n_link)

    if a.systemd:
        units = [x for x in os.listdir(os.path.join(ROOT, "tools", "systemd")) if x.endswith(".service")]
        r = sh("sudo cp %s/tools/systemd/*.service /etc/systemd/system/ && sudo systemctl daemon-reload" % ROOT)
        print("\n--systemd: 装了 %d 个单元 (rc=%d)" % (len(units), r.returncode))
        print("  启用示例: sudo systemctl enable --now zmax-ss-remote.service zmax-agent-hub.service")

    if a.download:
        print("\n--download: 下缺失的模型/数据 (%d 项)" % len(need_dl))
        if not need_dl:
            print("  没有需要下载的(hf/url 类)资产 —— 已有的不重下。")
        for at in need_dl:
            _, dest, _ = check_asset(at, P)
            cmd = fetch_cmd(at, P, dest)
            print("▶ %s\n  %s" % (at["id"], cmd))
            r = sh("set -o pipefail; " + cmd, cwd=ROOT)
            print("  rc=%d %s" % (r.returncode, (r.stdout or r.stderr or "").strip().splitlines()[-1][:120] if (r.stdout or r.stderr) else ""))

    if a.smoke:
        smoke(P)

    if not any([a.apply, a.download, a.secrets, a.systemd, a.smoke]):
        print("\n提示: 本次是只读体检。要铺环境跑 --apply; 要下缺的模型跑 --download; 自检跑 --smoke")
        if need_dl:
            print("缺失且可下载的 %d 项——命令如下(要自动跑加 --download):" % len(need_dl))
            for at in need_dl:
                _, dest, _ = check_asset(at, P)
                print("  %-26s %s" % (at["id"], fetch_cmd(at, P, dest)))
        for at in man["assets"]:
            if (at.get("fetch") or {}).get("method") == "self" and check_asset(at, P)[0] == "missing":
                print("  %-26s 自产/现场产物(%s): %s" % (at["id"], at["kind"], at["fetch"]["note"][:80]))
    return 1 if missing_req else 0


if __name__ == "__main__":
    sys.exit(main())
