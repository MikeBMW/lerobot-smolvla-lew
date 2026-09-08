# GUI 训练入口地图 + 训练状态诊断 (2026-08-14 实测)

## 训练入口在哪 — 别找错页面

| 想训什么 | 入口 |
|---|---|
| SmolVLA / VLA-Touch / AWE / ACT / MLP蒸馏 | 首页 → 🏋️ 模型引擎 (TrainingModule)。🎛训练开关 S-01~S-07 勾对应模型 (SmolVLA=S-02, config_smolvla_peg_long2.yaml) |
| left_right 双脑 (左脑MLP+右脑WM) | Simulink 模式 → 画布内 🚀 训练 节点 |
| ACT (画布模板) | Simulink 模式 Model Zoo 模板的 🚀 ACT 训练 节点 |

### 前馈PD顶层画布 (ff_pd_top.json) 没有训练入口!
它是总系统视图: 📡参考输入 → 🔬Z700子系统 → 🖥输出Scope → ⚙️前馈PD分析。
底部一排 (感知链/双脑/状态机/动作) 是**只读展示** (z700_internal 节点), 双击只提示。
**进训练路径**: 双击 🔬 Z700 子系统 → 加载 dual_brain_peg_yolo.json →
「🎨 训练」行 → 🚀 训练 节点 (params: policy="left_right", steps=3000,
source=src/lerobot/policies/left_right) → 双击调 on_train(policy=left_right)。

Z700 画布 (dual_brain_peg_yolo.json) 全功能行:
- 🎨 训练: 🚀训练 + 🔀训练/推理开关 + 📷推理(rollout, 自动加载最新模型)
- 🎨 评估: 📊模型评估(状态空间) + 🧮谱归一化 + 🧮GRU门控 + 🧮力幅值限幅
- 🎨 交付: 📄方案+评估PDF + 🌐方案介绍
- 🎛 顶层控制: ⚙️前馈PD控制器

## 训练状态诊断 — 看 outputs/train 别信配置名

🐛 **陷阱 (2026-08-14 实测踩坑)**: 训练容器命令行显示
`--config_path /app/config_act_runtime.yaml`, **不代表在训 ACT**!
config_act_runtime.yaml 是运行时生成的临时配置 (名字是模板命名),
实际策略看 `outputs/train/` 最新目录前缀 (left_right_20260814_173341 = left_right)。
判断实际训练策略 = 列 outputs/train/ 最新目录名, 不是看容器 config 名。

### ✅ 训练完成判定 (全部满足 = 正常完成)
1. `outputs/train/<policy>_YYYYMMDD_HHMMSS/checkpoints/` 有完整数字目录 (001000/002000/003000) + last
2. 末位 checkpoint 的 `pretrained_model/` 完整: config.json + model.pt +
   preprocessor/postprocessor safetensors + train_config.json
3. `training_state/training_step.json` 的 step == 目标步数
4. 容器已消失 (docker run --rm 退出即删) + 运行时 config_act_runtime.yaml 被清理

### ⏱ 速度认知 (别误判"没跑完")
left_right (0.71M 参数) + metaworld_peg (24集) 3000步 ≈ **3 分钟**跑完
(实测 17:33 建目录 → 17:36 checkpoint 写全)。时间线: 容器起 → ~2min 加载 →
输出目录建 → ~3min 训练 → 容器 --rm 清理。小模型秒完, 别等。

### 训练触发后的完整痕迹链 (诊断用)
容器启动 → outputs/train/<新目录> 出现 → checkpoints 数字目录递增 →
pretrained_model 写全 → 容器消失 + 运行时 config 删除 → (训练完自动视频+飞书+PDF)
