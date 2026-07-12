# Z-MAX 具身智能开发文档

> **当前产品版本：v1.0.4** | **LeRobot 基线：v0.5.2** | **GitHub**: https://github.com/MikeBMW/lerobot-smolvla-lew

---

## 🔄 Git 操作快速参考

### 首次安装（从 GitHub 克隆项目）

```bash
# 1. 克隆仓库到本地
git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git

# 如果需要特定目录：
cd ~/  # 或任何你喜欢的位置
git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git

# 2. 进入项目目录
cd lerobot-smolvla-lew

# 3. 安装 Python 依赖
pip install -e .

# 4. 运行 GUI
bash tools/gui/run_studio.sh
```

### 日常拉取更新（从 GitHub 下载最新代码）

```bash
# 进入项目目录
cd ~/lerobot-smolvla-lew   # 或你的项目路径

# 拉取远程所有更新
git pull origin main

# 如果有本地未提交的修改，可以先 stash 再 pull：
git stash
git pull origin main
git stash pop
```

### 推送代码到 GitHub（上传本地修改）

```bash
# 1. 查看修改了哪些文件
git status

# 2. 添加所有修改到暂存区（或用 git add 指定文件）
git add -A

# 3. 提交修改（写一条有描述的 commit message）
git commit -m "feat: 你的修改描述"

# 4. 推送到 GitHub
git push origin main
```

### 查看历史和差异

```bash
# 查看最近 5 条提交历史
git log --oneline -5

# 查看当前工作区和暂存区的差异
git diff --cached

# 查看当前工作区（未暂存）的差异
git diff

# 查看某个文件的提交历史
git log --oneline tools/gui/studio.py
```

### 同步上游 LeRobot 官方更新（仅限维护者）

```bash
# 添加上游仓库（只需执行一次）
git remote add upstream https://github.com/lerobot/lerobot.git

# 拉取上游最新代码
git fetch upstream

# 合并上游 main 到本地 main
git merge upstream/main

# 解决可能的冲突后，推送到自己的 GitHub
git push origin main
```

### 常用 Git 命令速查表

| 命令 | 说明 | 示例 |
|------|------|------|
| `git clone <url>` | 从 GitHub 下载整个项目 | `git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git` |
| `git pull` | 下载+合并远程更新 | `git pull origin main` |
| `git status` | 查看当前修改状态 | `git status` |
| `git add -A` | 将所有修改添加到暂存区 | `git add -A` |
| `git commit -m "..."` | 提交修改 | `git commit -m "fix: 修复bug"` |
| `git push` | 推送提交到远程仓库 | `git push origin main` |
| `git log --oneline` | 查看提交历史（简洁模式） | `git log --oneline -10` |
| `git diff` | 查看文件差异 | `git diff tools/gui/studio.py` |
| `git stash` | 临时保存未提交修改 | `git stash` / `git stash pop` |
| `git branch` | 查看/创建/切换分支 | `git branch feature-new` |

---

## 📦 产品版本管理

> **当前版本：v1.0.4** (2026年7月10日)
> 详细版本历史和发布流程见 [VERSION.md](./VERSION.md)

### 快速入口

- [📖 开发宝典](./HELP-DEVELOPMENT-BIBLE.md) - 全维度参考手册（场景需求/设计/架构/训练/硬件/数据/GUI）
- [📦 产品版本管理](./VERSION.md) - 版本号规范与发布流程
- [🔄 上游同步指南](./Z-MAX-UPSTREAM-SYNC.md) - LeRobot上游同步工作流
- [📜 专利交底书](./patents/Z-MAX-专利交底书-实用新型-多模态VLA具身机器人精细操作控制系统.docx) - Z-MAX 实用新型专利（.docx）
- [🤖 AI分身状态](./memory/xspace.md) - 静静 & 小芳 协同工作台

---

## 📋 主文档（v1.0.4）

| 层级 | 文档 | 用途 | 读者 |
|------|------|------|------|
| **L1 战略层** | [L1-Z-MAX产品发布-v1.0.4.pptx](./L1-Z-MAX产品发布-v1.0.4.pptx) | 管理层汇报、投资人路演 | CEO / CTO / 投资人 |
| **L2 方案层** | [L2-Z-MAX解决方案-v1.0.4.md](./L2-Z-MAX解决方案-v1.0.4.md) | 客户解决方案详述、技术选型 | 客户CTO / 技术负责人 |
| **L3 实施层** | [L3-技术路线与开发指南-v1.0.4.md](./L3-技术路线与开发指南-v1.0.4.md) | 研发指导、代码实现 | 研发工程师 |
| **品牌注册** | [BRAND-品牌注册材料.pptx](./BRAND-品牌注册材料.pptx) | 商标注册、品牌审批 | 法务 / 品牌部 |

### 核心指标 (v1.0.4)

| 指标 | 目标值 |
|------|--------|
| 插拔精度 | ±0.02 mm |
| 成功率 | >99% |
| 节拍 | <25s |
| 关键工序良率 | 99%+ |
| 力控闭环频率 | >1kHz |
| 双臂协同 | 左取料 + 右插拔 |
| ROI回收期 | 14~22月 |

---

## 🤖 技术资料

### 策略实现
- [SmolVLA-LEW 策略设计](../src/lerobot/policies/smolvla_lew/README.md)
- [Z-MAX 策略体系](../src/lerobot/policies/) - sys1 / sys11 / sys12 / sys2 四阶段演进

### GUI 工具
- [XSpace Studio GUI](../tools/gui/studio.py) - 暗色主题，9大功能模块
- [数据集查看器](../tools/gui/dataset_viewer.py) - 浏览下载的数据集（图片/视频/state）
- [训练后端](../tools/gui/training_backend.py) - 调用 lerobot-train CLI 管理训练进程

### 脚本
- [数据集浏览器](../scripts/view_lerobot_data.py) - 独立运行，查看开源数据集元信息
- [上游同步脚本](../scripts/sync-upstream.sh) - 一键同步 LeRobot 官方更新

### 参考资料
- [竞品方案 PDF](./轮式双臂机器人光模块自主插拔项目-20260702.pdf) - 外部参考
- [历史版本归档](./archive/) - 已废弃的内部草稿

---

## 🛠️ 开发环境配置

### Python 环境要求
- Python 3.12（推荐，conda 环境名 `lerobot`）
- PyTorch 2.x + CUDA 支持
- PyQt5（GUI 使用）
- transformers >= 4.52（SmolVLM 模型）
- huggingface_hub, peft, datasets

### 快速启动
```bash
# 创建 conda 环境
conda create -n lerobot python=3.12 -y
conda activate lerobot

# 安装项目
cd ~/lerobot-smolvla-lew
pip install -e .

# 启动 GUI
bash tools/gui/run_studio.sh
```

---

## 📐 LeRobot 原生文档生成

以下是 LeRobot 官方文档的构建说明，如需本地生成文档可参考：

```bash
pip install -e . -r docs-requirements.txt
make doc BUILD=1
```
