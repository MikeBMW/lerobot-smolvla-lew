# 场景映射：Intel AIPC + Qwen-Image-Edit + NF4 QLoRA

把展板的 8 阶段落到**具体代码动作**。平台：Intel 酷睿 Ultra（XPU/NPU）· 全程本地、不出网。

## 01 Preflight 预检
```bash
xpu-smi 2>/dev/null || nvidia-smi                       # 认算力单元
python -c "import torch;print(torch.__version__, torch.xpu.is_available())"
ls -l $MODEL_DIR/*.safetensors | wc -l                  # 权重文件数
du -sh $MODEL_DIR $DATA_DIR; df -h /                    # 体积与磁盘
```
**Gate**: XPU 可见 · 权重非 0 字节 · 磁盘 ≥ 数据×2 + 模型×1.5
**缺什么提前告知用户**（展板 Step01 的"Agent 指导用户"就指这里）

## 02 Dataset 数据集
```python
# 图像编辑数据集: 三元组 (原图, 指令, 目标图)
# Agent 自动: 尺寸对齐 / 去重 / 去坏图 / 切 train:val = 85:15
# 留出集必须按"来源/场景"切, 不随机 —— 否则低估泛化
```
**Gate**: 每条样本三要素齐全 · 图像可解码 · val 非空

## 03 Env Setup 环境
```bash
conda create -n aipc-ft python=3.11 -y && conda activate aipc-ft
pip install torch torchvision --index-url https://download.pytorch.org/whl/xpu
pip install diffusers transformers accelerate peft bitsandbytes datasets
```
**Gate**: `torch.xpu.is_available()` True · `import diffusers,peft` 成功
**坑**: bitsandbytes 的 NF4 在 XPU 上需对应版本；不匹配就退到 `bf16`（见 06 的量化降级原则）

## 04 Config 配置生成
```yaml
# Agent 按显存/算力自动填, 不拍脑袋
model: Qwen/Qwen-Image-Edit
quantization: {load_in_4bit: true, bnb_4bit_quant_type: nf4, bnb_4bit_compute_dtype: bf16}
lora: {r: 16, alpha: 32, dropout: 0.05, target_modules: [q_proj,k_proj,v_proj,out_proj,to_q,to_k,to_v,to_out]}
train: {lr: 1e-4, batch: 1, grad_accum: 8, steps: 800, warmup: 50, save_every: 100}
eval:  {every: 100, holdout_frac: 0.15, early_stop_patience: 3}
```
**Gate**: 五项齐全（数据/留出/量化/LoRA/早停）· batch 由显存二分搜索实测得出

## 05 Adaptation 适配移植
```python
# ① 基座 4bit 加载 (DIT + MLLM 分别量化)
from transformers import BitsAndBytesConfig
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16)
model = QwenImageEdit.from_pretrained(MODEL, quantization_config=bnb)
# ② 挂 LoRA (★ 顺序: 先 prepare 再 to(device))
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
model = prepare_model_for_kbit_training(model)
model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                         target_modules=[...], task_type="CAUSAL_LM"))
model = model.to("xpu")          # ← 必须在 get_peft_model 之后
```
**Gate**: 可训参数占比 1-3% · forward+backward 各跑通一次
**端侧优化**: SDPA attention · channels_last · TF32（XPU 对应开关）

## 06 Quantize 量化
```
方案选择（按机器能力降级）:
  NF4 (4bit 归一化)  ← 首选, 显存 ↓~4x (QLoRA 论文格式, 比普通 int4 保真)
  bf16               ← NF4 后端不支持时
  int8 动态           ← CPU/端侧推理
★ 量化后必须验: 与 fp32 输出逐指标对比, |Δ|>8% 则**拒绝该量化方案**并降级
```
**Gate**: 体积比 ≥2x 且精度退化 ≤8%

## 07 Training 训练
```bash
python train_qlora.py --config cfg.yaml --out out/
# Agent 负责: 缓存构建 → 启动 → 监控留出 → 早停 → 存留出最优
```
**四层优化**（实测收益见 SKILL.md）:
```
算子层: SDPA + TF32 + channels_last
流程层: bf16 AMP + 梯度累积(显存不够时) + 数据预取
量化层: NF4
端侧  : 冻结基座, 只训 LoRA
```
**Gate**: 留出指标优于**平凡基线**（如"输出原图/恒等编辑"）· 早停生效 · best 非 step1

## 08 Validation 验证
```python
# 三方对比出图（展板 Step08 的核心交付）
for sample in val_set:
    base_out   = base_model(sample)          # 基础模型输出
    lora_out   = peft_model(sample)          # 微调后输出
    save_side_by_side(sample.orig, base_out, lora_out)   # 原图 | 基座 | LoRA
```
**Gate**: 出对比图 + 指标 · **有提升非仅不回退** · 无提升如实报

## 与传统流程的差别（为什么要 Skill 化）
```
传统: 工程师手装环境 → 手处理数据 → 手写配置 → 手调量化 → 手跑训练 → 手写评估
Skill: 用户只给数据集; Agent 自主跑 8 阶段, 每阶段过 gate 才继续, 全程落盘可复现
→ 降门槛 + 可复用 + 判据明确 + 隐私友好(不出网)
```
