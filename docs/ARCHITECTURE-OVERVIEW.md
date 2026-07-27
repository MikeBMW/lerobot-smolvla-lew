# Z-MAX 系统全景架构

> 2026-07-14 · 小芳(硬件系统)

## 工程关系

```
datadrive.world (主入口)
  ├── ComfyUI 标签页 → web 前端 (4090)
  ├── 数据任务设置 → 指向 robogen-deepseek
  ├── 训练框架 → 指向 lerobot-smolvla-lew
  ├── 部署状态 → 小芳汇报
  ├── DDS 数据空间 → 所有工程数据映射
  └── 进入其他仓库

genesis-world (物理引擎) → 生成合成数据
    ↓
robogen-deepseek (数据生成) → 用 DeepSeek V4 Pro 生成训练任务
    ↓
lerobot-smolvla-lew (训练框架) → 训练 ACT/SmolVLA/LeWorld
    ↓
DDS_Skill_ros2_ws (全局数据) → 所有数据节点
    ↓
小芳 (Mac 部署 + Orin 真机)
```

## 小芳部署计划

| 阶段 | 内容 | 依赖 |
|:---:|------|:---:|
| 1 | DDS_Skill 21节点 Mac 测试 | xspace 推送代码 |
| 2 | Genesis 数据 → Mac 仿真桥 | genesis-world 就绪 |
| 3 | DDS 节点 Orin 真机验证 | Orin 在线 |
| 4 | 训练模型 → Orin 部署 | web 训练完成 |
| 5 | 全线数据闭环验证 | 全部就绪 |

等待 xspace 推送 DDS_Skill 代码。硬件端已就绪。
