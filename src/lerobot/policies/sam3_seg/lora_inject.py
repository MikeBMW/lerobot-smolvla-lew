# -*- coding: utf-8 -*-
"""LoRA 注入 (SAM3 微调通道) —— L2 感知模型的**可训练适配器**层

纪律 (见技能 lora-train-merge-discipline, 违反等于没做):
  1. **B 零初始化** ⇒ 注入后前向与基座**逐位一致** (W' = W + s·B@A, B≡0) ⇒ 不需要 init 基准文件;
     副作用: 第 1 步 dL/dA ≡ 0 (A 无梯度是**正常**的), 第 2 步才有 A 的梯度 ⇒
     梯度闸必须分两步看: **第1步判 B, 第2步判 A**; 判早了会把正常误判成坏。
  2. 键名约定: 原 Linear 存 `<prefix>.base.weight` / `.base.bias`, 适配器 `<prefix>.lora_A` / `.lora_B`
     (A=[r,in], B=[out,r])。**部署合并**时还原成普通 Linear ⇒ 输出键去掉 `.base.`
     (标准加载器不认 `.base.weight`, 会把权重当未知键丢掉 ⇒ 零输出)。
  3. 折叠精度: bf16 基座上 ‖ΔW‖/‖W‖ 可能 < bf16 eps(3.9e-3) ⇒ 折进 bf16 等于**抹掉**。
     本模块提供 `delta_norm_ratio()` 供折叠前算精度账。

显存定位 (4060 8GB, 实测): 视觉塔 32 层全量可训 = fwd+bwd 峰值 >7.6GB ⇒ OOM;
  ViT **冻结** + 只训 4 个头 = 31.4M 可训 / 峰值 2.94GB ⇒ 可行。
  LoRA 只注**最后 N 个 ViT block** (+ 文本塔, CLIP 序列极短): 反向只保留 LoRA block **之后**的激活
  ⇒ 显存增量 ≈ N/32 的视觉塔激活。
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """W' x = W x + s·B(A x);  A=[r,in] kaiming, B=[out,r] **零初始化**; 适配器用 fp32。"""

    def __init__(self, base: nn.Linear, r: int = 8, alpha: int | None = None, dropout: float = 0.0):
        super().__init__()
        assert isinstance(base, nn.Linear), type(base)
        self.base = base                      # 保留原参数名 ⇒ 键 `<prefix>.base.weight`
        self.in_features = base.in_features
        self.out_features = base.out_features
        self.r = int(r)
        self.alpha = int(alpha if alpha is not None else r)
        self.scaling = self.alpha / self.r
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

        for p in self.base.parameters():
            p.requires_grad_(False)           # 基座冻结 —— 只训适配器

        _dev = base.weight.device                    # ⚠️ 注入在 `.to(cuda)` **之后**做 ⇒ 新参数必须显式跟基座同设备(否则 cuda/cpu 混算报错)
        a = torch.empty(self.r, self.in_features, dtype=torch.float32, device=_dev)
        nn.init.kaiming_uniform_(a, a=math.sqrt(5))
        self.lora_A = nn.Parameter(a)
        self.lora_B = nn.Parameter(torch.zeros(self.out_features, self.r, dtype=torch.float32, device=_dev))  # ★ 零初始化

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.base(x)
        xf = self.dropout(x).float() if self.training else x.float()
        d = (xf @ self.lora_A.t()) @ self.lora_B.t()          # [.., out], fp32
        return out + (self.scaling * d).to(out.dtype)

    def delta_weight(self) -> torch.Tensor:
        """ΔW = s·B@A (fp32, [out,in]) —— 折叠精度账/合并用"""
        return self.scaling * (self.lora_B.float() @ self.lora_A.float())


def inject_lora(model: nn.Module, targets: dict[str, list[str]], r: int = 8, alpha: int | None = None,
                prefix_filter: dict[str, object] | None = None) -> tuple[int, int]:
    """按 targets={前缀: [子模块名...]} 注入。prefix_filter={前缀: 谓词(块索引)} 限定注入范围。

    返回 (注入的 Linear 个数, 其中被 prefix_filter 过滤掉的 Linear 个数)。
    用法: 只注**最后 N 个** ViT block ⇒ prefix_filter={".vision_encoder.backbone.layers.": lambda i: i>=32-N}
    """
    pf = prefix_filter or {}
    n_inj = n_skip = 0
    for prefix, subs in targets.items():
        for name, mod in list(model.named_modules()):
            if prefix not in name or not isinstance(mod, nn.Linear):
                continue
            if not name.endswith(tuple(subs)):
                continue
            pred = pf.get(prefix)
            if pred is not None:
                tail = name.split(prefix)[-1]                 # 如 "12.attention.q_proj.weight" 前的索引
                try:
                    idx = int(tail.split(".")[0])
                except (ValueError, IndexError):
                    idx = -1
                if not pred(idx):
                    n_skip += 1
                    continue
            parts = name.split(".")
            parent = model.get_submodule(".".join(parts[:-1]))
            setattr(parent, parts[-1], LoRALinear(mod, r=r, alpha=alpha))
            n_inj += 1
    return n_inj, n_skip


def lora_named(model: nn.Module):
    return [(n, p) for n, p in model.named_parameters()
            if (n.endswith(".lora_A") or n.endswith(".lora_B")) and p.requires_grad]


def lora_state_dict(model: nn.Module) -> dict:
    """只取适配器权重 (A/B) —— 产物是**适配器文件**, 不落 3.4GB 基座 (大文件不进 git)。"""
    return {n: p.detach().cpu() for n, p in lora_named(model)}


def grad_stats(model: nn.Module) -> dict:
    """逐适配器梯度统计: {name: (kind, status, max|grad|)}; status = OK / ZERO / NONE。"""
    out = {}
    for n, p in lora_named(model):
        kind = "B" if n.endswith(".lora_B") else "A"
        g = p.grad
        status = "NONE" if g is None else ("ZERO" if float(g.abs().max()) == 0.0 else "OK")
        out[n] = (kind, status, None if g is None else float(g.abs().max()))
    return out


def nonzero_lora_b(model: nn.Module) -> tuple[int, int, float]:
    """免基准判据: 训练前所有 lora_B ≡ 0 ⇒ 非零即**确实被更新过**。返回(总条数, 非零条数, 最大|B|)。"""
    tot = nz = 0
    mx = 0.0
    for n, p in model.named_parameters():
        if not n.endswith(".lora_B"):
            continue
        m = float(p.detach().abs().max())
        tot += 1
        nz += int(m > 0)
        mx = max(mx, m)
    return tot, nz, mx


def delta_norm_ratio(model: nn.Module) -> list[tuple[str, float, float]]:
    """每个退化点算 ‖ΔW‖/‖W‖ (中位/最大是折叠精度账的输入)。"""
    rows = []
    for mname, mod in model.named_modules():
        if isinstance(mod, LoRALinear):
            w = mod.base.weight.detach().float()
            d = mod.delta_weight()
            wn = float(w.norm())
            rows.append((mname, float(d.norm()) / max(wn, 1e-12), wn))
    return rows
