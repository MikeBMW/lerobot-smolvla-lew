#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 LoRA 适配器 (Z-MAX 全系统微调用, 自实现免依赖)

老倪 (09-22): 「适配或增加 LoRA, 你来进行架构优化」

为什么自实现而不用 peft:
  · L4 INTACT 是自研 JEPA (jepa.py/module.py), 不是 HF transformers 模型 — peft 的
    target_modules 约定与它的命名 (model.net.*, intent_actor.net.*, predictor.*) 不适配;
  · 本机 INTACT-JEPA venv **没有 peft** (实测), 而 gui-venv311 有 — 自实现可让两套环境
    用同一份代码, 避免"训练环境装不上依赖"卡住。
  · 只有 ~120 行, 行为可审计 (老倪要"实际怎么执行的"证据)。

设计 (零回退默认):
  · LoRA 包装 nn.Linear: y = base(x) + (alpha/r)·B(A(dropout(x)))
  · **B 零初始化** ⇒ 注入瞬间输出与原始模型**逐位相同** (可断言); 训练只更新 A/B, 基座冻结。
  · merge_lora() 把 B@A 折回 base.weight → 导出与原始推理路径**完全一致** (可直接部署)。
  · targets 支持名字片段过滤 (默认只包 2D Linear, 跳过 1D/输出层可用 exclude 排除)。

用法:
  gui-venv311/bin/python tools/lora_inject.py --selftest          # 四条物理断言
  gui-venv311/bin/python tools/lora_inject.py --stats <adapter.pt>  # 看适配器规模
作为库:
  import lora_inject as li
  li.inject_lora(model, targets=["to_qkv","net."], r=8, alpha=16)   # 返回注入层数
  li.save_adapter(model, "lora.pt", meta={...});  li.merge_lora(model)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """把 nn.Linear 包装成 base + 低秩增量 (B 零初始化 ⇒ 注入瞬间逐位等价)。"""

    def __init__(self, base: nn.Linear, r: int = 8, alpha: int = 16, dropout: float = 0.0):
        super().__init__()
        if not isinstance(base, nn.Linear):
            raise TypeError(f"LoRALinear 只接受 nn.Linear, 收到 {type(base)}")
        self.base = base
        self.r = int(r)
        self.alpha = int(alpha)
        self.scaling = self.alpha / self.r
        self.lora_A = nn.Parameter(torch.zeros(self.r, base.in_features))
        self.lora_B = nn.Parameter(torch.zeros(base.out_features, self.r))
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))     # A 随机, B 恒零 ⇒ 增量为 0
        for p in self.base.parameters():
            p.requires_grad_(False)                              # 基座冻结

    @property
    def merged(self) -> bool:
        return isinstance(self.base, nn.Linear) and self.base.weight.requires_grad

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.base(x)
        if self.r > 0:
            d = self.lora_B @ self.lora_A                              # [out, in]
            out = out + self.scaling * torch.nn.functional.linear(self.dropout(x), d)
        return out

    def merged_weight(self) -> torch.Tensor:
        """合并后的等效权重 (base + scaling·B@A) — 用于导出部署路径。"""
        with torch.no_grad():
            return self.base.weight + self.scaling * (self.lora_B @ self.lora_A)

    @torch.no_grad()
    def merge(self) -> nn.Linear:
        """把增量折进 base.weight, 还原成普通 nn.Linear (部署用, 推理与适配器路径逐位一致)。"""
        w = self.merged_weight().to(dtype=self.base.weight.dtype, device=self.base.weight.device)
        new = nn.Linear(self.base.in_features, self.base.out_features,
                        bias=self.base.bias is not None,
                        device=self.base.weight.device, dtype=self.base.weight.dtype)
        new.weight.copy_(w)
        if self.base.bias is not None:
            new.bias.copy_(self.base.bias.detach())
        return new


# ───────────────────────── 注入 / 冻结 ─────────────────────────
def _named_linears(model: nn.Module):
    for name, mod in model.named_modules():
        if isinstance(mod, nn.Linear) and mod.in_features and mod.out_features:
            yield name, mod


