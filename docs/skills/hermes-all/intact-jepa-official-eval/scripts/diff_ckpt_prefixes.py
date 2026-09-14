#!/usr/bin/env python3
"""逐 key 比对两份(或多份)检查点, 按 **key 前缀** 分组 —— 用于回答
"这四个任务权重到底是不是同一套模型 / 有没有共享编码器"。

用法:
  python diff_ckpt_prefixes.py <基准.pt> <其他1.pt> [其他2.pt ...]

坑 (我踩过): 别用 `"encoder" in key` 这种子串判断来分组 —— `action_encoder.*` 会被算进"编码器",
于是四份哈希全不同, 得出"编码器根本没共享"的错结论。必须 `key.split(".")[0]` 取前缀。
"""
import sys, os
import torch


def load_sd(path):
    ck = torch.load(path, map_location="cpu", weights_only=False)
    sd = ck.get("model", ck.get("state_dict", ck)) if isinstance(ck, dict) else ck
    return {k: v for k, v in sd.items() if hasattr(v, "shape")}


def prefixes(sd):
    out = {}
    for k in sd:
        out.setdefault(k.split(".")[0], 0)
        out[k.split(".")[0]] += 1
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    base_p, others = argv[1], argv[2:]
    base = load_sd(base_p)
    print(f"基准 {os.path.basename(os.path.dirname(base_p))}/{os.path.basename(base_p)} "
          f"({os.path.getsize(base_p)} B, {len(base)} 张量)")
    print("  前缀分布:", dict(sorted(prefixes(base).items(), key=lambda x: -x[1])))
    for op in others:
        o = load_sd(op)
        same = diff = 0
        per_prefix = {}          # 前缀 -> [相同, 不同]
        maxd = 0.0
        for k in base:
            if k not in o:
                continue
            a, b = base[k].float(), o[k].float()
            eq = a.shape == b.shape and torch.equal(a, b)
            p = k.split(".")[0]
            s = per_prefix.setdefault(p, [0, 0])
            if eq:
                same += 1; s[0] += 1
            else:
                diff += 1; s[1] += 1
                if a.shape == b.shape:
                    maxd = max(maxd, float((a - b).abs().max()))
        tag = os.path.basename(os.path.dirname(op))
        print(f"\n{tag:<44s} 相同 {same:3d} / 不同 {diff:3d}   最大绝对差 {maxd:.4g}")
        for p, (s, d) in sorted(per_prefix.items(), key=lambda x: -x[1][1]):
            mark = "★完全一致=共享" if d == 0 else "任务相关"
            print(f"    {p:<16s} 相同 {s:3d} 不同 {d:3d}   {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
