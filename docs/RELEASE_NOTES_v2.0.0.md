# 🎉 Z-MAX v2.0.0 Release Note — 左右脑双脑策略大版本

> 日期: 2026-08-10 · 仓库: MikeBMW/lerobot-smolvla-lew
> 标签: v2.0.0

---

## 一、核心发布: 🧠 LeftRightPolicy 左右脑双脑策略

**仿真成绩: 抓起 8/8 · 插入 7/8** (官方专家 7/8 · 视觉 BC 全部 0/8)
**参数量: ~635K** (左脑 547K + 右脑 87K) · GPU 推理 0.19ms

### 架构: 左脑动作 + 右脑世界模型 + 状态机调制

```
39D obs ──▶ 左脑 LeftBrainMLP (39D→4D 动作生成, MSE, 547K)
obs+动作 ──▶ 右脑 RightBrainWM (世界模型: 预测 next obs + contact 概率, 87K)
contact ──▶ 状态机 (8 状态: 接近→对位→下降→抓取→抬起→转移→插入→完成)
状态 ──▶ 动作调制 (_act_state_machine 按阶段改写左脑动作 → 最终动作)
```

### 关键技术点

1. **左脑 = 动作生成器**: 39D 状态 → 4D 连续动作 (vx vy vz + 夹爪), 3 层 MLP (512×2)
2. **右脑 = 世界模型**: obs+action → 预测 next obs (MSE 学动力学) + contact 概率 (BCE 学抓取时机)
   - contact 不直接进左脑网络, 只作状态机转移条件 (contact>0.5 & 距离<0.06 → 抓取)
3. **状态机 = 阶段调制**: 不喂信息给左脑, 而是对左脑输出做阶段化控制
   - 接近: 动作×0.3 + 规则偏置×2 (MLP偏置接近, 关键技巧: 训练数据带规则偏置)
   - 抓取: 动作×0.1 稳住 + 夹持 0.6 + 锁定
   - 抬起: 固定抬升 [0,0,0.8]
   - 转移: 速度自适应 (距离越近越慢: 0.6/0.35/0.15, 防过冲卡顿)
   - 插入: 只下降 clip((孔z-销z)×2, ±0.6)
4. **8 状态机** (v2.0 新增对位/下降): 修复"插入 4/8 vs 7/8 缺对位/下降"根因

---

## 二、Simulink 画布模型 (left_right 工程)

- `flows/dual_brain_peg.json`: 22 节点 21 连线 (39D obs → 左脑/右脑 → 接触判定 → 状态机 6→8 阶段 → 对比/交付)
- `flows/transfer_adaptive.json`: 18 节点 17 连线 (降波动三实验 + 根因: 仿真物理碰撞 → 需真机力控+视觉对齐)
- 模块库新增「🧠 双脑 (left_right)」按钮一键加载 left_right 工程
- **▶ 运行 = 自动训练**: left_right 画布点运行自动启动 lerobot_train (容器 zmax-std:1.0, 3000 步)
- 节点右键 → 查看/编辑节点逻辑 → 显示真实源码 (modeling_left_right.py 类定义, 只读参考 + VSCode 定位)

---

## 三、GUI / 控制台升级

- 版本号: Z-MAX v1.8.0 → **v2.0.0**
- 帮助文档下拉菜单新增: **🧠 左右脑策略 · LeftRightPolicy 技术方案**
- 39D obs 节点双击 → 完整数据结构说明 (11 段: 索引/名称/单位/解释)
- 右键菜单弹出修复 (QCursor.pos() 多屏不跑偏)
- 视频生成后自动打开 Windows 播放器 (C:\Users\Public\ZMAX_videos)
- PDF 报告 glob 修复 (五模型对比技术选型报告_*.pdf)
- 摄像头轮询线程化 (主线程零阻塞, 防卡死)

---

## 四、训练管线

```bash
# 容器训练 (▶ 运行 自动触发)
sudo docker run --rm --gpus all -v <repo>:/app -w /app \
  -e PYTHONPATH=/app/src --entrypoint python zmax-std:1.0 \
  -u -m lerobot.scripts.lerobot_train \
  --config_path /app/configs/policies/config_left_right.yaml
```

- 数据: data/metaworld_peg_long (39D, 12 集 3600 帧, 全量)
- 配置: configs/policies/config_left_right.yaml (3000 步 · bs 8 · lr 1e-4 · seed 42)
- 产物: outputs/train/left_right_<ts>/checkpoints/003000/pretrained_model/

---

## 五、实验结论 (降波动系列)

| 实验 | 效果 |
|---|---|
| 数据增强 (120eps) | ✅ 抓起下限 5→6 (唯一有效) |
| z 保持 | ❌ 更差 (2-4), 已回滚 |
| 转移速度自适应 | ≈ 抓起方差略优, 插入持平 |

**本质结论**: 转移卡顿 = 仿真物理碰撞 (peg 与孔边缘/台面几何干涉), 无接触反馈的控制参数调不动
→ 需真机力控夹爪 (实时接触力反馈) + 视觉对齐 (插入前 YOLO 检测孔位精调)

---

## 六、文件清单

| 文件 | 说明 |
|---|---|
| `src/lerobot/policies/left_right/modeling_left_right.py` | LeftRightPolicy (400 行, 8 状态机) |
| `src/lerobot/policies/left_right/configuration_left_right.py` | LeftRightConfig |
| `src/lerobot/policies/left_right/processor_left_right.py` | 归一化处理器 |
| `configs/policies/config_left_right.yaml` | 训练配置 (规范位置) |
| `flows/dual_brain_peg.json` | 画布模型 22 节点 |
| `flows/transfer_adaptive.json` | 实验 flow |
| `docs/left_right_policy.md` | 技术方案文档 |
| `tools/gui/gen_dual_brain_flow.py` | 画布生成器 |
| `tools/gui/gen_transfer_adaptive_flow.py` | 实验 flow 生成器 |
