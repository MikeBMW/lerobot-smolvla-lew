# -*- coding: utf-8 -*-
"""SAM3 框提示式微调内核 (L2 感知模型的**可训练通道**)

定位: 与 `segmenter.py` 同一层 (policies/sam3_seg/) —— `segmenter.py` 管**推理**, 本文件管**训练**。
调用方 (CLI) 在 tools/sam3_finetune.py。

## 训练任务 (为什么这样设计)
数据只有 **检测框** (data/yolo_annot/dataset: 52 帧 / 58 框 / 2 类 peg·OPT_Gold), **没有掩膜**。
所以监督分两路, 各自说清来源 (不许把伪标签说成真标注):

  A. **文本提示 → 框** (真标注监督, 非退化): 提示词 = 类名, 用 Hungarian 匹配把 200 个 query
     配到 GT 框, 监督 pred_boxes (L1+GIoU) + pred_logits + presence_logits。字面是真标注。
  B. **框提示 → 掩膜** (教师蒸馏, 必须显式声明): 提示 = GT 框, 监督 pred_masks 对 **冻结基座
     在本帧同一框提示下**产出的掩膜 (tools/sam3_finetune.py `masks` 子命令预生成, 落 PNG)。
     ⚠️ 这不是人工掩膜标注, 是"教师伪标签"; 报告里一律写作 教师伪标签。
     非退化的来源: 训练时对**图像做光度扰动 + 对提示框做抖动**, 目标仍是**干净帧+原始框**的教师掩膜
     ⇒ 学生必须学会"鲁棒地把框内的东西分出来", 而不是把提示框原样输出。

## 显存口径 (4060 8GB 实测, 见 lora_inject.py 抬头)
冻结视觉塔+文本塔 ⇒ 峰值 2.98GB; LoRA 只注**最后 N 个 ViT block**+文本塔;
N=8 ⇒ 33.53M 可训 / 4.91GB; N=16 ⇒ 6.51GB; N=32 ⇒ OOM。默认 N=8。

## 双闸 (技能 lora-train-merge-discipline)
闸一 **梯度到齐**: 第 1 次 backward 后所有 lora_B 必须非零梯度 (B 零初始化 ⇒ 非零即"进过损失图");
  第 2 次 backward 后所有 lora_A 必须非零 (第 1 步 dL/dA ≡ 0 是**正常**的, 判早了会误判)。
  同时对**4 个可训头**逐模块查梯度, 显式登记"不在损失图里"的死区 (如 mask_decoder.semantic_projection)。
闸二 **折叠精度**: 训练后算 ‖ΔW‖/‖W‖ 中位 vs bf16 eps(3.9e-3); 小于 eps ⇒ 禁止折进 bf16。
"""
from __future__ import annotations

import glob
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .lora_inject import LoRALinear, grad_stats, inject_lora, lora_named, nonzero_lora_b

# ── 默认口径 ────────────────────────────────────────────────────────────────
SAM3_DIR = os.environ.get("ZMAX_SAM3_DIR", "/home/ubuntu/zmax_data/models/sam3_hf")
DATASET_DIR = os.environ.get("ZMAX_SAM3_DATASET", "/home/ubuntu/zmax_rel/data/yolo_annot/dataset")
SIZE = 1008
VIT_LORA_BLOCKS = 8
R, ALPHA = 8, 16

LORA_TARGETS = {
    # 前缀**不带**前导点 (named_modules() 名字无前导点) —— 带点会匹配 0 个 (踩过)
    "vision_encoder.backbone.layers.": ["attention.q_proj", "attention.k_proj", "attention.v_proj", "attention.o_proj"],
    "text_encoder.text_model.encoder.layers.": ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.out_proj"],
}
HEAD_MODULES = ("geometry_encoder", "detr_encoder", "detr_decoder", "mask_decoder")


# ── 数据集 ─────────────────────────────────────────────────────────────────
@dataclass
class Sample:
    stem: str
    split: str
    img_path: str
    W: int
    H: int
    boxes_xyxy: list[list[float]] = field(default_factory=list)     # 像素 xyxy
    cls_ids: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "?"


def read_class_names(root: str | os.PathLike) -> list[str]:
    """从 data.yaml 读类名 (names: 0: peg ...)"""
    names: dict[int, str] = {}
    p = Path(root) / "data.yaml"
    if not p.exists():
        return []
    inside = False
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("names:"):
            inside = True
            continue
        if inside:
            if not s or ":" not in s:
                inside = False
                continue
            k, v = s.split(":", 1)
            try:
                names[int(k.strip())] = v.strip()
            except ValueError:
                inside = False
    return [names[i] for i in sorted(names)]


