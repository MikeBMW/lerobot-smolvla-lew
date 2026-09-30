---
name: edge-finetune-automation
description: Use when 端侧(AIPC/Orin/笔记本)自动化微调 — 8阶段流水线+判据+坑。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finetune, lora, qlora, quantize, edge, aipc, pipeline-automation]
    related_skills: [zmax-joint-training-deploy, zmax-multilayer-pipeline, disk-redline-guard]
---

# 端侧微调自动化（8 阶段流水线 Skill）

## When to Use
- 要在**端侧**（Intel AIPC / NVIDIA 笔记本 / Orin 边缘盒）本地微调模型，不上传数据
- 要把「装环境→理数据→写配置→调量化→跑训练→出对比」这套重复劳动交给 Agent 自主执行
- 目标模型是**多模态大模型/扩散模型**（Qwen-Image-Edit 类）或机器人策略（SigLIP+头）
- 显存紧张（消费级卡/集显 NPU），需 NF4/int8 量化 + LoRA 低秩微调
- 需要**可回滚、可复现、有判据**的微调（不是"跑完就算成功"）

## 核心原则（先立规矩，再跑流水线）
```
① 判据先行: 每阶段定义 gate, 不过 gate 不进下一阶段
② 只信留出集 + 平凡基线: 训练 loss 不作证据（血泪: 0.0003 漂亮但输出发散）
③ 基座永不改: 只训 adapter(几 MB) → 回滚 = 删目录
④ 全程可复现: 种子/数据 hash/超参/产物 hash 落盘
⑤ 跨源先验口径: 换数据集必先逐通道比 obs/action/图像 的均值方差
```

## 8 阶段流水线（含 gate 与命令）

### 01 Preflight 预检 — gate: 硬件/驱动/依赖/模型齐全
```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader   # 或 xpu-smi (Intel)
python -c "import torch;print(torch.__version__, torch.cuda.is_available() or torch.xpu.is_available())"
ls -la <模型目录>            # 权重完整性 (文件数+大小, 别只看目录存在)
df -h /                      # 磁盘红线 (训练要留 ≥2x 数据量)
```
**判据**: 显存 ≥ 模型 fp16 体积 ×2.5（含激活）· 权重文件非 0 字节 · 磁盘 ≥ 数据×2
**失败**: 显存不足 → 降 batch/开梯度检查点/上 NF4；权重缺 → 先补齐再继续

### 02 Dataset 数据集 — gate: train/val 切分 + 口径同源
```bash
# 校验: 帧数/维度/非零率/取值范围
python -c "import h5py,numpy as np;f=h5py.File('data.h5');print({k:f[k].shape for k in f})"
```
**判据**: 留出集非空（**按时间/episode 切，不随机**）· 图像非零率 >0.9 · 各通道量纲与原训练集一致
**坑（必查）**: 我踩过 3 次——换数据源后 **obs/action 逐通道均值差 >0.05 就是口径不同**，不是模型问题
**小样本**: 必须混 **25% 回放数据**，否则灾难性遗忘

### 03 Env Setup 环境 — gate: import 成功 + 设备可见
```bash
# CUDA
python -m venv .venv && .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu124
# Intel XPU
pip install torch --index-url https://download.pytorch.org/whl/xpu
# 国内镜像加速
pip install -i https://mirrors.aliyun.com/pypi/simple/ <deps>
```
**判据**: `torch.cuda.is_available()` 或 `torch.xpu.is_available()` 为 True · 目标模型 forward 一次通过
**坑**: 多框架多 venv 时**别指望同进程**；跨 venv 用子进程桥（采集落 npz → 另一 venv 读）

### 04 Config 配置生成 — gate: 配置由硬件反推而非拍脑袋
```
自动推导: batch = f(显存, 图像尺寸, 模型大小)  ← 用二分搜索实测打满显存
lr = 3e-4 (LoRA 常用) · wd = 1e-2 · r = 8 · alpha = 16
eval_every = steps/12 · patience = 5 (早停)
```
**判据**: 配置里含 数据/留出/量化/LoRA/早停 五项，缺一不可

