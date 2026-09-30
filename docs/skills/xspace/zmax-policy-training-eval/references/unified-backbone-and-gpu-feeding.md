# 统一 backbone 改造 + GPU 喂饱 (2026-09-23 收尾, 泛化问题的解药)

> 承接 `references/joint-training-holdout-eval-corrections.md`。
> 那篇的结论是"三组配置一致过拟合 ⇒ 瓶颈在数据/任务可泛化性"。
> **本文是该瓶颈的定位与解药** —— 真因不是数据多样性, 是**主干太弱**。

---

## 一、★ 结论: 泛化的解药是换主干, 不是调超参

| 架构 | 共享主干 | 同源留出集表现 | 判定 |
|---|---|---|---|
| 旧: 各层独立 + 投影拼接 | L4 的 **ViT-tiny 192d `pretrained: false`**（from scratch） | 观测 MAE 18.1 → **45.2**（2.5× 劣化）| ❌ 崩 |
| 旧 + 冻结基座 + 强正则 | 同上（冻结） | 11.9 → **402.7**（34× 劣化） | ❌ 更糟 |
| **统一 backbone** | **SmolVLM2 视觉塔 = 预训练 SigLIP 768d (86.4M)** | 0.171 → **0.019**（9× 改善）| ✅ **打赢平凡基线** |

```
根因: 用**从零训练的小视觉编码器**当共享主干 → 它只能背训练集
      (L4 的 config: {"_target_": "stable_pretraining...vit_hf", "size": "tiny",
                      "pretrained": false} ← 这个 false 是病根)
解药: 主干换成**预训练**视觉表征, 四头共享
⇒ "统一 backbone 改造"的真正价值不是"少几个模型", 而是**换掉弱主干**

⚠️ 冻结基座 / 强正则 / 结构限幅 都**治不了**这个病（都实测过）——
   它们治的是别的病（表征破坏、输出发散）。泛化 = 主干质量。
```

### 统一主干实测曲线（8GB 卡, 冻结主干）
| step | 训练 loss | 留出 L4 认知预测 | 留出 动作 |
|---|---|---|---|
| 1 | 0.3180 | 0.171 | 0.237 |
| 100 | 0.0261 | 0.036 | 0.085 |
| **200** | 0.0115 | **0.019** ✅ | **0.060** ✅ |
| 300 | 0.0129 | 0.021（持平） | 0.059（持平） |

→ 打赢平凡基线（§二）且**不过拟合**（旧架构同期已劣化 2.5×, 这里持平）。

---

## 二、平凡基线 = 标尺（必须先算, 否则数字无意义）

v6 随机留出集（8,715 帧, 39 维 obs / 4 维 action）上实测：

```
动作恒定输出 0          : MAE 0.2362
动作恒定输出训练均值     : MAE 0.0947
观测恒定输出训练均值     : MAE 0.0366   ← L4 认知预测的及格线
```

判据: **模型留出 MAE 必须低于对应平凡基线**才算"真学到"。
统一主干: 0.019 < 0.0366 ✅ / 0.060 < 0.0947 ✅。
生成脚本: `tools/split_rand_holdout.py`（随机切分 + 一并打印这些基线）。

---

## 三、统一主干实现要点 (`tools/joint_unified_backbone.py`)

### 3.1 取视觉塔（transformers 5.x 顶层就是 vision_model）
```python
from transformers import AutoModel
full  = AutoModel.from_pretrained("HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
                                  dtype=torch.float32)
trunk = full.vision_model          # ★ 顶层子模块: vision_model / connector / text_model
del full                           # 只留 86.4M 视觉塔, 不拖 460M 的 LLM
for p in trunk.parameters():
    p.requires_grad_(False)        # 冻结, 保护预训练表征
```
取错路径（`full.model.vision_model`）→ `None` → `AttributeError: 'NoneType' object has no attribute 'to'`。

### 3.2 规格与成本（8GB 卡实测）
```
视觉塔 86.4M · hidden 768 · 12 层 · patch 16 · 预训练 SigLIP
batch  4 : 494MB / 179ms
batch 16 : **986MB** / 29ms      ← 只吃 1GB, 8GB 卡绰绰有余
冻结主干 + 挂头: 梯度 4.58e+00 (非零 ✓)
```

### 3.3 四头结构（共享主干输出 768d）
```
L4 认知预测: concat(meanpool(768), obs39) → 512 → 256 → {obs_next(39), z(192)}
L2 检测反馈: 768 → 256 → 64 → 192  (与 z 做一致性)
L5 场景token: 768 → 256 → 64
L3 状态调度: concat(z(192), scene(64)) → 256 → chunk×4, **最后 tanh 限幅**
记忆注入   : mem(13) → 64 → 192, 与 z 相加
```

### 3.4 ⚠️ GPU 利用率: 这个架构算力需求本来就低
```
冻结 86.4M 主干 + 只有 1.13M 可训头 → 每步 GPU 活很少
实测利用率 50-100% 波动（对比全参微调 2100 万参数时能到 96-100%）

用户硬要求是"GPU 必须全负荷" ⇒ 该架构要喂满需:
   ① 大 batch（128 → 384）  ② 解冻主干 / 加 LoRA 让主干参与  ③ 加更多任务头
别再只加 workers —— 数据侧不是瓶颈时加 worker 无效（见 §四）。
```

