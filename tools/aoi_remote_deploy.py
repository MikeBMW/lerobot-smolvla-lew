#!/usr/bin/env python3
"""AOI 自主更新器 —— 4060(主节点) 推程序到工控机 192.168.23.23 并上线验收 (2026-09-27)

老倪要求: 主节点要能自主更新工控机程序, **只用 10082/10083**, 不用 10084/10085 试跑口。

流程(全程无人工):
  ① 程序拷进 8794 静态目录 (agent_hub --dir)
  ② 经反向通道让工控机 iwr 下载 + Get-FileHash 与本地 SHA256 逐位核对(不一致就中止, 不动产线)
  ③ 备份现役程序为 <名>.bak ④ 停旧起新(**始终 10082/10083**, 分离启动, 不受窗口关闭影响)
  ⑤ 验收(缺一即判失败): /storage 200 · /last_result 200 · POST /capture_detect 回执 code=200 ·
     GET /picture?kind=origin&grab=1 字节>0 且 /storage 的 files_total **不增长**(v5 不落盘口径)
  ⑥ 任一失败 → 用 .bak 回滚 + 重启 + 复验, 并如实报失败

用法:
  python tools/aoi_remote_deploy.py --finger ~/aoi_v4/cam_finger_10082_work_v6.py \
                                   --surface ~/aoi_v4/surface_10083_work_v5.py
  可选: --no-restart(只推文件不重启) · --dry(只做 ① ② 核对) · --pubdir <目录>
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
HUB = os.path.join(ROOT, "tools", "agent_hub.py")
# 2026-09-29: 与 agent_hub.py 的 OUT_DIR 同步搬出 /tmp(见 agent_hub.py 顶部"fs.protected_regular"说明)
OUT_DIR = "/home/ubuntu/zmax_data/agent_hub/out"
HOST = "192.168.23.50"
ILO = "192.168.23.23"
FILENAME_10082 = "cam_finger_10082_work_v6.py"
FILENAME_10083 = "cam_surface_10083_work_v6.py"


def log(msg):
    print("[deploy %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest().upper()


def newest_out():
    try:
        fs = [os.path.join(OUT_DIR, x) for x in os.listdir(OUT_DIR)]
        return max(fs, key=os.path.getmtime) if fs else None
    except OSError:
        return None


def remote(ps, wait=180, label=""):
    """经反向通道在工控机上跑一段 PowerShell, 返回回执文本。"""
    before = newest_out()
    t0 = time.time()
    r = subprocess.run([PY, HUB, "--enqueue", ps], capture_output=True, text=True)
    if r.returncode != 0:
        return "<<ENQUEUE_FAIL: %s>>" % (r.stderr or r.stdout)[:200]
    deadline = time.time() + wait
    while time.time() < deadline:
        f = newest_out()
        if f and f != before and os.path.getmtime(f) >= t0 - 1:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                pass
        time.sleep(1.0)
    return "<<TIMEOUT %s>>" % label


def http_get(url, timeout=20):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        # ⚠️ 2026-09-30 踩坑: 4xx/5xx 也说明"服务活着"。原来走 except Exception 会丢状态码(st=0),
        #    于是验收认不出 10082 那条**合法 404**("/last_result 尚无检测结果") ⇒ 首帧推理慢时假失败 ⇒ 误回滚。
        try:
            body = e.read()
        except Exception:                      # noqa: BLE001
            body = b""
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def http_post(url, timeout=90):
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def files_total(port):
    st, body = http_get("http://%s:%d/storage" % (ILO, port))
    if st != 200:
        return None
    m = re.search(rb'"files_total":\s*(\d+)', body)
    return int(m.group(1)) if m else None


def verify(port, test_capture=True):
    """验收一路; 返回 (ok, 明细 list)。"""
    out = []

    def chk(name, cond, extra=""):
        out.append(("✅ " if cond else "❌ ") + name + (" " + extra if extra else ""))
        return cond

    st, body = http_get("http://%s:%d/storage" % (ILO, port))
    ok = chk("/storage HTTP200", st == 200, "(%s)" % st)

    def _stable_total(tries=8, gap=1.5):
        """等落盘稳定(连续两次读数相同)再取基准。
        ⚠️ 2026-09-29 踩坑: 基准若在 capture_detect 的**异步 worker 还在落图**时取,
        'grab 不落盘' 会假失败 ⇒ 假失败触发**自动回滚**(危险)。实测就是这么误判过一次。"""
        last = None
        for _ in range(tries):
            cur = files_total(port)
            if cur is not None and cur == last:
                return cur
            last = cur
            time.sleep(gap)
        return last

    if test_capture:
        st, body = http_post("http://%s:%d/capture_detect" % (ILO, port))
        ok &= chk("POST /capture_detect 回执 code=200", st == 200 and b'"code":200' in body,
                  body[:80].decode("utf-8", "replace"))
        # /last_result 的两种合法形态: ①200+verdict/count ②404+「尚无检测结果」(后台推理还没跑完)
        # 表面(housing) 推理实测 ~8.9s ⇒ 轮询等, 别用固定短等待(会假失败)。2026-09-27 踩过。
        t_end = time.time() + 45
        st, body = 0, b""
        while time.time() < t_end:
            st, body = http_get("http://%s:%d/last_result" % (ILO, port))
            if st == 200:
                break
            time.sleep(3)
        # ⚠️ 2026-09-30 踩坑: Flask jsonify 默认 ensure_ascii=True ⇒ 中文在 body 里是 \u5c1a\u65e0…,
        #    只比对 UTF-8 原文会漏判"合法 404" ⇒ 首帧推理慢(要加载模型)时假失败 ⇒ **误触发自动回滚**。
        #    这里把"还没出结果"的三种形态都当合法: 原始中文 / \u 转义 / 空 body(服务刚起来)。
        _esc = "".join("\\u%04x" % ord(c) for c in "尚无检测结果")
        legal404 = st == 404 and (not body or "尚无检测结果".encode() in body or _esc.encode() in body)
        ok &= chk("/last_result 判决通道", st == 200 or legal404,
                  ("200 " if st == 200 else "404-尚无(在等/推理慢) ") + body[:60].decode("utf-8", "replace"))
    n_before = _stable_total()          # 取基准: 等检测线程落盘稳定(见 _stable_total 注释)
    st, img = http_get("http://%s:%d/picture?kind=origin&grab=1" % (ILO, port), timeout=60)
    ok &= chk("grab=1 出图", st == 200 and len(img) > 10000, "%d 字节" % len(img))
    n_after = files_total(port)
    ok &= chk("grab 不落盘(files_total 不增)", n_after is not None and n_before == n_after,
              "%s→%s" % (n_before, n_after))
    return bool(ok), out


def start_pair(restart=True):
    py = r"D:\xspace\ultralytics_AOI\venv\Scripts\python.exe"
    d = r"D:\xspace\ultralytics_AOI"
    ps = (
        'cd %s; '
        'foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
        'if($c){ Stop-Process -Id $c.OwningProcess -Force } }; Start-Sleep 4; '
        '$sh=New-Object -ComObject WScript.Shell; '
        '$sh.Run("cmd /c cd /d %s && %s cam_finger_10082_work_v6.py > %s\\v5f.log 2>&1",0,$false) | Out-Null; '
        '$sh.Run("cmd /c cd /d %s && %s cam_surface_10083_work_v6.py > %s\\v5s.log 2>&1",0,$false) | Out-Null; '
        'Start-Sleep -Seconds 40; '
        'foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
        '"$p -> " + $(if($c){"up pid " + $c.OwningProcess}else{"DOWN"}) }'
    ) % (d, d, py, d, d, py, d)
    return remote(ps, wait=200, label="start")


def stop_pair():
    ps = ('foreach($p in 10082,10083){ $c=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue; '
          'if($c){ Stop-Process -Id $c.OwningProcess -Force; "stopped $p" } }')
    return remote(ps, wait=60, label="stop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--finger", default=os.path.expanduser("~/aoi_v4/cam_finger_10082_work_v6.py"))
    ap.add_argument("--surface", default=os.path.expanduser("~/aoi_v4/cam_surface_10083_work_v6.py"))
    ap.add_argument("--pubdir", default="/home/ubuntu/aoi_v4/deliver/v6")
    ap.add_argument("--no-restart", action="store_true", help="只推文件+核对, 不动服务")
    ap.add_argument("--dry", action="store_true", help="只推文件+核对, 不重启不验收")
    a = ap.parse_args()

    pair = [(10082, a.finger, FILENAME_10082), (10083, a.surface, FILENAME_10083)]
    os.makedirs(a.pubdir, exist_ok=True)
    report = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "files": [], "verify": {}}

    # ① 拷进静态目录
    for _port, src, name in pair:
        if not os.path.exists(src):
            log("✗ 本地文件不存在: %s" % src)
            return 2
        dst = os.path.join(a.pubdir, name)
        subprocess.run(["cp", "-f", src, dst], check=True)
        log("① 已发布 %s (%d B, %s…)" % (name, os.path.getsize(dst), sha256(dst)[:8]))

    # ② 工控机下载 + SHA256 核对
    dl = ("cd D:\\xspace\\ultralytics_AOI; "
          "foreach($f in '%s','%s'){ iwr \"http://%s:%d/v6/$f\" -OutFile $f -UseBasicParsing -TimeoutSec 60 }; "
          "Get-FileHash %s,%s -Algorithm SHA256 | ForEach-Object { $_.Hash + '  ' + (Split-Path $_.Path -Leaf) }"
          ) % (FILENAME_10082, FILENAME_10083, HOST, 8794, FILENAME_10082, FILENAME_10083)
    out = remote(dl, wait=150, label="download")
    if "TIMEOUT" in out or "ENQUEUE_FAIL" in out:
        log("✗ 通道没回执(%s) —— 工控机上的 ZMAX_Agent 任务没跑? " % out)
        return 3
    ok_hash = True
    for _port, src, name in pair:
        want = sha256(os.path.join(a.pubdir, name))
        line = next((l for l in out.splitlines() if name in l), "")
        got = line.strip().split()[0].upper() if line.strip() else ""
        same = got == want
        ok_hash &= same
        log("② %s SHA256 %s (%s)" % (name, "一致" if same else "不一致!", got[:12] or "无回执"))
        report["files"].append({"name": name, "sha256_local": want, "sha256_remote": got, "same": same})
    if not ok_hash:
        log("✗ 哈希不一致 → 中止, 产线一字未动")
        return 4
    if a.dry:
        log("--dry: 到此为止 (文件已就位, 服务未动)")
        return 0

    # ③ 备份现役
    log("③ 备份现役程序为 .bak")
    remote("cd D:\\xspace\\ultralytics_AOI; foreach($f in '%s','%s'){ if(Test-Path $f){ Copy-Item $f ($f + '.bak') -Force; "
           "\"backup $f\" } else { \"no such $f\" } }" % (FILENAME_10082, FILENAME_10083), wait=60, label="backup")

    if a.no_restart:
        log("--no-restart: 文件已换, 服务未重启")
        return 0

    # ④ 停旧起新 (10082/10083)
    log("④ 重启 10082/10083 上的 v6")
    log("   " + start_pair().strip().replace("\n", " / "))

    # ⑤ 验收
    # ⚠️ 2026-09-30 踩坑: 只该用**本轮真换了文件**的那一路当判据。原来两路都当判据 ⇒
    #    另一台相机自己抽风(10083 grab 出 46 字节)会把本轮的修复误判成失败 ⇒ 触发回滚,
    #    而回滚会把**本轮新文件**换成本轮之前的内容(把刚修好的版本滚掉)。没换文件的那路只报状态。
    changed = {port for (port, _src, nm) in pair
               if any(f["name"] == nm and not f["same"] for f in report["files"])}
    ok_all = True
    for port, _src, name in pair:
        ok, detail = verify(port)
        report["verify"][str(port)] = detail
        if port not in changed:
            log("⑤ %d (本轮未换文件, 仅报状态): %s" % (port, "OK" if ok else "⚠️ 异常(与本轮改动无关)"))
            continue
        ok_all &= ok
        log("⑤ %d %s" % (port, "\n     ".join(detail)))
    log("⑤ 验收结果: %s%s" % ("全部通过 ✅" if ok_all else "有失败 ❌",
                            "" if changed else " (本轮无文件变化, 无判据)"))

    # ⑥ 失败 → 回滚
    if not ok_all:
        log("⑥ 验收失败 → 用 .bak 回滚")
        remote("cd D:\\xspace\\ultralytics_AOI; foreach($f in '%s','%s'){ if(Test-Path ($f + '.bak')){ Copy-Item ($f + '.bak') $f -Force; "
               "\"rolled back $f\" } }" % (FILENAME_10082, FILENAME_10083), wait=60, label="rollback")
        log("   " + start_pair().strip().replace("\n", " / "))
        for port, _src, _name in pair:
            ok, detail = verify(port, test_capture=False)
            log("   回滚后 %d: %s" % (port, "OK" if ok else "仍异常"))

    with open(os.path.join(ROOT, "reports", "aoi_deploy_log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0 if ok_all else 5


if __name__ == "__main__":
    sys.exit(main())