### 05 Adaptation 适配移植 — gate: 目标后端前向+反向都通
```python
# LoRA 注入 ★顺序坑: 必须"先注入、后 .to(device)"
inject_lora(net, targets=["q_proj","k_proj","v_proj","out_proj","fc1","fc2"], r=8, alpha=16)
net = net.to(device)     # ← 若反过来, 新建的 A/B 层留在 CPU → device mismatch 报错
for p in net.base.parameters(): p.requires_grad = False   # 基座冻结
```
**判据**: 可训参数占比 **1-3%**（我实测 1.49%）· backward 梯度非零 · 显存可容纳

### 06 Quantize 量化 — gate: **量化后精度退化 ≤8%**
```python
# NF4 (QLoRA, 最省显存) / int8 (动态) / bf16 (半精度)
# 量化后必须逐指标与 fp32 对比, 退化超阈值 → 拒绝量化
```
**实测模板**（`tools/edge_finetune.py --quant`）:
```
fp32 : L4 0.0130 · 动作 0.0830 · 88.89 MB
int8 : L4 0.0131 · 动作 0.0831 · 22.20 MB  (体积 ↓4x)
精度变化: +0.8% / +0.1%  → ✅ 可接受
```
**判据**: |Δ| ≤ 8%（我设的阈值）· 体积比 ≥2x 才有意义

### 07 Training 训练 — gate: 留出改善 **且** 不过拟合
```bash
python tools/edge_finetune.py --data new.h5 --replay base.h5 \
  --steps 300 --lr 3e-4 --wd 1e-2 --lora-r 8 --patience 5 --out out/
```
**四层优化开关**（每层都有实测收益 · 本机 4060L + SigLIP-86M, batch24）:
```
① 算子层: TF32 + cudnn.benchmark + channels_last
② 流程层: bf16 AMP + 梯度累积 + 内存像素缓存
③ 量化层: 见 06
④ 端侧  : 冻结基座 + 只训 LoRA/heads

★ 实测收益 (tools/edge_finetune.py --bench):
   基线(无优化)         : 348.2 ms/步 ·  68.9 样本/s · 峰值 3150 MB
   ②+bf16 AMP          : 180.8 ms/步 · 132.8 样本/s · 峰值 2254 MB  → 吞吐 **1.93x** · 显存 **-28%**
   ②+AMP+channels_last : 160.9 ms/步 · 149.2 样本/s · 峰值 2254 MB  → 吞吐 **2.17x**
   大 batch x2         : 126.9 样本/s · 峰值 3985 MB (等效累积; 显存换吞吐)
   LoRA 可训参数       : 1,327,104 / 88,889,987 = **1.49%**  (72 层, r=8/alpha=16)
```
**判据**: 留出 MAE **优于平凡基线**（obs 恒输出均值 / 动作恒输出 0）· best 出现在中后段（非 step1）· 早停触发即收
**血泪**: 旧架构 500 步就把训练集背下来（loss 0.0015）而留出恶化 2.5× → **必须早停+存留出最优**

### 07b 两阶段配方（2026-09-23 实测 · 精度与鲁棒性兼得）
```
症状: 想要"几何不变形"(抗位姿漂移) 就得加几何域增强, 但增强了精度会掉
      (实测: 留出 0.008 → 0.010, 一度以为这是不可调和的 **权衡** — **错了**)

★ 正解: 两阶段
  阶段1 (表征层): 加**几何域增强**(平移±8px / 缩放 0.90~1.10 / 旋转±5°) 训练
        → 把"几何不变性"练进**表征** (特征层面变鲁棒)
  阶段2 (输出层): **关掉增强**, 短程微调 (lr 减半, **600 步足够**)
        → 在已鲁棒的表征上精修输出头 → 精度回来, 鲁棒性**不退**

实测 (同一批引擎样本, 同判据):
  仅阶段1 : 留出 0.010/0.048 · cos 平移0.994/缩放0.966/旋转0.996 · 一致性 15.5%
  阶段2=600步: 留出 **0.008/0.047** · cos **0.997/0.997/0.998** · 一致性 **6.8%** ← 最优
  阶段2=4000步: 留出 0.008/0.045 · cos 0.985/0.994/0.996 · 一致性 13.4% ← 鲁棒性被磨掉一半
⇒ **阶段2 越短越好 (600 步)**; 拉长只换来动作 0.002 的微增, 却让鲁棒性单调劣化
⇒ 机理: 增强改**表征**, 微调只动**输出头** → 二者本不冲突

工程支撑: `--init <ckpt>` 从阶段1 权重续训; `--aug-scale lo,hi` 调增强强度
⚠️ 改任何配置类参数后**必须核验生效**(打印/hash) — 我踩过 `--aug-scale` setter 静默失效,
   导致两次训练的 ckpt **sha256 完全相同**(同一权重当成两个结果上报), 结论作废
```

