---
name: system-replication-twin
description: Use when 把整套系统复制到另一台机器/备份端 (分级清单+资源预检+校验冒烟)。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [replication, migration, twin-system, resource-preflight, backup-host]
    related_skills: [edge-finetune-automation, disk-redline-guard]
---

# 系统复制到孪生备份端（可复制性工程）

## When to Use
- 把整套系统（代码+数据+权重+训练/推理/运行程序）复制到**另一台机器**（Mac/另一台服务器/边缘盒）
- 目标机**资源有限**，要求"**性能不减、不能崩溃**"
- 双机协作：一台工作端（主力算力）+ 一台备份端（备份 + 联合开发）
- 要证明"复制成功"而不是"拷过去了"

## 核心原则
```
① **先评估再收包**: 备份端先跑资源预检(零依赖), 再决定收多少 —— 不是先拷再说
② **复制能力不复制环境**: venv 绝不跨平台复制(arm64/x86 wheel 不通用) → 必重建
③ **分级交付**: T1 核心(能跑) / T2 重要 / T3 大数据(按需拉, 永不随包) / X 排除
④ **可校验**: 每项带 sha256 → 收端能证明"没传坏、没传丢"
⑤ **量化判据**: "不崩"= 内存峰值 ≤ 可用×70%; "性能不减"= 冒烟通过 + 指标锚点对比
```

## 五步流程

### ① 分级清单（工作端）
```bash
python tools/replicate_manifest.py --hash 1 --out replica_manifest.json
```
典型分级（实测某具身项目）:
| 级 | 内容 | 体积 |
|---|---|---|
| T1 核心 | 代码(tools/src/flows/config) + 关键权重 + 记忆/状态 | ~850MB |
| T2 重要 | 报告 / 数据索引 / 文档 | ~12GB（可精简到 200MB）|
| T3 可选 | 全量数据集 | 442GB（**永不随包**）|
| X 排除 | venv / .git / `__pycache__` / 大 h5·npz | — |

### ② 资源预检（**备份端，收包之前**）
```bash
python3 tools/resource_preflight.py     # 纯标准库, 6KB 单文件即可先传过去
```
输出：CPU/内存/磁盘/加速器(CUDA\|MPS\|CPU)/Python/依赖 → **三档建议 + 崩溃红线校验**
```
保守(仅推理 batch32) / 标准(推理+LoRA batch64/24) / 激进(batch128)
判据: 每档峰值 ≤ 可用内存×0.70 → ✅可跑 / ❌超红线
结论三种: 可跑标准档 / 只能保守档(训练回工作端) / 内存不足(只做只读分析)
```

### ③ 建环境（备份端，arm64 示例）
```bash
bash tools/mac_bootstrap.sh <root>
# 内建: 预检 → venv → arm64 wheel(torch含MPS/transformers/h5py/cv2) → 依赖自检
```
**坑**: Mac 上 `torch` 走 PyPI 官方即含 MPS；别用 conda 与系统 python 混装。

### ④ 收包校验 + 冒烟（证明"性能不减、不崩"）
```bash
.venv-arm/bin/python tools/replica_verify.py --root <root>
```
三块输出：① 完整性(sha256 逐项) ② **冒烟**(真跑一次模型 forward, 报 device+耗时) ③ 性能锚点对比
**通过判据**: 0 缺失 + 0 校验不符 + 冒烟成功

### ⑤ 一键打包（工作端）
```bash
bash tools/make_replica_bundle.sh    # 清单→组包→压缩→sha256→自校验
```
产物：`<name>.tar.zst`（391MB 例）+ `.sha256`
**坑**: 自校验别用系统 `python3`（常无 numpy）→ 脚本里自动探测含 numpy 的解释器

## 交付与通道
| 包 | 体积 | 通道 |
|---|---|---|
| 代码包 | 4MB | 聊天工具直传 |
| 核心包(含权重) | 390MB~1GB | 网盘 / 数据服务器 / release |
| 大数据 | ≥10GB | **不传**，备份端按需拉切片(≤500MB) |

## 双机协作约定（工作端 / 备份端）
```
· 代码同步走 git（唯一真相），不手工拷 .py
· 权重/数据走网盘，不进 git
· 备份端改完先跑 verify + 指标复算, 指标不退才提 PR
· 全量训练回工作端(有 CUDA)；备份端只跑 LoRA 小步
· 状态对齐读同一份状态 JSON；拓扑以 flows/*.json 为准
```

## 常见坑
1. **venv 复制过去必炸**（平台 wheel 不兼容）→ 永远重建
2. **系统 python3 缺 numpy** → 任何"验证脚本"都要自动挑带依赖的解释器，否则误报失败
3. **manifest 路径基准不一致**（仓库相对 vs 包内布局）→ 校验脚本要**双前缀兜底**
4. **"拷过去了"≠"跑得起来"** → 必须有冒烟（真跑一次前向）
5. **大文件进 git** 会被拒/撑爆仓库 → 权重走网盘
