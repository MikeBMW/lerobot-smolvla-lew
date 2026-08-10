# 🧠 Z-MAX 左右脑双脑策略 (LeftRightPolicy) 技术方案

> 版本: v2.0.0 · 2026-08-10 · 作者: Z-MAX 控制台
> 实现: `src/lerobot/policies/left_right/` (lerobot 标准 PreTrainedPolicy)

---

## 一、一句话概述

**左右脑双脑策略 = 左脑动作生成器 + 右脑世界模型 + 状态机阶段调制**。
左脑负责"想动作"，右脑负责"判断时机"，状态机负责"分阶段编排"，三者合成为完整插拔闭环。

仿真成绩: **抓起 8/8 · 插入 7/8** (官方专家 7/8 · 视觉 BC 全部 0/8)
参数量: **~635K** (左脑 547K + 右脑 87K), 比 SmolVLA 小数百倍, GPU 推理 0.19ms

---

## 二、架构总览

```
                    ┌─────────────────────────────────────────┐
  39D obs ─────────▶│ ◉ LeftRightPolicy (PreTrainedPolicy)     │
                    │                                         │
                    │   ┌──────────────┐    ┌──────────────┐  │
                    │   │ 左脑          │    │ 右脑          │  │
  39D obs ─────────▶│   │ LeftBrainMLP  │    │ RightBrainWM  │◀─ obs + action
                    │   │ 39D → 4D 动作 │    │ 世界模型       │  │
                    │   └──────┬───────┘    └──────┬───────┘  │
                    │          │ 4D 动作(草稿)      │ contact 概率 │
                    │          ▼                    ▼          │
                    │   ┌─────────────────────────────────┐    │
                    │   │ 状态机 (8 状态)                  │    │
                    │   │ 接近→对位→下降→抓取→抬起→转移→插入→完成│    │
                    │   └──────────────┬──────────────────┘    │
                    │                  │ 阶段调制               │
                    │                  ▼                        │
                    │        4D 最终动作 (输出)                 │
                    └─────────────────────────────────────────┘
```

---

## 三、左脑: LeftBrainMLP — 动作生成器 (547K)

### 3.1 原理

**39D 状态 → 4D 连续动作** 的 MLP 回归器 (MSE 训练):

```
输入: 39D obs (归一化后)
  3 层 MLP: Linear(39, 512) → ReLU → Linear(512, 512) → ReLU → Linear(512, 4)
输出: 4D = [vx, vy, vz 末端速度, 夹爪开度]  (归一化后反归一化)
```

### 3.2 训练技巧: MLP 偏置接近

纯 MLP 学 peg-insertion 长程任务极易失败 (视觉 BC 全部 0/8)。
**关键技巧**: 训练数据用"解析规则偏置"的动作轨迹, 让 MLP 学到的解空间偏向规则解:

```
动作 = 左脑输出 × 0.3 + (peg - hand)方向 × 2.0   (接近阶段)
```

MLP 实际学到的是"在规则偏置基础上的修正量", 而非从零学起。
效果: 左脑+偏置接近 5/8, 纯解析规则 0/8, 纯 MLP 接近 0/8。

### 3.3 关键点

| 项 | 值 |
|---|---|
| 输入 | 39D obs (状态归一化 x_mean/x_std) |
| 输出 | 4D 动作 (vx vy vz 夹爪) |
| 隐藏层 | 512×2, ReLU |
| 参数 | 547,844 |
| 损失 | MSE (动作回归) |
| 训练 | 800 epoch · AdamW · lr 1e-4 · seed 42 |

---

## 四、右脑: RightBrainWM — 世界模型 (87K)

### 4.1 原理

**世界模型 (World Model)**: 输入"当前状态 + 要做的动作", 预测"做完后的下一个状态 + 接触概率"。

```
输入: [39D obs ∥ 4D action] = 43D
  enc: Linear(43, 256) → ReLU → Linear(256, 256) → ReLU
  pred_next:  Linear(256, 39)   → 预测 next obs (世界模型主任务)
  contact_head: Linear(256, 1) → sigmoid → contact 概率 (抓取时机)
```

### 4.2 两个输出头的用途

| 输出 | 训练监督 | 推理用途 |
|---|---|---|
| next obs (39D) | MSE: 预测 obs_{t+1} vs 真实 | 学习环境动力学 (物理规律) — 中间表征 |
| contact 概率 (1D) | BCE: 该抓时刻标签 | **抓取时机判断**: contact > 0.5 且 距离 < 0.06 → 触发抓取 |

### 4.3 为什么 contact 给状态机而不是左脑?

左脑网络输入恒为 39D obs, **不接收 contact**。
contact 只作为状态机转移条件:

```
if d_hp < grasp_d_hp (0.06) and contact > 0.5:  状态 → 抓取
```

- 左脑: 一直看 obs 出动作 (输入不变)
- 右脑: 判断"该抓了吗" (输出 contact)
- 状态机: 听到 contact 切阶段, 阶段决定**怎么调制左脑的动作**

**类比**: 左脑是司机 (看路打方向), 右脑是副驾喊"碰到了!", 导航 (状态机) 切到"抓取"模式,
司机的手被引导改成"抓紧稳住"。contact 不改变司机看什么 (输入不变), 只改变操作方式 (输出调制)。

---

## 五、状态机: 8 阶段编排与动作调制

### 5.1 8 状态定义