### 08 Validation 验证 — gate: 有提升才进默认档
```
产出三方对比:  ① 基座  ② 微调后(adapter)  ③ 平凡基线
指标: 留出 MAE / 任务成功率 / 图像效果对比图
脱敏表述: "符合 X 个场景的方案技术协议"(不用"白盒交付")
```
**判据**: **有提升非仅不回退**；无提升 → 保留 adapter 但不进默认档，如实上报

## 部署与回滚
```bash
# 部署: adapter 可 merge 进基座, 也可运行时挂载(swap 不重载基座)
python tools/lora_merge_ckpt.py --base base.pt --adapter out/adapter.pt --out merged.pt
# 回滚: 删 adapter 目录即可 (基座从未改动)
rm -rf out/
```
**假接入检测（部署后必查）**: 引擎/宿主给出的**融合权重 w 必须 >0**
（我踩过: 节点挂上、每帧被调、但 w=0 → 输出零贡献 = 假接入；
根因通常是宿主只从 `out.diagnostics['intent_norm']` 这类**字典字段**取置信度）

## 🔴 训练进程的 cgroup 内存上限（2026-09-24 实测，踩了 5 次）
```
症状: 训练在"载入像素缓存"时被杀(exit -9), 但 free 显示还剩 ~20GB 空闲
定位: sudo dmesg -T | grep 'Memory cgroup out of memory'
      → oom-kill: constraint=CONSTRAINT_MEMCG,
                  oom_memcg=.../hermes-worker-proc_XXX.scope
      → 被杀进程 total-vm 仅 8.5GB
原因: **Agent 工具给每条命令套的临时 systemd scope 有内存上限(~8GB, 动态)**
      —— 不是机器内存不足! 父 slice 显示 max 也没用, 限在 transient scope 上
⇒ 对策:
   a) 大数据集**不开像素缓存** → 磁盘流式(慢 3-5x 但不崩)
   b) 或把数据集切到"缓存 ≤5-6GB"的规模
   c) 缓存上限**按 /proc/meminfo MemAvailable 自动算**(别硬编码 20GB)
   d) 跑大缓存前 `sync; sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'` 清页缓存
   e) **同一时刻只跑一个加载模型的进程**(并发两个必 OOM)
⇒ 诊断三部曲: dmesg 看 CONSTRAINT_MEMCG → 看 oom_memcg 是哪个 scope → 比对 free -g
⚠️ 被 OOM 中断写出的 h5 会**损坏**(`bad object header version`) → 重建后再用
⚠️ 改配置/加开关时**补丁必须覆盖所有调用点**: 同一函数有 2 处调用, 只改一处 = 没改
   (我因只改了 make_loader 而漏掉真调用点, 大缓存照装 → 又一次 OOM)
```

## Agent 自主执行要点
1. **每阶段先跑 gate 检查**，不过就修，不跳到下一步
2. **全程日志落盘**（`--out` 里放 `finetune_report.json`：超参/曲线/最优步/耗时/参数占比）
3. **不夸大**: 只报留出指标与基线对比；无提升就说无提升
4. **资源纪律**: 磁盘红线（训练产物只留最后 ckpt）；GPU 满载前先查占用
5. 平台无关: 上述在 **CUDA / Intel XPU / NPU** 上等价（仅 03 的 wheel index 不同）
