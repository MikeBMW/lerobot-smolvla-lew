# 全负荷联合集训 + 留出集评估 (2026-09-23 实测)

老倪指令: "L5层继续定方向, 造数据; L4认知预测; L3状态调度; L2检测反馈; 加大力度集训"
         "模型要一起训练 GPU必须全负荷工作"

---

## 一、★ 最重要的一课: 训练 loss 低 ≠ 学到

```
联合集训 V6 (4 层同图, 20000 步, 真数据 236,250 帧, batch 128)
  训练 loss 轨迹: 0.2500 → 0.0011(step500) → 0.0007(step1000) → 0.0003(step2000)
  → 看起来完美收敛

留出集评测 (L5 生成的新方向变体, 训练从未见过的 dy/f/v 组合):
  A 联合集训 joint_full_v6 : 动作 MAE 2.703 · 观测预测 MAE 30.271 · L2 一致性 11.576
  B 在役基线 intact_l4_current : 动作 MAE 1.062 · 观测预测 MAE 28.598 · L2 一致性 15.286
  → **A 相对 B 退化 154.4%**

结论: 训练 loss 0.0003 完全是"记住训练集"（64k 样本就压到 1e-3 量级 = 背诵）。
      训练 loss 作为效果证据的价值 = 0。
```

### 铁律
1. **绝不用训练 loss 当效果证据。** 必须留出集。
2. **留出集要用域迁移，不用同分布随机切分**（同分布自评会高估）:
   - 训练集 = v5/v6 真轨迹（236,250 帧）
   - 留出集 = **L5 生成的新方向变体**（pixels + obs + action + goal 齐全）
3. **报告"训练 loss vs 留出 loss 差距"** = 过拟合程度的直接量化。

---

## 二、★ A/B 口径必须公平（本次实际踩到的评估设计缺陷）

```
反例 (无效比较):
  A 臂的动作走 "联合训练新加的 L3 头"
  B 臂的动作走 "在役 L4 的 intent_actor"
  → 两条路的动作定义不同 ⇒ 谁好谁坏都说明不了问题

修法:
  两臂走**同一个动作出口** — 要么都走 L3 头(只换 L4 权重), 要么都旁路联合头走 intent_actor

纪律:
  评估脚本里**显式打印"动作来源"**; 来源不同就直接拒绝出结论。
```

### 配套: checkpoint 必须确认是本轮产物
```
本次误评了一个"比当前长跑早 1 分钟"的旧 ckpt:
  joint_full.pt mtime = 01:09:54  vs  长跑进程 lstart = 01:10:18
检查: stat -c '%y' <ckpt>  对比  ps -o lstart= -p <pid>
```

### 配套: h5py 取帧索引必须升序
```python
idx = np.sort(rng.choice(total, size=n, replace=False))   # ✓
idx = rng.permutation(total)[:n]                          # ✗ TypeError:
    # Indexing elements must be in increasing order
```

---

## 三、全负荷 GPU 集训配置（RTX 4060 Laptop 8GB 打满实测）

工具: `tools/joint_train_full.py`

```bash
/home/ubuntu/INTACT-JEPA/.venv/bin/python -u tools/joint_train_full.py \
    --steps 20000 --workers 6 --stats 500 \
    --save /home/ubuntu/stable-wm-cache/checkpoints/joint_full_v6
```

| 项 | 配置 | 说明 |
|---|---|---|
| batch | **自动搜索 → 128** | 逐档试跑取峰值显存; 8→128 峰值 5193MB; 192 档 OOM 自动降档 |
| 显存阈值 | **5200MB** | ✗ 7000MB 会 OOM（8192MB 总量下别的进程占 ~460MB） |
| AMP | **关** | 见下方 dtype 冲突 |
| DataLoader | 6 workers + pin_memory | 不足会 GPU 饥饿, 利用率在 57-100% 抖动 |
| 其他 | cudnn.benchmark + TF32 + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` | |
| GPU 监控 | **外部 nvidia-smi 采样** | `torch.cuda.utilization()` 需 pynvml, 会崩 |

实测: 2.2 步/s · 显存 7070MB · **GPU 96-100%** · loss 0.25→0.0003

### 🚨 AMP 与自研 JEPA 的 dtype 冲突
```
RuntimeError: Input type (float) and bias type (c10::Half) should be the same
  at Conv2d(3, 16, kernel_size=(7,7), ...)