def inject_lora(model: nn.Module, targets=None, exclude=None, r: int = 8, alpha: int = 16,
                dropout: float = 0.0, verbose: bool = True) -> dict:
    """把 model 里匹配 targets 的 nn.Linear 换成 LoRALinear; 其它参数一律冻结。

    返回 {"injected": n, "layers": [...], "trainable_params": int, "total_params": int,
          "params_pct": float}
    """
    targets = list(targets or [])
    exclude = list(exclude or [])

    def hit(name: str) -> bool:
        if exclude and any(x in name for x in exclude):
            return False
        return (not targets) or any(t in name for t in targets)

    # 先冻结全部参数, 再把 LoRA 参数解冻 (注入后新参数默认 requires_grad=True)
    for p in model.parameters():
        p.requires_grad_(False)

    layered = []
    for name, mod in list(_named_linears(model)):
        if not hit(name):
            continue
        # 🐛 顶层子模块名不含 "." (如 nn.Sequential 的 "0"/"2") → 早先用 rsplit 取 attr 会得到 None
        #    而被 continue 跳过 ⇒ 注入 0 层 (2026-09-22 自检抓出)。分两种情形正确取 parent/attr。
        if "." in name:
            parent = model.get_submodule(name.rsplit(".", 1)[0])
            attr = name.rsplit(".", 1)[1]
        else:
            parent, attr = model, name
        if attr is None:
            continue
        setattr(parent, attr, LoRALinear(mod, r=r, alpha=alpha, dropout=dropout))
        layered.append(name)

    n_tr = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_all = sum(p.numel() for p in model.parameters())
    out = {"injected": len(layered), "layers": layered, "trainable_params": n_tr,
           "total_params": n_all,
           "params_pct": round(100.0 * n_tr / max(1, n_all), 4), "r": r, "alpha": alpha}
    if verbose:
        print(f"🧩 LoRA 注入 {len(layered)} 层 (r={r}, alpha={alpha}, targets={targets or '全部 Linear'}"
              f"{', exclude=' + str(exclude) if exclude else ''})")
        print(f"   可训参数 {n_tr:,} / 总参数 {n_all:,} = {out['params_pct']}%")
    return out


def lora_parameters(model: nn.Module) -> list:
    return [p for n, p in model.named_parameters() if p.requires_grad and (".lora_A" in n or ".lora_B" in n)]


def lora_state_dict(model: nn.Module) -> dict:
    return {k: v.detach().cpu() for k, v in model.state_dict().items()
            if ".lora_A" in k or ".lora_B" in k}


def load_lora_state_dict(model: nn.Module, sd: dict, strict: bool = True) -> int:
    cur = dict(model.state_dict())
    n = 0
    missing = []
    for k, v in sd.items():
        if k in cur and cur[k].shape == v.shape:
            cur[k] = v
            n += 1
        else:
            missing.append(k)
    if missing and strict:
        raise ValueError(f"适配器与模型不匹配, 缺失/形状不符: {missing[:5]} (共 {len(missing)})")
    model.load_state_dict(cur, strict=False)
    return n


@torch.no_grad()
def merge_lora(model: nn.Module) -> int:
    """把所有 LoRALinear 合并回普通 Linear (部署路径); 返回合并层数。"""
    n = 0
    for name, mod in list(model.named_modules()):
        if isinstance(mod, LoRALinear):
            if "." in name:
                parent = model.get_submodule(name.rsplit(".", 1)[0])
                attr = name.rsplit(".", 1)[1]
            else:
                parent, attr = model, name
            setattr(parent, attr, mod.merge())
            n += 1
    return n


def save_adapter(model: nn.Module, path: str, meta: dict | None = None) -> dict:
    sd = lora_state_dict(model)
    blob = {"lora": sd, "meta": {**(meta or {}), "saved_at": time.strftime("%F %T"),
                                 "n_layers": len(sd) // 2,
                                 "params": int(sum(v.numel() for v in sd.values()))}}
    torch.save(blob, path)
    return {"path": path, "n_layers": blob["meta"]["n_layers"], "params": blob["meta"]["params"],
            "size_mb": round(os.path.getsize(path) / 1e6, 3)}


