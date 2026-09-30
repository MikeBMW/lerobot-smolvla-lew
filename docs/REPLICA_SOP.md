# 📦 Z-MAX 系统复制 SOP（工作端 静静 → 备份端 小芳）

> 老倪 2026-09-23：把全套状态空间系统复制到 Mac；**资源要先评估，性能不减，不能崩溃**
> 角色：**静静 = 工作端**（4060/CUDA，做训练与产线对接）· **小芳 = 孪生备份端**（Mac，做备份/联合开发）

---

## 一、分工与红线

| | 工作端（静静/4060） | 备份端（小芳/Mac） |
|---|---|---|
| 定位 | 主力：训练、真机、产线 | 备份 + **联合开发**（改代码、跑推理、验证） |
| 算力 | CUDA 8GB | 无 CUDA（MPS/CPU），内存有限 |
| 训练 | ✅ 全量训练 | ⚠️ 只做 **LoRA 微调**，大训练回工作端 |
| 数据 | 127G 全量 | **只带小样本切片**（≤500MB），大数据按需拉 |

**三条红线**
1. **内存红线**：任何进程峰值 ≤ 可用内存 × 0.70（留 30% 给系统）—— 这是"不崩"的量化判据
2. **磁盘红线**：留 ≥ 20% 空闲；训练产物只留最后 1 个 ckpt
3. **venv 不跨平台**：Mac 必须**重建**（arm64 wheel 与 x86 不通用），绝不复制 venv

---

## 二、复制顺序（先评估 → 再收包 → 再建环境 → 再验证）

### ① 资源预检（**收包之前**，纯标准库可跑）
```bash
# 把 tools/resource_preflight.py 单独传过去先跑 (只有 6KB, 不依赖任何库)
python3 resource_preflight.py
```
**看结论行**：
- `✅ 可跑标准档` → 收 T1+T2，能做推理+LoRA 微调
- `⚠️ 只能跑保守档` → **只收 T1**，端侧只推理，训练回工作端
- `❌ 内存不足` → 只收 T1 代码做**只读分析**，不跑模型

### ② 收包（T1 核心 ≈ 850MB）
```
zmax_replica_T1.tar.zst     ← 代码(tools/src/flows/config) + 4 个关键权重 + manifest + 本 SOP
zmax_replica_T1.sha256      ← 传输完整性校验
```
```bash
shasum -a 256 -c zmax_replica_T1.sha256      # 先验包未损坏
mkdir -p ~/zmax && tar -C ~/zmax --strip-components=1 -xf zmax_replica_T1.tar.zst   # zstd 需 brew install zstd
```
**T2/T3 先不收**：T2（12.2G）若非必需可精简为 `reports/*.json + data/*.json ≈ 200MB`；T3（442G）永不随包。

### ③ 建环境（arm64 原生）
```bash
bash ~/zmax/lerobot-smolvla-lew/tools/mac_bootstrap.sh ~/zmax/lerobot-smolvla-lew
# 产出 ~/zmax/lerobot-smolvla-lew/.venv-arm  (torch+MPS / transformers / h5py / cv2)
```

### ④ 收包校验 + 冒烟（证明"性能不减、不崩"）
```bash
.venv-arm/bin/python tools/replica_verify.py --root ~/zmax/lerobot-smolvla-lew
```
输出三块：① 完整性（sha256）② 冒烟（统一主干 forward，报 dev=mps/cpu + 耗时）③ 性能锚点对比
**通过判据**：完整性 0 缺失 0 不符 + 冒烟成功（能加载能推理）→ 即"性能不减"

---

## 三、备份端能直接做什么（收到就能跑）

```bash
# 1) 跑整条 pipeline 闭环（画布状态落盘）
.venv-arm/bin/python tools/pipeline_closure_run.py

# 2) 几何不变性复算（对比工作端锚点）
.venv-arm/bin/python tools/geom_invariance_check.py --ckpt ~/zmax/lerobot-smolvla-lew/checkpoints/backbone_cont/unified.pt --n 24

# 3) 端侧微调（LoRA，小样本；8G 内存机建议 --steps 300 --batch 8）
.venv-arm/bin/python tools/edge_finetune.py --data <h5> --steps 300 --batch 8 --lora-r 8

# 4) 标定状态与 SOP
python3 tools/calib_studio.py status && python3 tools/calib_studio.py guide
```

## 四、双系统联合开发约定

| 事项 | 约定 |
|---|---|
| **代码同步** | 以 git 为唯一真相（`git pull` / 分支 PR）；**不手工拷 .py** |
| **权重/数据** | 走网盘/数据服务器，**不进 git**（大文件红线） |
| **改动验证** | 备份端改完先跑 `replica_verify.py` + `geom_invariance_check.py`，指标不退才提 PR |
| **训练分工** | 备份端只跑 LoRA 小步；全量训练回工作端（CUDA） |
| **状态对齐** | 双方都读 `docs/PIPELINE_STATE.json` 看闭环状态；拓扑以 `flows/*.json` 为准 |
| **冲突** | 同一文件两边都改 → 用 tools/merge（若可用）或小 PR 串行合 |

## 五、故障与回退

| 症状 | 处置 |
|---|---|
| 冒烟时内存暴涨 | 降到 `--batch 1`；仍不行则只做代码分析 |
| MPS 报不支持算子 | 加环境变量强制 CPU：`PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` 或 `--dev cpu` |
| 权重 sha 不符 | **不要用**，重新传（可能是没传完） |
| 装了 mujoco 失败 | 可忽略（备份端不做真机），跨机控制走工作端 |
| 需要全量数据 | 别拷 127G：用 `tools/hf-dataset-subset` 思路只取切片 |

---
**核心理念**：模块化（每层可插拔）+ 管道化（spec 驱动）+ 可复制（清单+校验+冒烟）+ 可运维（状态落盘可观测）。
复制的是**能力**（代码+权重+拓扑+流程），不是**环境**（venv 必重建）。