def scan_split(root: str | os.PathLike, split: str) -> list[Sample]:
    """扫 images/<split> + labels/<split> (YOLO 检测格式: cls cx cy w h, 归一化)"""
    import cv2
    root = Path(root)
    out: list[Sample] = []
    for img in sorted(glob.glob(str(root / "images" / split / "*.jpg"))):
        stem = Path(img).stem
        lab = root / "labels" / split / f"{stem}.txt"
        im = cv2.imread(img)
        if im is None:
            continue
        H, W = im.shape[:2]
        s = Sample(stem=stem, split=split, img_path=img, W=W, H=H)
        if lab.exists():
            for line in lab.read_text().splitlines():
                f = line.split()
                if len(f) < 5:
                    continue
                c, cx, cy, w, h = int(float(f[0])), *[float(x) for x in f[1:5]]
                s.cls_ids.append(c)
                s.boxes_xyxy.append([(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H])
        if s.boxes_xyxy:
            out.append(s)
    return out


def pick_text(s: Sample, names: list[str]) -> str:
    """一帧一个文本提示 = 该帧 GT 框的**多数类** (需英文 —— SAM3 文本塔是 CLIP, 中文=0 实例)。"""
    if not s.cls_ids:
        return "visual"
    maj = max(set(s.cls_ids), key=s.cls_ids.count)
    return names[maj] if 0 <= maj < len(names) else "visual"


# ── 教师伪标签 (框提示 → 掩膜) ──────────────────────────────────────────────
MASK_SUBDIR = "sam3_teacher_masks"


def teacher_mask_path(cache_dir: str | os.PathLike, s: Sample, i: int) -> Path:
    return Path(cache_dir) / MASK_SUBDIR / s.split / f"{s.stem}__b{i}.png"


def save_teacher_mask(path: Path, mask: np.ndarray, src: str, iou_box: float) -> None:
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), (mask.astype(np.uint8) * 255))
    path.with_suffix(".json").write_text(json.dumps({"src": src, "iou_box": round(float(iou_box), 4)}))


def load_teacher_mask(path: Path, size: int) -> tuple[np.ndarray, dict]:
    import cv2
    m = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise FileNotFoundError(path)
    if m.shape[0] != size or m.shape[1] != size:
        m = cv2.resize(m, (size, size), interpolation=cv2.INTER_NEAREST)
    meta = {}
    j = path.with_suffix(".json")
    if j.exists():
        meta = json.loads(j.read_text())
    return (m > 127), meta


@torch.no_grad()
def gen_teacher_masks(model, proc, samples: list[Sample], cache_dir: str | os.PathLike, names: list[str],
                      size: int = SIZE, mask_threshold: float = 0.5, log=print) -> dict:
    """用**冻结基座** + 框提示生成掩膜伪标签 (落 PNG, 288x288 = pred_masks 原生分辨率)。

    选 query 口径: 与 GT 框 IoU 最高的那个 query 的掩膜 (而不是"分数最高的") ——
    因为学生正是要学"框提示→该框内物体的掩膜", 口径必须一致。
    基座在真机帧上可能整帧零检出 (技能记载: 概念常 0 实例) ⇒ 此时回退成**框矩形**, 并登记 src=box_fallback。
    """
    model.eval()
    n_ok = n_fb = 0
    rows = []
    for s in samples:
        inputs = build_inputs(proc, s, size=size, text=pick_text(s, names), device="cuda")
        out = model(pixel_values=inputs["pixel_values"], input_ids=inputs["input_ids"],
                    attention_mask=inputs["attention_mask"], input_boxes=inputs["input_boxes"],
                    input_boxes_labels=inputs["input_boxes_labels"])
        pm = out.pred_masks[0].float().sigmoid()                     # [200, h, w]
        h, w = pm.shape[-2:]
        bins = pm > mask_threshold
        sx, sy = w / s.W, h / s.H
        for i, b in enumerate(s.boxes_xyxy):
            bx = np.array([b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy])
            rect = np.zeros((h, w), bool)
            x1, y1, x2, y2 = [int(round(v)) for v in bx]
            x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
            x2, y2 = max(0, min(x2, w)), max(0, min(y2, h))
            rect[y1:y2, x1:x2] = True
            # ⚠️ 混算坑: bins 在 cuda, rect 是 numpy ⇒ 必须先转成同设备的张量再比 (否则 __array__ 报错)
            rect_t = torch.as_tensor(rect, device=bins.device, dtype=torch.bool)[None]
            inter = (bins & rect_t).sum(dim=(1, 2)).float()
            union = (bins | rect_t).sum(dim=(1, 2)).float().clamp(min=1)
            iou = inter / union
            j = int(iou.argmax())
            best = float(iou[j])
            m = bins[j].cpu().numpy()
            if best < 0.05 or m.sum() < 50:                          # 基座没分出来 ⇒ 回退(并登记)
                save_teacher_mask(teacher_mask_path(cache_dir, s, i), rect, "box_fallback", best)
                n_fb += 1
            else:
                save_teacher_mask(teacher_mask_path(cache_dir, s, i), m, "sam3_teacher", best)
                n_ok += 1
            rows.append({"stem": s.stem, "box": i, "iou_box": round(best, 4),
                         "src": "box_fallback" if best < 0.05 or m.sum() < 50 else "sam3_teacher",
                         "area_px": int(m.sum())})
    log(f"[teacher] 生成伪标签 {n_ok + n_fb} 条: sam3_teacher {n_ok} · box_fallback {n_fb} ⇒ {cache_dir}/{MASK_SUBDIR}")
    return {"n_total": n_ok + n_fb, "n_teacher": n_ok, "n_fallback": n_fb, "rows": rows}