```
ST_APPROACH=0 接近   → ST_ALIGN=1 对位 → ST_DESCEND=2 下降 → ST_GRASP=3 抓取
→ ST_LIFT=4 抬起 → ST_TRANSFER=5 转移 → ST_INSERT=6 插入 → ST_DONE=7 完成
```

(2026-08-10 v2.0: 新增 对位/下降 两阶段 — 插入 4/8 vs 7/8 根因是缺对位/下降)

### 5.2 转移条件 (状态机推进)

| 当前状态 | 转移条件 |
|---|---|
| 接近 | d_hp < 0.06 且 contact > 0.5 → 抓取 |
| 抓取 | peg 抬升 > 0.02m → 抬起 |
| 抬起 | peg z > 初始 + 0.08m → 转移 |
| 转移 | peg xy 与 hole xy 偏差 < 容差 5cm → 插入 |
| 插入 | d_ph < 0.05 → 完成 |

### 5.3 阶段调制 (核心: 对左脑动作的改写)

`_act_state_machine`: 拷贝左脑动作 → 按阶段改写 → 返回最终动作

| 阶段 | 动作调制 (act[:3]=xyz速度, act[3]=夹爪) |
|---|---|
| 接近 | `act = act×0.3 + clip(朝peg偏置×2)` · 夹爪 -1.0 (张开) |
| 对位 | xy 对齐 hole (速度自适应) · 夹爪 0.6 |
| 下降 | 朝 hole 下降 · 夹爪 0.6 |
| 抓取 | `act = act×0.1` (稳住) · 夹爪 0.6 + 位置锁定 |
| 抬起 | `act = [0,0,0.8]` 固定抬升 · 夹爪 0.6 |
| 转移 | 速度自适应: 距离>0.2m 用 0.6 / >0.05m 用 0.35 / 否则 0.15 (防过冲卡顿) · 夹爪 0.6 |
| 插入 | `act = [0,0, clip((孔z-销z)×2, ±0.6)]` 只下降 · 夹爪 0.6 |
| 完成 | 全零 + 夹爪 0.6 |

调制后统一归一化 (|act|max > 1.0 时缩放)。

---

## 六、39D 观测结构 (metaworld peg-insertion)

```
39D = 当前帧(18) + 上一帧(18) + 目标(3)  [帧堆叠]

[0:3]    hand_pos      末端位置 xyz        单位: 米
[3]      gripper       夹爪开度             0=闭合 1=张开
[4:7]    peg_pos       销钉位置 xyz         米
[7:11]   peg_quat      销钉四元数 xyzw      单位四元数
[11:18]  pad           填充槽 (固定0)
[18:21]  prev_hand_pos 上一帧末端位置        米
[21]     prev_gripper  上一帧夹爪开度        0-1
[22:25]  prev_peg_pos  上一帧销钉位置        米
[25:29]  prev_peg_quat 上一帧销钉四元数     xyzw
[29:36]  prev_pad      填充槽 (固定0)
[36:39]  hole_pos      插孔目标位置 xyz      米 (goal)
```

45D = 39D + 6D 相对向量 (peg-hand, hole-peg); 49D 加触觉 4D; 58D 加 W2-CoT 9D。

---

## 七、训练管线

```
数据: metaworld peg-insertion 专家轨迹 (官方专家策略 rollout, 50 条)
   → data/metaworld_peg_long (12 集 3600 帧, 39D, splits 归一化)

左脑: obs → action  MSE 回归 (专家动作, 含偏置接近技巧)
右脑: obs+action → next obs (MSE) + contact (BCE, 权重 0.5)
状态机: 参数固定 (不学习), 规则编排

训练: 800 epoch · AdamW · lr 1e-4 · seed 42
  左脑损失 = MSE(action)
  右脑损失 = MSE(next obs) + 0.5 × BCE(contact)
  总损失 = 左脑 + 右脑
```

### 容器训练 (标准命令)

```bash
sudo docker run --rm --gpus all \
  -v /home/xspace/lerobot-smolvla-lew:/app -w /app \
  -e PYTHONPATH=/app/src --entrypoint python zmax-std:1.0 \
  -u -m lerobot.scripts.lerobot_train \
  --config_path /app/configs/policies/config_left_right.yaml
```

---

## 八、版本历史

| 版本 | 日期 | 内容 | 成绩 |
|---|---|---|---|
| v1.0 | 08-10 | 双脑+状态机初版 (6 状态) | 抓起 8/8 插入 7/8 |
| v1.1 | 08-10 | 转移速度自适应 (距离越近越慢) | 抓起方差略优, 插入持平 |
| v2.0 | 08-10 | 8 状态 (新增对位/下降), 画布/模块库/自动训练对齐, 39D 结构文档化 | 插入待复测 |

---

## 九、相关文件

| 文件 | 说明 |
|---|---|
| `src/lerobot/policies/left_right/modeling_left_right.py` | LeftRightPolicy 实现 (400 行) |
| `src/lerobot/policies/left_right/configuration_left_right.py` | LeftRightConfig 参数 |
| `src/lerobot/policies/left_right/processor_left_right.py` | 归一化处理器 |
| `configs/policies/config_left_right.yaml` | lerobot_train 配置 |
| `flows/dual_brain_peg.json` | Simulink 画布模型 (22 节点 21 连线) |
| `tools/gui/gen_dual_brain_flow.py` | 画布生成器 |