---

## 四、★ GPU 饥饿的真因: h5 分块尺寸（不是 worker 数）

```
症状: batch 128 + 24 workers, GPU 仍只有 2%
真因: **h5 分块 512 帧/块**
      → 随机取 1 帧要解压整块 (224×224×3×512 ≈ 75MB)
      → 数据管道被 IO 锁死, GPU 饿着

错解: 加 workers (8 → 24)  —— 无效
对解: 建 DataLoader(fork) **之前** 把像素整块读进 RAM, 所有 worker COW 共享
```
```python
class RealH5(Dataset):
    _PIX_CACHE = None            # 类级: fork 前填 → 子进程共享

    @classmethod
    def build_pixel_cache(cls, files, cap_bytes=14 * 1024**3):
        tot = sum(int(h5py.File(p, "r")["pixels"].shape[0]) for p in files)
        per = int(h5py.File(files[0], "r")["pixels"][0].nbytes)
        if tot * per > cap_bytes:
            print(f"  ⚠️ 像素缓存需 {tot*per/1024**3:.1f}GB > 上限 → 跳过")
            return None
        arr = np.empty((tot,) + pix_shape, dtype=np.uint8)
        o = 0
        for p in files:                       # 顺序读, 块利用率 100%
            fh = h5py.File(p, "r"); n = int(fh["pixels"].shape[0])
            for s in range(0, n, 8192):
                arr[o+s:o+min(n, s+8192)] = fh["pixels"][s:min(n, s+8192)]
            o += n; fh.close()
        cls._PIX_CACHE = arr
        return arr

# main(): 必须在 make_loader 之前调用
if a.pixel_cache:
    RealH5.build_pixel_cache(files)
dl = make_loader(files, a.batch, a.workers, a.chunk)
```
```
容量实算: 78,435 帧 × 150,672 B ≈ **11.0GB**（23GB 可用内存下可行）
超上限时必须**打印警告并跳过**, 不要静默降级。
```

---

## 五、训练目标必须是"真未来"（别用 torch.roll）

```python
tgt = torch.roll(obs, -1, 0)     # ✗ shuffle=True 下配到的是随机帧 → 目标是噪声
```
数据集里直接返回真未来（索引越界用 `min(j+k, N-1)` 夹住）：
```python
jn = min(j + 1, N - 1)
obs_next = np.asarray(f["observation"][jn], dtype=np.float32)
jc = np.stack([np.minimum(j + k, N - 1) for k in range(chunk)], 1)
```
评估同样要用真未来（`fh["observation"][idx + 1]`），否则指标无意义。

### h5py 索引约束（两种都踩过）
```
TypeError: Only 1D arrays allowed for fancy indexing       → 2D 索引要 ravel 再 reshape
TypeError: Indexing elements must be in increasing order   → 必须升序；且不能有重复
```
取"每样本未来 chunk 动作"时 2D 索引不升序且有重复 → 改**连续块读 + numpy 索引**：
```python
jc = np.minimum(jc, Nc - 1)
lo, hi = int(jc.min()), int(jc.max())
blk = np.asarray(fh["action"][lo:hi + 1], dtype=np.float32)   # 一次连续读
a   = blk[jc - lo]                                            # (n, chunk, 4)
```

### DataLoader 返回的是 Tensor（不是 ndarray）
`torch.from_numpy(px)` 会报 `TypeError: expected np.ndarray (got Tensor)`。
图像预处理函数写成两种都收：
```python
x = px if torch.is_tensor(px) else torch.from_numpy(np.asarray(px))
```

---

## 六、命令行
```bash
# 统一主干联合训练 (真数据 + 有效随机留出 + 内存像素缓存)
/home/ubuntu/INTACT-JEPA/.venv/bin/python -u tools/joint_unified_backbone.py \
    --steps 1500 --batch 128 --workers 16 --stats 100 \
    --lr 5e-4 --wd 0.01 --pixel-cache 1 \
    --files    /home/ubuntu/stable-wm-cache/datasets/v6_train_rand.h5 \
    --holdout  /home/ubuntu/stable-wm-cache/datasets/v6_holdout_rand.h5 \
    --save     /home/ubuntu/stable-wm-cache/checkpoints/unified_siglip

# 随机切分 + 平凡基线 (改数据后重算)
gui-venv311/bin/python tools/split_rand_holdout.py
```

---

## 七、待办（交给下一轮）
```
① GPU 喂满: batch 128 → 384, 或解冻主干/LoRA（§3.4）
② 接进引擎闭环做端到端验证（统一产物 → 引擎 select_action → A/B）
③ L5 造数据若要与 v5/v6 同源, 需先给引擎 run() 加 env 原生 obs 记录
   （见 corrections §一; 现有 l5_gen_v2.h5 的 obs 源不同, 只能当独立数据集）
```
