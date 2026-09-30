#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HF 模型缓存瘦身: 删掉「本机代码零引用的格式导出」(如 onnx/), 顺带清悬空 blob。

判据 (先做, 别跳):
  1. `grep -rn "onnx" --include=*.py <项目代码> ~/.hermes/scripts` 若无**加载**引用 (只当关键词/正则不算)
     ⇒ 该格式导出纯占地; 运行时真正吃的是 model.safetensors + config + tokenizer。
  2. `du -sh <模型目录>/blobs <模型目录>/snapshots` — snapshots 里全是符号链接 (几十 KB),
     体积全在 blobs ⇒ 可按「是否被某个 snapshot 链接引用」判定可删性。

用法:
  python3 hf_prune_onnx.py ~/.cache/huggingface/hub/models--<org>--<name> [--dry] [--keep decoder_model_merged.onnx]

删法 (两段式, 保证不留断链):
  ① 删 snapshots/*/onnx/* 符号链接 (及空目录)  ② 删「不再被任何 snapshot 引用」的 blob。
复核: find <目录> -xtype l 必须为空; model.safetensors / config.json / tokenizer* 仍在。
重下:  hf download <repo_id> --include 'onnx/*'
"""
from __future__ import annotations

import glob
import os
import sys

SUB = "onnx"          # 要清的子目录 (按需改)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    keep = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--keep" and i + 1 < len(sys.argv)]
    if not args:
        print(__doc__)
        return 2
    base = os.path.expanduser(args[0]).rstrip("/")
    if not os.path.isdir(base):
        print(f"❌ 目录不存在: {base}")
        return 2
    snaps = glob.glob(os.path.join(base, "snapshots", "*"))
    if not snaps:
        print(f"❌ 没有 snapshot: {base}")
        return 2

    links, skipped = [], 0
    for s in snaps:
        for p in glob.glob(os.path.join(s, SUB, "*")):
            if os.path.basename(p) in keep:
                skipped += 1
                continue
            links.append(p)
    print(f"{SUB}/ 链接 {len(links)} 个 (保留 {skipped})" + ("  [DRY]" if dry else ""))
    for p in links:
        print(f"  rm link {p.replace(base, '…')}")
        if not dry:
            os.remove(p)
    for s in snaps:
        d = os.path.join(s, SUB)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)

    keepset = set()
    for s in snaps:
        for root, _d, files in os.walk(s):
            for f in files:
                p = os.path.join(root, f)
                if os.path.islink(p):
                    keepset.add(os.path.basename(os.path.realpath(p)))

    freed = 0
    for p in sorted(glob.glob(os.path.join(base, "blobs", "*"))):
        if os.path.basename(p) in keepset:
            continue
        sz = os.path.getsize(p)
        freed += sz
        print(f"  rm blob {os.path.basename(p)[:16]}… {sz/1e6:.1f}MB (无引用)")
        if not dry:
            os.remove(p)
    print(f"释放 {freed/1e9:.2f} GB" + (" (dry-run, 未真删)" if dry else ""))

    # 复核
    broken = [p for p in glob.glob(os.path.join(base, "snapshots", "*", "**", "*"), recursive=True)
              if os.path.islink(p) and not os.path.exists(p)]
    print(f"复核: 断链 {len(broken)} 个" + (f" ❌ {broken[:3]}" if broken else " ✅"))
    print("别忘了确认 model.safetensors / config.json / tokenizer* 仍在, 并记下重下命令。")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