根因: 自研 JEPA 内部按 fp32 跑; autocast 把自定义模块的权重转成 Half → 输入仍 fp32
修: **关 AMP, 用 fp32 + 大 batch 打满显存**（不靠 AMP）
```

### 训练循环要 OOM 优雅降档
```python
try:
    obs, act, px, goal = next(it)
except StopIteration:
    it = iter(dl); obs, act, px, goal = next(it)
except torch.cuda.OutOfMemoryError:
    torch.cuda.empty_cache(); bs = max(4, bs // 2)
    dl = make_loader(bs); it = iter(dl); continue
```

---

## 四、★ L4 JEPA 动作维对齐（真数据 4 维 vs 在役 ckpt 8 维）

```
在役 ckpt 的 action_encoder 期望 **8 维**:
  config.json: action_encoder = {input_dim: 8, smoothed_dim: 8} → Conv1d(8, 8, 1)
真数据 action 只有 **4 维** → 必须补零: F.pad(act, (0, 4))
```

### 🚨 只补一处必踩（本次两轮才定位）
```python
# ✗ 只补 action_encoder —— 报 expected input[8,4,1] to have 8 channels
#   （因为 jepa.encode(info) 内部也消费 info["action"]）
# ✓ 补零后的 action 要同时喂 info["action"] 和 action_encoder:
act_e = F.pad(act, (0, d_enc - act.shape[-1]))   # (b, 8)
info  = {"pixels": px.unsqueeze(1), "action": act_e.unsqueeze(1)}   # ★ encode 也用
enc   = jepa.encode(info)
a_emb = jepa.action_encoder(act_e.unsqueeze(1))
```
引擎侧同样处理（引擎启动日志: "动作维对齐 4 → 10 (来自模型实测)"）。

### 其他形状契约（见 zmax-joint-training-deploy 的接口节）
- `pixels` = **(b, t, c, h, w)** 5D
- `action` = **(b, t, d)** 3D（ARPredictor 内部 `rearrange("b t d -> (b t) d")`）
- ViT 输出 `(b,t,257,192)` → 取 **CLS token** `[:,:,0,:]`

---

## 五、L5 定方向 · 造数据

工具: `tools/l5_plan_and_gen.py`（gui-venv311; `nice -n 19` 让 GPU 给训练）

```bash
gui-venv311/bin/python tools/l5_plan_and_gen.py \
    --n 250 --steps 300 --vision 1 \
    --out /home/ubuntu/stable-wm-cache/datasets/l5_gen_v2.h5 --save-every 20
```

```
方向谱 = 对位偏差 dy±20mm × 高度 dz±10mm × 阶段组合 × 力档(30/40/50) × 速度(0.8/1.0/1.2)
每变体引擎真跑 → obs(39) + action(4) + 该阶段真渲染帧(224×224×3) + goal(39)
实测: 250 变体 × 300 步 = 75,000 帧 / 547s (138 帧/s, vision=False)
      150 变体 × 300 步 = 45,000 帧 / 2429s ( 19 帧/s, vision=True)
```

### 🚨 必须 `vision=True`，否则像素全零（本次 75k 帧报废）
```
引擎 `_key_frames` **只在 vision 开启时采集**（在 perception refresh 内,
且需 `_kf_cnt >= 6` 同阶段连续帧才开始记）→ vision=False 造出的 pixels 全是 0

验证真渲染: 非零率 > 0.99 且均值 ~130
            (全零 / 均值 0 → 废数据, 必须重造)

诚实标注: pixels = "该阶段的关键帧按阶段复用", 不是每步独立渲染。
```
obs/action 即使 vision=False 也是真值（实测非零率 74% / 88%）→ 单独可用于
动作/世界模型维度, 但 L2 感知通道需要真渲染。

---

## 六、本轮四层职责 → 代码映射（老倪定义）

| 层 | 老倪定义 | 实现 |
|---|---|---|
| L5 | 定方向 · 造数据 | `l5_plan_and_gen.py`（规划器展开方向×变体 → 引擎真跑 → h5） |
| L4 | 认知预测 | `joint_train_full.JointFull`（ViT 编码 → ARPredictor → obs_head 显式监督） |
| L3 | 状态调度 | 官方同构动作头（z_pred → 阶段/动作序列） |
| L2 | 检测反馈 | 像素 → 检测 token + 反馈一致性头（l2_cons） |
| 记忆 | 联络协同 | 五层记忆(681 段冠军轨迹) → mem_cond 注入潜空间 |
