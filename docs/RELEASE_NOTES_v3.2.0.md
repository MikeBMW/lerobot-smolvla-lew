# 🚀 Z-MAX Console v3.2.0 Release Note — 状态空间八阶段状态机定版（双平台）

> 日期: 2026-08-26 · 仓库: MikeBMW/lerobot-smolvla-lew
> 标签: v3.2.0 · 发布页: https://github.com/MikeBMW/lerobot-smolvla-lew/releases/tag/v3.2.0

---

## 一、双平台产物

- 🪟 **Windows**: `Z-MAX_Console.exe`（x86-64 单文件免安装）
- 🍎 **macOS**: `Z-MAX_Console-macOS.zip`（Apple Silicon M1/M2/M3 arm64 原生）
- ✅ 已验证: exe PE32+ x86-64 / macOS Mach-O
- ✅ 双平台产物版本号已写入真实 3.2.0（不再 0.0.0）

---

## 二、核心发布: 状态空间八阶段状态机定版

### 3D 视图状态机图层

- 八阶段阶梯可视化 + 下一阶段预测（证据 / 阈值 / 进度 / 预计切换时间）

### 全局算法审计

- 新增 `tools/audit_state_machine.py` 全局审计
- 12 项逻辑验收全通

### 算法修正

- 连续确认防抖
- 夹持丢失 → 回退重抓
- 阶段限速按瓶颈调参

---

## 三、实测数据

| 指标 | 结果 |
|:---|:---|
| 单次节拍 | 8.09s → **7.44s**（快 2.9 倍） |
| 插入残距 | **3.7mm** |
| 安全层介入 | **零介入** |

---

## 四、版本线

- GUI Console 版本线: **v3.2.0**（3D 状态机图层系列 v3.0.3 → v3.2.0）
- 文档同步: 见 `docs/VERSION.md` / `docs/VERSION-SYNC.md`
