#!/usr/bin/env python3
"""扫出"用墙钟差值做节拍/新鲜度判据"的反模式 —— 时钟被 NTP 回拨时会静默冻死它们。

用法:
    python3 audit_wall_clock_cadence.py <repo_or_dir> [<dir> ...]
    python3 audit_wall_clock_cadence.py ~/lerobot-smolvla-lew --quiet   # 只打印危险项

判读 (三类):
  [DAEMON]  文件里有 `while True` / rclpy Node / QTimer 等常驻形态, 且判据是 time.time() 差值
            → 时钟回拨后判据反转 = 采样停摆 / 永久 continue。**必须改 time.monotonic()**。
  [AGE]     `age = time.time() - mtime/t` 且后面有 `age <= 阈值` 之类的采信判据
            → 回拨后 age 为负 → 静止旧帧被判"新鲜"。**必须 `age < 0` 一律拒用**。
  [BOUNDED] 一次性超时循环 (`while time.time() - t0 < 30`, `--seconds`, `--duration`)
            → 只被拉长, 不会冻死, 可以不动。

退出码: 发现 DAEMON/AGE 危险项 → 1 (可当 CI/巡检闸门); 否则 0。

背景与处置流程: references/clock-step-freezes-daemons-and-freshness.md
"""
import os
import re
import sys

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages",
             "gui-venv311", "lerobot-venv", ".mypy_cache", "dist", "build"}

DAEMON_HINT = re.compile(r"while\s+True\s*:|rclpy\.(init|spin)|QTimer|def\s+main\s*\(")
CADENCE = re.compile(r"time\.time\(\)\s*-\s*[\w\.\[\]'\"]+\s*(>=|<=|>|<)")
AGE_ASSIGN = re.compile(r"\b(age\w*|_age\w*)\s*=\s*time\.time\(\)\s*-")
FRESH_CMP = re.compile(r"(age\w*|_age\w*)\s*(<=|<|>=)\s*[\w\.]*(FRESH|fresh|threshold|阈值|fresh_s)")


def scan(root):
    daemon, age, bounded = [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue
            is_daemon = any(DAEMON_HINT.search(ln) for ln in lines)
            has_fresh_cmp = any(FRESH_CMP.search(ln) for ln in lines)
            for i, ln in enumerate(lines, 1):
                s = ln.strip()
                if s.startswith("#") or s.startswith('"'):
                    continue
                if CADENCE.search(ln):
                    (daemon if is_daemon else bounded).append((p, i, s))
                if AGE_ASSIGN.search(ln) and has_fresh_cmp:
                    age.append((p, i, s))
    return daemon, age, bounded


def main(argv):
    quiet = "--quiet" in argv
    roots = [a for a in argv[1:] if not a.startswith("-")] or [os.getcwd()]
    all_d, all_a, all_b = [], [], []
    for r in roots:
        if not os.path.isdir(r):
            print(f"跳过 (不是目录): {r}")
            continue
        d, a, b = scan(os.path.abspath(r))
        all_d += d
        all_a += a
        all_b += b

    def dump(title, rows):
        if rows and not (quiet and title.startswith("BOUNDED")):
            print(f"\n── {title} ({len(rows)}) ──")
            for p, i, s in rows:
                print(f"  {p}:{i}\n      {s[:160]}")

    dump("DAEMON 常驻循环里的墙钟节拍判据 → 必须改 time.monotonic()", all_d)
    dump("AGE 帧龄可能为负 → 采信判据前必须先排除 age < 0", all_a)
    dump("BOUNDED 一次性超时循环 → 无害 (可用 --quiet 隐藏)", all_b)

    bad = len(all_d) + len(all_a)
    print(f"\n汇总: DAEMON={len(all_d)} AGE={len(all_a)} BOUNDED={len(all_b)} "
          f"→ {'有危险项, 逐条改单调钟/拒负龄' if bad else '未发现危险项 ✅'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
