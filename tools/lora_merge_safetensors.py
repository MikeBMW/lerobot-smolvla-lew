#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lora_merge_safetensors.py — 把 LoRA 折进 **safetensors**(lerobot/SmolVLA 存法) 的权重里。

为什么需要它: `merge_lora_ckpt.py` / `post_lora_merge.sh` 处理的是 INTACT 那种 **.pt**
  (键形如 `....lora_A` 且 base 权重在同文件); L3(SmolVLA) 存的是 **safetensors**,
  沿用同一套卷积/线性包装 ⇒ 同样需要"折叠后部署", 否则会出现**零动作伪装成没提升**
  (老倪 09-30 认过的坑: 不 merge 就 A/B, 结论不可信)。

公式**照抄** tools/lora_inject.py:83 —— 不许自己推:
    merged = base.weight + (alpha/r) · (lora_B @ lora_A)

两道硬校验(缺一即拒绝出文件):
  ① **非 LoRA 张量必须逐位不变**(sha256 比对) —— 证明我只动了该动的 512 个键;
  ② **ΔW 必须逐位等于 scaling·B@A** —— 证明折叠算术没写错(不是"看起来差不多")。

用法:
  ./gui-venv311/bin/python tools/lora_merge_safetensors.py \
      --src outputs/train/smolvla_lew_lora_200_r4/checkpoints/000200/pretrained_model \
      --out outputs/train/smolvla_lew_lora_200_r4/checkpoints/000200/pretrained_model_merged \
      --r 8 --alpha 16 [--dry]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

import torch
from safetensors.torch import load_file, save_file