def build_inputs(proc, s: Sample, size: int = SIZE, text: str = "visual", device: str = "cuda",
                 box_override: list[list[float]] | None = None) -> dict:
    """一帧 → 模型入参 (processor 口径: input_boxes 归一化 cxcywh)。box_override 用于提示框抖动。"""
    import cv2
    from PIL import Image
    im = cv2.imread(s.img_path)
    pil = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
    boxes = box_override if box_override is not None else s.boxes_xyxy
    enc = proc(images=pil, text=text, input_boxes=[boxes], return_tensors="pt")
    out = {}
    for k, v in enc.items():
        if not hasattr(v, "to"):
            out[k] = v
            continue
        if k == "original_sizes":
            out[k] = v
            continue
        if v.dtype in (torch.float32, torch.float64):
            out[k] = v.to(device, torch.bfloat16)
        else:
            out[k] = v.to(device)
    return out


# ── 损失 ───────────────────────────────────────────────────────────────────
def _giou(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """a,b: [n,4] 归一化 xyxy"""
    x1 = torch.max(a[:, 0], b[:, 0]); y1 = torch.max(a[:, 1], b[:, 1])
    x2 = torch.min(a[:, 2], b[:, 2]); y2 = torch.min(a[:, 3], b[:, 3])
    inter = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    aa = (a[:, 2] - a[:, 0]).clamp(min=0) * (a[:, 3] - a[:, 1]).clamp(min=0)
    ab = (b[:, 2] - b[:, 0]).clamp(min=0) * (b[:, 3] - b[:, 1]).clamp(min=0)
    union = aa + ab - inter
    iou = inter / union.clamp(min=1e-6)
    cx1 = torch.min(a[:, 0], b[:, 0]); cy1 = torch.min(a[:, 1], b[:, 1])
    cx2 = torch.max(a[:, 2], b[:, 2]); cy2 = torch.max(a[:, 3], b[:, 3])
    carea = (cx2 - cx1).clamp(min=0) * (cy2 - cy1).clamp(min=0)
    return iou - (carea - union) / carea.clamp(min=1e-6)


def jitter_boxes(boxes: list[list[float]], frac: float, rng) -> list[list[float]]:
    """提示框抖动 —— 训练信号"非退化"的来源: 目标始终是**精确框**下的教师掩膜,
    而学生拿到的是**抖动过的框** ⇒ 必须学会"框不准也把物体分出来"(提示式微调的真正价值)。"""
    if frac <= 0:
        return [list(b) for b in boxes]
    out = []
    for b in boxes:
        w, h = b[2] - b[0], b[3] - b[1]
        jx, jy = w * frac, h * frac
        out.append([b[0] + float(rng.uniform(-jx, jx)), b[1] + float(rng.uniform(-jy, jy)),
                    b[2] + float(rng.uniform(-jx, jx)), b[3] + float(rng.uniform(-jy, jy))])
    return out


def _box_iou(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    x1 = torch.max(a[0], b[0]); y1 = torch.max(a[1], b[1])
    x2 = torch.min(a[2], b[2]); y2 = torch.min(a[3], b[3])
    inter = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    aa = (a[2] - a[0]).clamp(min=0) * (a[3] - a[1]).clamp(min=0)
    ab = (b[2] - b[0]).clamp(min=0) * (b[3] - b[1]).clamp(min=0)
    return inter / (aa + ab - inter).clamp(min=1e-6)


def match_queries(pred_boxes: torch.Tensor, gt_boxes: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Hungarian 匹配 (cost = L1 + GIoU)。返回 (query_idx, gt_idx)。"""
    if gt_boxes.numel() == 0:
        return torch.zeros(0, dtype=torch.long, device=pred_boxes.device), torch.zeros(0, dtype=torch.long, device=pred_boxes.device)
    c = pred_boxes[:, None, :] - gt_boxes[None, :, :]
    cost = (c.abs().sum(-1) + (1.0 - _giou(pred_boxes.unsqueeze(1).expand(-1, gt_boxes.shape[0], -1).reshape(-1, 4),
                                           gt_boxes.unsqueeze(0).expand(pred_boxes.shape[0], -1, -1).reshape(-1, 4))
                               ).reshape(pred_boxes.shape[0], gt_boxes.shape[0]))
    cost = cost.detach().float().cpu().numpy()
    from scipy.optimize import linear_sum_assignment
    r, cc = linear_sum_assignment(cost)
    return torch.as_tensor(r, dtype=torch.long, device=pred_boxes.device), torch.as_tensor(cc, dtype=torch.long, device=pred_boxes.device)


def seg_loss(out, gt_boxes_norm: torch.Tensor, target_masks: torch.Tensor | None,
             w_mask=2.0, w_box=1.0, w_cls=0.5, w_pres=1.0) -> tuple[torch.Tensor, dict]:
    """out: Sam3ImageSegmentationOutput (batch=1)。gt_boxes_norm: [n,4] 归一化 xyxy。
    target_masks: [n, h, w] bool (教师伪标签, 与 pred_masks 同分辨率) 或 None (只训检测路)。
    """
    pred_boxes = out.pred_boxes[0].float()                      # [200,4] 归一化 xyxy
    pred_logits = out.pred_logits[0].float()                    # [200]
    n_q = pred_boxes.shape[0]
    qi, gi = match_queries(pred_boxes.detach(), gt_boxes_norm)

    parts: dict[str, float] = {}
    if len(qi):
        l1 = F.l1_loss(pred_boxes[qi], gt_boxes_norm[gi])
        lgiou = (1.0 - _giou(pred_boxes[qi], gt_boxes_norm[gi])).mean()
        parts["box_l1"] = float(l1)
        parts["box_giou"] = float(lgiou)
        lbox = l1 + lgiou
    else:
        lbox = pred_boxes.sum() * 0.0
        parts["box_l1"] = parts["box_giou"] = 0.0

    tgt = torch.zeros(n_q, device=pred_logits.device)
    if len(qi):
        tgt[qi] = 1.0
    lcls = F.binary_cross_entropy_with_logits(pred_logits, tgt)
    parts["cls"] = float(lcls)

    pres = out.presence_logits[0].float().reshape(-1)
    lpres = F.binary_cross_entropy_with_logits(pres, torch.ones_like(pres) if len(qi) else torch.zeros_like(pres))
    parts["presence"] = float(lpres)

    lmask = pred_boxes.sum() * 0.0
    if target_masks is not None and len(qi):
        pm = out.pred_masks[0].float()[qi]                       # [n,h,w] logits
        tm = target_masks.float()
        bce = F.binary_cross_entropy_with_logits(pm, tm)
        p = pm.sigmoid()
        num = 2.0 * (p * tm).sum(dim=(1, 2))
        den = p.sum(dim=(1, 2)) + tm.sum(dim=(1, 2)) + 1e-6
        dice = 1.0 - (num / den).mean()
        parts["mask_bce"] = float(bce)
        parts["mask_dice"] = float(dice)
        lmask = bce + dice

    total = w_mask * lmask + w_box * lbox + w_cls * lcls + w_pres * lpres
    parts["total"] = float(total)
    return total, parts


# ── 模型装配 ───────────────────────────────────────────────────────────────
def build_trainable_model(model_dir: str = SAM3_DIR, size: int = SIZE, vit_lora_blocks: int = VIT_LORA_BLOCKS,
                          r: int = R, alpha: int = ALPHA, log=print):
    """冻结基座 → 4 个头全量可训 + LoRA (视觉塔最后 N block / 文本塔全层)。"""
    from transformers import Sam3Model, Sam3Processor
    proc = Sam3Processor.from_pretrained(model_dir, local_files_only=True)
    try:
        proc.image_processor.size = {"height": size, "width": size}
    except Exception:                                            # noqa: BLE001
        pass
    model = Sam3Model.from_pretrained(model_dir, local_files_only=True, dtype=torch.bfloat16).to("cuda")
    for p in model.parameters():
        p.requires_grad_(False)
    pf = {"vision_encoder.backbone.layers.": (lambda i, N=vit_lora_blocks: i >= 32 - N)}
    n_inj, n_skip = inject_lora(model, LORA_TARGETS, r=r, alpha=alpha, prefix_filter=pf)
    n_head = 0
    for h in HEAD_MODULES:
        for p in model.get_submodule(h).parameters():
            p.requires_grad_(True)
            n_head += p.numel()
    n_lora = sum(p.numel() for _, p in lora_named(model))
    log(f"[model] LoRA 注入 {n_inj} 个 Linear (跳过 {n_skip}) · 头模块全量可训 {n_head/1e6:.2f}M · 适配器 {n_lora/1e6:.3f}M")
    return model, proc, {"n_lora_linear": n_inj, "n_lora_skip": n_skip,
                         "n_head_params": n_head, "n_lora_params": n_lora}


def preencode(proc, samples: list[Sample], size: int, names: list[str], device: str = "cpu", log=print) -> dict:
    """processor 只在启动时跑一次 ⇒ 训练循环里只剩 GPU 计算 (提利用率)"""
    t0 = time.time()
    cache = {}
    for s in samples:
        inp = build_inputs(proc, s, size=size, text=pick_text(s, names), device=device)
        cache[s.stem] = {k: (v.cpu() if hasattr(v, "cpu") else v) for k, v in inp.items()}
    log(f"[data] 预编码 {len(cache)} 帧 ({size}px) 用时 {time.time()-t0:.1f}s · "
        f"每帧 {next(iter(cache.values()))['pixel_values'].numel()*2/1e6:.1f}MB(bf16)")
    return cache


def apply_adapter(model, adapter_dir: str | os.PathLike, log=print) -> tuple[int, int]:
    """把适配器**加载进模型** —— 部署侧自证 (技能三问之二): 键必须完全匹配且真的改变前向。

    返回 (加载张量数, 非零 lora_B 数)。键不匹配直接报错, 不静默丢。
    """
    from safetensors.torch import load_file
    f = Path(adapter_dir) / "adapter_model.safetensors"
    sd = load_file(str(f))
    own = dict(model.named_parameters())
    miss = [k for k in sd if k not in own]
    extra = [n for n, _ in own.items() if (n.endswith(".lora_A") or n.endswith(".lora_B")) and n not in sd]
    if miss or extra:
        raise RuntimeError(f"适配器键不匹配: 模型里找不到 {miss[:5]} (共{len(miss)}) · 产物未覆盖 {extra[:5]} (共{len(extra)})")
    with torch.no_grad():
        for k, v in sd.items():
            own[k].copy_(v.to(device=own[k].device, dtype=own[k].dtype))
    nb = sum(1 for k, v in sd.items() if k.endswith(".lora_B") and float(v.abs().max()) > 0)
    log(f"[adapter] 加载 {len(sd)} 个张量 (键完全匹配: 缺 0 / 多余 0) · 非零 lora_B {nb} 条 ⇒ 部署侧**真加载**")
    return len(sd), nb


def trainable_param_groups(model, lr_lora: float, lr_head: float):
    heads = set()
    for h in HEAD_MODULES:
        heads |= {id(p) for p in model.get_submodule(h).parameters()}
    g_lora = [p for n, p in lora_named(model)]
    g_head = [p for p in model.parameters() if p.requires_grad and id(p) in heads]
    return [{"params": g_lora, "lr": lr_lora, "name": "lora"},
            {"params": g_head, "lr": lr_head, "name": "heads"}]


# ── 闸门 ───────────────────────────────────────────────────────────────────
def grad_gate_report(model, step: int) -> dict:
    """第 1 步判 B / 第 2 步判 A (B 零初始化 ⇒ 第1步 dL/dA ≡ 0 是正常的)。"""
    gs = grad_stats(model)
    fam = {"vision": [], "text": []}
    for n, (kind, status, mx) in gs.items():
        f = "vision" if "vision_encoder" in n else ("text" if "text_encoder" in n else "other")
        fam.setdefault(f, []).append((n, kind, status, mx))
    rep = {"step": step, "n_lora_params": len(gs)}
    for f, rows in fam.items():
        rep[f] = {"n": len(rows),
                  "B_none": sum(1 for _, k, s, _ in rows if k == "B" and s == "NONE"),
                  "B_zero": sum(1 for _, k, s, _ in rows if k == "B" and s == "ZERO"),
                  "B_ok": sum(1 for _, k, s, _ in rows if k == "B" and s == "OK"),
                  "A_none": sum(1 for _, k, s, _ in rows if k == "A" and s == "NONE"),
                  "A_zero": sum(1 for _, k, s, _ in rows if k == "A" and s == "ZERO"),
                  "A_ok": sum(1 for _, k, s, _ in rows if k == "A" and s == "OK")}
    # 4 个可训头逐模块: 有非零梯度 / 无梯度 (逐名登记, 不许只说个数字)
    hm = {}
    for h in HEAD_MODULES:
        mod = model.get_submodule(h)
        alive = dead = nod = 0
        zero_names, none_names = [], []
        for pname, p in mod.named_parameters():
            if not p.requires_grad:
                continue
            if p.grad is None:
                nod += 1
                none_names.append(pname)
            elif float(p.grad.abs().max()) > 0:
                alive += 1
            else:
                dead += 1
                zero_names.append(pname)
        hm[h] = {"n_trainable": alive + dead + nod, "grad_nonzero": alive, "grad_zero": dead, "grad_None": nod,
                 "zero_params": zero_names[:20], "none_params": none_names[:20]}
    rep["heads"] = hm
    rep["dead_zone"] = {n: hm[n]["none_params"] for n in hm if hm[n]["grad_None"] > 0}
    return rep


def assert_grad_gate(rep: dict, step: int) -> tuple[bool, list[str]]:
    """闸一判定: 第1步所有 B 必须 OK; 第2步所有 A 必须 OK。返回(是否通过, 失败原因)。"""
    bad = []
    for f in ("vision", "text"):
        r = rep.get(f)
        if not r or r["n"] == 0:
            continue
        if step <= 1 and r["B_ok"] != r["n"] // 2:
            bad.append(f"{f}: 第{step}步 lora_B 收到非零梯度 {r['B_ok']}/{r['n']//2}")
        if step >= 2 and r["A_ok"] != r["n"] // 2:
            bad.append(f"{f}: 第{step}步 lora_A 收到非零梯度 {r['A_ok']}/{r['n']//2} (第二步起 A 必须有梯度)")
    return (not bad), bad


# ── 训练 ───────────────────────────────────────────────────────────────────
def run_train(args, log=print) -> dict:
    import torch
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    names = read_class_names(args.dataset)
    train = scan_split(args.dataset, "train")
    val = scan_split(args.dataset, "val")
    log(f"[data] 类名 {names} · train {len(train)} 帧/{sum(len(s.boxes_xyxy) for s in train)} 框"
        f" · val {len(val)} 帧/{sum(len(s.boxes_xyxy) for s in val)} 框")

    model, proc, minfo = build_trainable_model(args.model_dir, size=args.size,
                                              vit_lora_blocks=args.lora_vit_blocks, r=args.r, alpha=args.alpha, log=log)

    # 缓存 pixel_values (processor 只在启动时跑一次 ⇒ 训练循环里只剩 GPU 计算, 提利用率)
    t0 = time.time()
    cache = {}
    for s in train + val:
        inp = build_inputs(proc, s, size=args.size, text=pick_text(s, names), device="cpu")
        cache[s.stem] = {k: (v.cpu() if hasattr(v, "cpu") else v) for k, v in inp.items()}
    log(f"[data] 预编码 {len(cache)} 帧 ({args.size}px) 用时 {time.time()-t0:.1f}s · 每帧 {next(iter(cache.values()))['pixel_values'].numel()*2/1e6:.1f}MB(bf16)")

    # 教师伪标签
    tasks = []
    for s in train + val:
        for i in range(len(s.boxes_xyxy)):
            p = teacher_mask_path(args.cache_dir, s, i)
            if not p.exists():
                raise FileNotFoundError(
                    f"教师伪标签缺失: {p} ⇒ 先跑 `tools/sam3_finetune.py masks --cache-dir {args.cache_dir}`")
            tasks.append((s, i, p))
    log(f"[data] 教师伪标签 {len(tasks)} 条就位")

    # 一次 dry forward: 拿到 pred_masks 原生分辨率 (伪标签按它加载) + 登记输出形状 (不许猜)
    with torch.no_grad():
        _s = train[0]
        _inp = {k: v.to("cuda") if k != "original_sizes" else v for k, v in cache[_s.stem].items()}
        _inp["pixel_values"] = _inp["pixel_values"].to(torch.bfloat16)
        _inp["input_boxes"] = torch.tensor([[( (b[0]+b[2])/2)/_s.W, (((b[1]+b[3])/2))/_s.H, (b[2]-b[0])/_s.W, (b[3]-b[1])/_s.H]
                                            for b in _s.boxes_xyxy], dtype=torch.bfloat16,
                                           device="cuda").unsqueeze(0)   # ⚠️ 模型要 [batch, n_box, 4], 少一维会 view 报错
        _inp["input_boxes_labels"] = torch.ones(_inp["input_boxes"].shape[:2], dtype=torch.long, device="cuda")
        _out = model(**_inp)
        hw = int(_out.pred_masks.shape[-1])
        log(f"[dry] 输出形状: pred_masks {tuple(_out.pred_masks.shape)} · pred_boxes {tuple(_out.pred_boxes.shape)} "
            f"· pred_logits {tuple(_out.pred_logits.shape)} · presence {tuple(_out.presence_logits.shape)} "
            f"⇒ 伪标签分辨率 {hw}x{hw}")
        del _out, _inp

    opt = torch.optim.AdamW(trainable_param_groups(model, args.lr_lora, args.lr_head),
                            betas=(0.9, 0.95), weight_decay=0.0, eps=1e-8)
    jrng = np.random.default_rng(args.seed + 7)

    # 训练前基线 (LoRA 的 B 零初始化 ⇒ 此刻模型 == 冻结基座, 前向逐位一致 ⇒ 这是干净的 step-0 基准)
    _banner0 = evaluate(model, val, names, cache, args, jitter=args.box_jitter, seed=1234,
                        tag="val@step0(==基座)", log=log)

    def make_batch(s: Sample, augment: bool):
        inp = {k: (v.clone() if hasattr(v, "clone") else v) for k, v in cache[s.stem].items()}
        pv = inp["pixel_values"].to("cuda", torch.bfloat16, non_blocking=True)
        boxes = [list(b) for b in s.boxes_xyxy]
        if augment:                                              # 光度扰动 + 提示框抖动 (信号"非退化"的来源)
            g = 1.0 + float(np.random.uniform(-0.12, 0.12))
            pv = (pv * g).clamp(-3.0, 3.0)
            if np.random.rand() < 0.5:
                pv = (pv + torch.randn_like(pv) * 0.02).clamp(-3.0, 3.0)
            boxes = jitter_boxes(boxes, args.box_jitter, jrng)
        # 归一化 cxcywh (processor 口径)
        bb = torch.tensor([[[( (b[0]+b[2])/2)/s.W, (((b[1]+b[3])/2))/s.H, (b[2]-b[0])/s.W, (b[3]-b[1])/s.H]
                            for b in boxes]], dtype=torch.bfloat16, device="cuda")   # [1, n_box, 4]
        lab = torch.ones(bb.shape[:2], dtype=torch.long, device="cuda")
        gt = torch.tensor([[b[0] / s.W, b[1] / s.H, b[2] / s.W, b[3] / s.H] for b in s.boxes_xyxy],
                          dtype=torch.float32, device="cuda")
        return {"pixel_values": pv, "input_ids": inp["input_ids"].to("cuda"),
                "attention_mask": inp["attention_mask"].to("cuda"),
                "input_boxes": bb, "input_boxes_labels": lab}, gt

    # 教师目标张量 (与 pred_masks 同分辨率)
    def target_masks_for(s: Sample, mhw: int):
        ms = []
        for i in range(len(s.boxes_xyxy)):
            m, _meta = load_teacher_mask(teacher_mask_path(args.cache_dir, s, i), mhw)
            ms.append(torch.as_tensor(m, device="cuda"))
        return torch.stack(ms)

    logf = open(Path(args.out) / "train_log.jsonl", "w", encoding="utf-8")
    gates = {}
    step = 0
    t_start = time.time()
    seen = 0
    hist = []
    for ep in range(args.epochs):
        order = np.random.permutation(len(train))
        model.train()
        for oi in order:
            s = train[oi]
            b, gt = make_batch(s, augment=(args.aug != "none"))
            out = model(**b)
            tms = target_masks_for(s, hw)
            loss, parts = seg_loss(out, gt, tms, args.w_mask, args.w_box, args.w_cls, args.w_pres)
            loss.backward()
            step += 1
            if step <= args.gate_steps:                           # 闸一: 逐步取证 (第1步判B, 第2步判A)
                rep = grad_gate_report(model, step)
                ok, bad = assert_grad_gate(rep, step)
                gates[f"step{step}"] = rep
                log(f"[gate/s{step}] vision B_ok={rep['vision']['B_ok']} A_ok={rep['vision']['A_ok']} "
                    f"| text B_ok={rep['text']['B_ok']} A_ok={rep['text']['A_ok']} | 通过={ok}"
                    + ("" if ok else f" ❌ {bad}"))
                if not ok:
                    raise RuntimeError(f"梯度到齐闸未通过 (step {step}): {bad}")
                if step == args.gate_steps:
                    gn = sum(v["grad_nonzero"] for v in rep["heads"].values())
                    gz = sum(v["grad_None"] for v in rep["heads"].values())
                    log(f"[gate] 4 个可训头逐模块: 非零梯度模块 {gn} · **不在损失图里(grad=None)** {gz} "
                        f"⇒ 死区 {rep['dead_zone'] if rep['dead_zone'] else '无'}")
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            seen += 1
            el = time.time() - t_start
            if seen % args.log_every == 0 or seen == 1:
                vr = torch.cuda.max_memory_allocated() / 1e9
                rec = {"step": seen, "epoch": ep + 1, "loss": round(parts["total"], 5),
                       **{k: round(v, 5) for k, v in parts.items() if k != "total"},
                       "s_per_step": round(el / seen, 3), "peak_gb": round(vr, 3)}
                logf.write(json.dumps(rec) + "\n"); logf.flush()
                log(f"[train] step {seen:4d} (ep{ep+1}) loss {parts['total']:.4f} "
                    f"(mask {parts.get('mask_bce',0)+parts.get('mask_dice',0):.3f} box {parts['box_l1']+parts['box_giou']:.3f} "
                    f"cls {parts['cls']:.3f}) s/step {el/seen:.3f} peak {vr:.2f}GB")
                hist.append(rec)
            if args.max_steps and seen >= args.max_steps:
                break
        if args.max_steps and seen >= args.max_steps:
            break
    total_s = time.time() - t_start
    logf.close()

    # 闸二: 免基准判据 (B 零初始化 ⇒ 非零 = 训过)
    tot_b, nz_b, mx_b = nonzero_lora_b(model)
    log(f"[gate] 免基准判据 lora_B: {nz_b}/{tot_b} 条非零 · 最大|B| {mx_b:.3e} ⇒ "
        f"{'✅ 全部适配器都训练过' if nz_b == tot_b else '❌ 有适配器从未更新'}")

    from .lora_inject import delta_norm_ratio
    dn = delta_norm_ratio(model)
    ratios = sorted(x[1] for x in dn)
    med = ratios[len(ratios) // 2] if ratios else 0.0
    bf16_eps = 2 ** -8
    log(f"[fold] ‖ΔW‖/‖W‖ 中位 {med:.3e} · 最大 {max(ratios) if ratios else 0:.3e} vs bf16 eps {bf16_eps:.1e} ⇒ "
        f"{'⛔ 禁止折进 bf16 (会被抹掉), 保持适配器路径加载' if med < bf16_eps else '可折进 bf16'}")

    # 产物
    from safetensors.torch import save_file
    adir = Path(args.out) / "lora_adapter"
    adir.mkdir(parents=True, exist_ok=True)
    sd = {n: p.detach().to(torch.float32).cpu().contiguous() for n, p in lora_named(model)}
    save_file(sd, str(adir / "adapter_model.safetensors"))
    meta = {"base": args.model_dir, "size": args.size, "r": args.r, "alpha": args.alpha,
            "lora_vit_blocks": args.lora_vit_blocks, "steps": seen, "epochs": args.epochs,
            "dataset": args.dataset, "n_train": len(train), "n_val": len(val),
            "n_boxes": sum(len(s.boxes_xyxy) for s in train + val),
            "trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "lora_params": sum(p.numel() for _, p in lora_named(model)),
            "supervision": {"A_text_to_box": "真标注(GT 框)", "B_box_to_mask": "教师伪标签(SAM3 冻结基座,框提示)"},
            "prefix_canon": "lora_A=[r,in] lora_B=[out,r]; 折叠时键去掉 .base."}
    (adir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    gates["final"] = {"lora_B_nonzero": nz_b, "lora_B_total": tot_b, "lora_B_max": mx_b,
                      "delta_ratio_median": med, "bf16_eps": bf16_eps}
    (Path(args.out) / "gates.json").write_text(json.dumps(gates, indent=1, ensure_ascii=False))

    # 验证集对照 (前后**同口径**: 同 seed/同抖动/同 5 帧)
    val_clean = evaluate(model, val, names, cache, args, jitter=0.0, seed=1234, tag="val@final(精确框)", log=log)
    val_aug = evaluate(model, val, names, cache, args, jitter=args.box_jitter, seed=1234,
                       tag="val@final(抖动框)", log=log)
    d_mask = val_aug["mask_iou_vs_teacher"] - _banner0["mask_iou_vs_teacher"]
    d_box = val_aug["box_iou_vs_gt"] - _banner0["box_iou_vs_gt"]
    log(f"[A/B] 抖动框掩膜IoU 基座 {_banner0['mask_iou_vs_teacher']:.4f} → 微调后 "
        f"{val_aug['mask_iou_vs_teacher']:.4f} (Δ{d_mask:+.4f}) · 框IoU {_banner0['box_iou_vs_gt']:.4f} → "
        f"{val_aug['box_iou_vs_gt']:.4f} (Δ{d_box:+.4f})")
    prod = sorted(glob.glob(str(Path(args.out) / "**" / "*"), recursive=True))
    sz = sum(os.path.getsize(f) for f in prod if os.path.isfile(f))
    return {"data": {"n_train": len(train), "n_val": len(val),
                     "n_train_boxes": sum(len(s.boxes_xyxy) for s in train),
                     "n_val_boxes": sum(len(s.boxes_xyxy) for s in val), "classes": names},
            "model": minfo, "steps": seen, "total_s": total_s, "s_per_step": total_s / max(seen, 1),
            "peak_gb": torch.cuda.max_memory_allocated() / 1e9, "hist": hist,
            "gates": gates, "val": val_aug, "val_step0": _banner0, "val_clean": val_clean,
            "val_delta_mask_iou": round(d_mask, 4), "val_delta_box_iou": round(d_box, 4),
            "adapter_path": str(adir), "adapter_bytes": sz, "out": args.out}


@torch.no_grad()
def evaluate(model, val: list[Sample], names: list[str], cache: dict, args, jitter: float = 0.0,
             seed: int = 1234, tag: str = "val", log=print) -> dict:
    """同口径 A/B 指标: 掩膜 IoU (预测 vs 教师掩膜) · 框 IoU (预测 vs GT 框)。
    ⚠️ 掩膜 IoU 的对照方是**教师伪标签**(不是人工标注) —— 报告里必须这么写。
    jitter>0 = 提示框被抖动 ⇒ 衡量"框不准时的鲁棒性"(提示式微调的价值所在)。"""
    model.eval()
    rng = np.random.default_rng(seed)
    mi, bi, nq = [], [], 0
    for s in val:
        boxes = jitter_boxes(s.boxes_xyxy, jitter, rng)
        inp = {k: (v.to("cuda") if k != "original_sizes" else v) for k, v in cache[s.stem].items()}
        inp["pixel_values"] = inp["pixel_values"].to(torch.bfloat16)
        bb = torch.tensor([[[( (b[0]+b[2])/2)/s.W, (((b[1]+b[3])/2))/s.H, (b[2]-b[0])/s.W, (b[3]-b[1])/s.H]
                            for b in boxes]], dtype=torch.bfloat16, device="cuda")
        inp["input_boxes"] = bb
        inp["input_boxes_labels"] = torch.ones(bb.shape[:2], dtype=torch.long, device="cuda")
        out = model(**inp)
        hw_ = int(out.pred_masks.shape[-1])
        pm = out.pred_masks[0].float().sigmoid()
        pred_boxes = out.pred_boxes[0].float()
        gt = torch.tensor([[b[0] / s.W, b[1] / s.H, b[2] / s.W, b[3] / s.H] for b in s.boxes_xyxy],
                          dtype=torch.float32, device="cuda")
        qi, gi = match_queries(pred_boxes, gt)
        tms = [torch.as_tensor(load_teacher_mask(teacher_mask_path(args.cache_dir, s, i), hw_)[0], device="cuda")
               for i in range(len(s.boxes_xyxy))]
        for q, g in zip(qi.tolist(), gi.tolist()):
            m = pm[q] > 0.5
            t = tms[g]
            u = (m | t).sum().clamp(min=1)
            mi.append(float((m & t).sum()) / float(u))
            bi.append(float(_box_iou(pred_boxes[q], gt[g])))
            nq += 1
    res = {"tag": tag, "jitter": jitter, "n_queries": nq,
           "mask_iou_vs_teacher": round(float(np.mean(mi)) if mi else 0.0, 4),
           "box_iou_vs_gt": round(float(np.mean(bi)) if bi else 0.0, 4)}
    log(f"[{tag}] 抖动 {jitter:.2f} · 匹配 {nq} 个 query ⇒ **掩膜IoU(对教师伪标签) {res['mask_iou_vs_teacher']:.4f}**"
        f" · 框IoU(对GT框) {res['box_iou_vs_gt']:.4f}")
    model.train()
    return res