# ───────────────────────── 自检 (四条物理断言) ─────────────────────────
def _selftest() -> int:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, 4))
    x = torch.randn(8, 16)
    base_out = model(x).detach().clone()

    info = inject_lora(model, targets=["0", "2"], r=4, alpha=8)
    y0 = model(x)
    d0 = float((y0 - base_out).abs().max())
    # ⚠️ 只断言"逐位等价"会漏掉"其实一层都没注入"(注入 0 层当然等价) —— 2026-09-22 实测踩到,
    #   故把"确实注入了预期层数"并入断言 ①。
    ok1 = (d0 == 0.0) and info["injected"] == 2
    print(f"① 注入 {info['injected']} 层且注入瞬间逐位等价 (B 零初始化): max|Δ| = {d0:.3e}  → {'✅' if ok1 else '❌'}")

    tr = [n for n, p in model.named_parameters() if p.requires_grad]
    only = all((".lora_A" in n or ".lora_B" in n) for n in tr)
    ok2 = bool(tr) and only and info["trainable_params"] > 0
    print(f"② 只有 LoRA 参数可训 ({len(tr)} 项, 全部 lora_*) → {'✅' if ok2 else '❌ ' + str(tr[:4])}")

    # 训练几步: 拟合一个固定目标, loss 必须下降
    torch.manual_seed(1)
    tgt = torch.randn(8, 4)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=5e-2)
    losses = []
    for _ in range(120):
        opt.zero_grad()
        loss = nn.functional.mse_loss(model(x), tgt)
        loss.backward()
        opt.step()
        losses.append(float(loss))
    ok3 = losses[-1] < 0.25 * losses[0]
    print(f"③ LoRA 真在学 (loss {losses[0]:.4f} → {losses[-1]:.4f}, 降幅 "
          f"{100 * (1 - losses[-1] / max(losses[0], 1e-9)):.1f}%) → {'✅' if ok3 else '❌'}")

    # 保存/加载往返 (走真实落盘路径; ⚠️ 必须在 merge **之前**存 —— merge 后模型里已无 LoRA 层,
    #  先 merge 再存会得到空适配器, 2026-09-22 自检踩到)
    p = "/tmp/zmax_lora_selftest.pt"
    meta = save_adapter(model, p, meta={"selftest": True})
    y_adapter = model(x).detach().clone()
    n = merge_lora(model)
    y_merged = model(x).detach().clone()
    d1 = float((y_adapter - y_merged).abs().max())
    tol = 1e-6 * max(1.0, float(y_adapter.abs().max()))
    ok4 = d1 <= tol and n == 2
    print(f"④ merge 后与适配器路径一致 (折 {n} 层): max|Δ| = {d1:.3e} (容差 {tol:.1e}) → {'✅' if ok4 else '❌'}")
    blob = torch.load(p, map_location="cpu", weights_only=False)
    m2 = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, 4))
    inject_lora(m2, targets=["0", "2"], r=4, alpha=8, verbose=False)
    nload = load_lora_state_dict(m2, blob["lora"])
    ok5 = (nload == 4) and meta["n_layers"] == 2 and len(blob["lora"]) == 4
    print(f"⑤ 适配器落盘/回读 {nload}/4 张量, {meta['size_mb']} MB → {'✅' if ok5 else '❌'}  {p}")

    allok = ok1 and ok2 and ok3 and ok4 and ok5
    print("\n" + ("✅ LoRA 适配器自检全绿" if allok else "❌ 自检失败"))
    return 0 if allok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Z-MAX LoRA 适配器")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stats", metavar="ADAPTER_PT")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.stats:
        blob = torch.load(a.stats, map_location="cpu", weights_only=False)
        print(json.dumps(blob.get("meta", {}), ensure_ascii=False, indent=1))
        print(f"张量数: {len(blob.get('lora', {}))}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