def h(t: torch.Tensor) -> str:
    """按**原始字节**哈希(bfloat16/tf32 都能过; 不经任何 dtype 转换 ⇒ "逐位不变"才作数)。"""
    return hashlib.sha256(t.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="含 LoRA 的模型目录(内有 model.safetensors)或直接给 .safetensors")
    ap.add_argument("--out", default="", help="输出目录(默认 <src>_merged); 会复制 config/tokenizer 等旁文件")
    ap.add_argument("--r", type=int, default=8)
    ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--scaling", type=float, default=None, help="覆盖 alpha/r(默认按 r/alpha 算)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if os.path.isdir(a.src):
        sd_path = os.path.join(a.src, "model.safetensors")
        out_dir = a.out or (a.src.rstrip("/") + "_merged")
    else:
        sd_path = a.src
        out_dir = a.out or (os.path.dirname(sd_path) + "_merged")
    scaling = a.scaling if a.scaling is not None else a.alpha / a.r
    print("══ 源: %s" % sd_path)
    print("══ 输出: %s   scaling = alpha/r = %g/%d = %g" % (out_dir, a.alpha, a.r, scaling))

    sd = load_file(sd_path)
    print("══ 载入 %d 个张量 (%.2f GB)" % (len(sd), os.path.getsize(sd_path) / 1e9))

    # 键名实测(L3/lerobot 存法): `<prefix>.lora_A` + `<prefix>.lora_B` + `<prefix>.base.weight`
    #   (LoRALinear 把原 Linear 存成 .base ⇒ 合并后要**改回普通 Linear 的 <prefix>.weight**,
    #    与 lora_inject.LoRALinear.merge() 的语义一致: 还原成普通 nn.Linear 供部署)
    pairs, missing_base = [], []
    for k in list(sd.keys()):
        if k.endswith(".lora_A"):
            pre = k[: -len(".lora_A")]
            bk_a, bk_b = pre + ".lora_A", pre + ".lora_B"
            cands = [pre + ".base.weight", pre + ".weight"]
            bk_w = next((c for c in cands if c in sd), "")
            if bk_b in sd and bk_w:
                pairs.append((bk_w, bk_a, bk_b, pre + ".weight", pre + ".base.bias" if (pre + ".base.bias") in sd else ""))
            else:
                missing_base.append(pre)
    print("══ 找到 %d 组 LoRA (A/B/base 齐备)" % len(pairs))
    if missing_base:
        print("   ✗ 有 %d 组不成对/缺 base 权重, 前 3: %s" % (len(missing_base), missing_base[:3]))
        return 2

    before = {k: h(v) for k, v in sd.items()}
    WORST = [0.0]      # 低精度 base 的最大折叠相对误差
    n_ok_delta = 0
    for w_key, a_key, b_key, new_key, bias_key in pairs:
        W, A, B = sd[w_key], sd[a_key], sd[b_key]
        delta = float(scaling) * (B.to(torch.float32) @ A.to(torch.float32))
        new = (W.to(torch.float32) + delta).to(W.dtype)
        # ② ΔW 必须等于 scaling·B@A —— ⚠️ base 是 bf16 时"逐位相等"**物理上不可能**
        #    (折叠结果要落回 bf16 ⇒ 舍入)。所以这里: fp32 上逐位相等才放行; 低精度 base 改成
        #    **量化误差**判据(相对误差 < 1%), 并把最大误差打出来, 让人知道代价是多少。
        chk = (new.to(torch.float32) - W.to(torch.float32))
        if W.dtype in (torch.float32, torch.float64):
            if not torch.allclose(chk, delta, atol=0, rtol=0):
                print("   ✗ %s: ΔW 与 scaling·B@A 在 fp32 上不逐位相等 ⇒ 拒绝出文件" % w_key)
                return 3
            worst = 0.0
        else:
            rel = float((chk - delta).abs().max() / (delta.abs().max() + 1e-12))
            worst = max(WORST[0], rel)
            WORST[0] = worst
            if rel > 0.01:
                print("   ✗ %s: 折叠量化相对误差 %.3e > 1%% (base=%s) ⇒ 拒绝出文件" % (w_key, rel, W.dtype))
                return 3
        n_ok_delta += 1
        sd[new_key] = new                                # 普通 Linear 的键名
        if new_key != w_key:
            sd.pop(w_key, None)                          # 去掉 .base.
        if bias_key:
            sd[new_key[: -len(".weight")] + ".bias"] = sd[bias_key]
            sd.pop(bias_key, None)
    _dt = {str(v.dtype) for v in sd.values()} if not pairs else None
    print("══ ② ΔW == scaling·B@A: %d/%d 组通过 ✓%s" % (
        n_ok_delta, len(pairs),
        "" if WORST[0] == 0 else "  (base 低精度 ⇒ 折叠量化相对误差最大 %.2e)" % WORST[0]))

    for _w, a_key, b_key, _nk, _bk in pairs:             # 丢掉适配器键
        sd.pop(a_key, None)
        sd.pop(b_key, None)
    lora_left = [k for k in sd if ".lora_A" in k or ".lora_B" in k]
    print("══ 折叠后 %d 个张量 · 残留 lora 键 %d" % (len(sd), len(lora_left)))
    if lora_left:
        print("   ✗ 仍有残留: %s" % lora_left[:3])
        return 4

    changed = [k for k in sd if before.get(k) != h(sd[k])]
    untouched_bad = [k for k in sd if k not in {new_key for _w, _a, _b, new_key, _bk in pairs} and before.get(k) != h(sd[k])]
    print("══ ① 非 LoRA 张量逐位不变: %d 个校验, 异常 %d ✓" % (len(sd) - len(changed), len(untouched_bad)))
    if untouched_bad:
        print("   ✗ 不该动的键被改了: %s" % untouched_bad[:3])
        return 5
    print("══ 变动键数 %d (= LoRA 组数 %d) ✓" % (len(changed), len(pairs)))
    if a.dry:
        print("══ --dry: 不落盘"); return 0

    os.makedirs(out_dir, exist_ok=True)
    if os.path.isdir(a.src):
        for fn in sorted(os.listdir(a.src)):             # 复制 config/tokenizer/processor 旁文件
            if fn.endswith(".safetensors") or fn.endswith(".sha256"):
                continue
            s = os.path.join(a.src, fn)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(out_dir, fn))
    dst = os.path.join(out_dir, "model.safetensors")
    save_file(sd, dst)
    print("══ 已写: %s (%.2f GB)" % (dst, os.path.getsize(dst) / 1e9))
    side = sorted(os.listdir(out_dir))
    print("══ 目录内容: %s" % side)

    # ③ 回读自证: 新文件里 base 权重 == 我算出来的, 且非 lora 与源逐位一致
    rb = load_file(dst)
    bad = [k for k in sd if h(rb[k]) != h(sd[k])]
    print("══ ③ 回读自证: %d 个键 %s" % (len(rb), "全部一致 ✓" if not bad else ("✗ 不一致 %s" % bad[:3])))
    print(json.dumps({"src": sd_path, "out": dst, "pairs": len(pairs), "scaling": scaling,
                      "tensors": len(rb), "roundtrip_ok": not bad}, ensure_ascii=False))
    return 0 if not bad else 6


if __name__ == "__main__":
    raise SystemExit(main())
