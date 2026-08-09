# 🎛 原子技能 → 条件编码 (ControlNet 核心思想) — 2026-08-09 老倪

## 核心思想 (ControlNet)
原子技能 = **控制条件** (像 ControlNet 的 Canny/深度图 — 结构化控制信号)
条件编码 = **多模态条件向量** (图像/力/位姿/触觉/关节/点云/温度/信号/条码/CAD 各模态 one-hot + 语义)
注入结构条件节点 (coord_overlay) → `latent += proj(cond)×gate`
→ **技能条件"控制"VLA 动作生成** (图像是背景, 条件是主线)

## 文件
| 文件 | 说明 |
|:---|:---|
| `flows/atomic_skills_raw.json` | 242 条原子技能原始数据 (dds-atomic-api.php) |
| `flows/gen_atomic_conditions.py` | 生成器: 技能 → 条件编码 (模态提取 + 动作分类) |
| `flows/atomic_skills_conditions.json` | **输出: 242 条条件编码** (D001-D242) |

## 条件编码格式
```json
{
  "skill_id": "NPO002", "skill_name": "NPO精密料盘穴位与满空映射",
  "category": "NPO近封装光学", "cond_id": "D001",
  "condition": "...条件", "topic": "/dds/cond/...",
  "modalities": ["image", "state_2d"],      # 自动提取
  "encoding": {"image":1,"force":0,"pose":0,"tactile":0,
               "joint":0,"pointcloud":0,"temp":0,"signal":0,
               "code":0,"cad":0},            # ControlNet 多模态通道
  "action": "pick",                          # 动作类型
  "gate": 0.5, "source": "atomic_skill"
}
```

## 模态编码规则 (自动)
| 通道 | 关键词 |
|:---|:---|
| image | 图/图像/视觉/相机/显微 |
| force | 力/力矩/力控/六维力 |
| pose | 位姿/坐标/手眼/6D/朝向 |
| tactile | 触觉/触感/压觉 |
| joint | 关节/机械臂/轴 |
| pointcloud | 点云/3D/三维/扫描 |
| temp | 温度/温控/测温 |
| signal | 信号/IO/触发/到位/仓/状态 |
| code | ID/条码/二维码/扫码/编码 |
| cad | CAD/图纸/模型比对 |

## 使用 (Simulink)
双击画布上的「🧩 结构条件」节点 → 弹出原子技能库选择器:
① 选技能大类 → ② 选原子技能 → 显示 topic/模态/编码位 → ✅ 注入
节点 params 写入: cond_ref / skill / topic / action / modalities / encoding / gate
