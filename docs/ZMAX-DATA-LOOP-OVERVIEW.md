# Z-MAX 数据闭环全景 · 开发流程/场景/功能定义 (v4.0)

> 2026-08-02 · 以真实跑通的数据闭环为基础全面更新
> 团队统一基准: 静静(训练/GUI) · 小芳(采集/部署/Orin) · web(网站/前端/ECS)
> 数据流、逻辑、口径全链路一致

---

## 0. 数据闭环总览 (已真实跑通 2026-08-02)

```
┌────────────────────────────────────────────────────────────────────┐
│                    Z-MAX 边学边练数据闭环 (全自动)                    │
│                                                                    │
│  ① 采集        ② 上传         ③ 训练          ④ 模型传递            │
│  Orin 真机  →  ECS 中转  →  静静 4060  →  静态 URL 覆盖             │
│  (20s MCAP   (relay 弹栈   (ACT 2000步   (/models/                 │
│   +打标)       +快照直播)    loss~1.5)    act_cartesian)            │
│    │              │              │              │                 │
│    └──────────────┴──────┬───────┴──────────────┘                 │
│                          ▼                                        │
│  ⑥ 迭代循环 ←──── ⑤ 部署 Orin + 真实推理                          │
│  (新数据回灌)     (小芳监听器自动部署, infer_count>0)                │
└────────────────────────────────────────────────────────────────────┘
```

### 关键数字 (2026-08-02 实测)
| 指标 | 值 |
|---|---|
| 采集 | 20s/轮 · 96-112帧 · 6D关节+图像(320x240) |
| 训练 | 2000步 ~2.5min · loss 1.50-1.55 · 4060 RTX |
| 推理 | v2 479ms (state6D→action6D) |
| 模型传递 | 静态URL 84MB · HTTP 200 · 永不竞争 |
| 闭环周期 | ~5min/轮 (采集→训练→部署) |

---

## 1. 角色与职责 (三体一致)

| 角色 | 平台 | 职责 |
|:---:|:---:|------|
| **静静 (xspace)** | WSL2 RTX4060 | ACT训练 · 数据闭环守护(auto_loop) · Simulink控制台 · 模型静态URL |
| **小芳** | Mac M1 + Orin | 采集(打标上传) · Orin部署 · 推理验证 · 监听器自动部署 |
| **web** | RTX4090 + ECS | 网站(cicd.html) · 云端训练 · 前端可视化 · 实时画面 |

### 通信链路 (数据流)
```
Orin (192.168.23.66, 仅小芳可达)
  → 小芳 Mac (采集+部署)
  → ECS 中转 (datadrive.world/api/relay, 公网)
  → 静静 4060 (训练) / web (前端)
```

---

## 2. 数据流定义 (全环节一致)

### 2.1 采集数据格式 (小芳→ECS)
```json
{"meta": {"source": "orin", "frames": 97, "n_joint": 6, "n_action": 6,
          "labels": {"等待测试结果": 97}, "time": 1785681876},
 "frames": [{"observation.state": [6D关节角],
             "action": [6D关节增量],
             "label": "暂时松开|移动|等待测试结果|IDLE",
             "timestamp": 相对秒,
             "camera_b64": "320x240 JPEG"}]}
```
- **IDLE 帧不参与训练** (action==state, 无动作意义)
- 有效标签: 暂时松开/移动到治具插槽/等待测试结果/扫码/取料 等

### 2.2 训练数据 (静静侧)
- 数据集: `data/orin_6d` (LeRobot 格式, 6D state/action + 视频)
- 模型: ACT (state6→action6) · 或笛卡尔 (state3位姿→action4速度)
- 静态 URL: `https://datadrive.world/models/act_cartesian.safetensors`

### 2.3 推理接口 (Orin 侧)
- 输入: 6D 关节角 (或 3D TCP 位姿)
- 输出: (7,6) 动作块 → 6D 关节增量 → 珞石 SR5 执行
- 上报: `orin/status` infer_count/last_infer_ms

---

## 3. 开发流程 (产品迭代 v4.0)

### 3.1 三阶段渐进式训练 (老倪策略)
```
Stage1: MetaWorld 仿真训练 (backbone冻结, 快速验证, 300步)
Stage2: Sim-to-Real 零样本测试 (stage1模型→Orin数据, 量化Reality Gap)
Stage3: Orin 真机微调 (低lr 1e-5, backbone 1e-6, ensemble必开)
```

### 3.2 数据闭环迭代 (边学边练)
```
每轮: 采集(20s) → 上传 → 守护自动训练 → 覆盖静态URL → 自动部署 → 推理 → 采集
```

### 3.3 版本体系
| 版本 | 内容 | 状态 |
|---|---|---|
| v1.1.0 | 闭环+WS+Simulink CI | ✅ Released |
| v1.2.0 | 直播/归档/联调/自动迭代 | ✅ Released |
| v1.3.0 | 数据闭环全自动(守护+静态URL) | 🔄 当前 |
| v2.0 | 全自动无人值守闭环 | 目标 |

---

## 4. 场景定义 (产线 + 闭环)

### 4.1 光模块产线 12 工位 (产品场景)
详见 `docs/光模块产线-全流程12工位场景定义.md`:
工位1-4 光器件封装 → 工位5-6 OE光引擎(核心) → 工位7-9 电学集成 → 工位10-12 测试包装

### 4.2 机器人作业场景 (当前闭环验证)
| 标签 | 动作 | 训练价值 |
|---|---|---|
| 等待测试结果 | 保持位姿 | ✅ 高 |
| 暂时松开 | 夹爪释放 | ✅ 高 |
| 移动到治具插槽 | 末端平移 | ✅ 高 |
| 取料/扫码/插入 | 精细操作 | ✅ 高 |
| IDLE | 空闲 | ❌ 跳过 |

### 4.3 控制器 (珞石 SR5, 6关节)
- 关节角接口: `/sim_joint_trajectory` (JointTrajectory)
- 笛卡尔: `/robot/tcp_pose` (x/y/z+四元数) + 内部 IK
- **模型须匹配**: 6D关节模型 (state6/action6) 或 3D笛卡尔 (state3/action4)

---

## 5. 功能定义 (控制台/工具)

### 5.1 Simulink 数据闭环控制台 (studio.py)
| 功能 | 说明 | 数据源 |
|---|---|---|
| 6环节流水线 | 采集→训练→验证→集成→部署→推理 | 真实命令 |
| 三阶段卡片 | S1仿真/S2零样本/S3微调 | cicd_pipeline.py |
| 闭环状态栏 | 数据量/模型/URL/Orin/推理 | relay API (10s轮询) |
| Scope示波器 | 新老模型动作曲线对比 | CICD_COMPARE_*.json |
| 性能对比 | MSE/成功率/延迟 | act_compare.py |

### 5.2 闭环守护 auto_loop.py
- 60s 轮询 ECS 队列 → 新数据自动训练 → 自动推模型
- 训练锁防并发 · IDLE过滤 · episode连续编号

### 5.3 模型传递 (静态URL, 铁律)
**不用弹栈队列传模型** (会竞争丢失)。静态URL:
```bash
scp model.safetensors root@ECS:/www/wwwroot/datadrive.world/models/
# 权限必须 644 (nginx 可读)
```

---

## 6. 数据一致性规范 (全环节)

| 环节 | 规范 |
|---|---|
| 维度 | Orin 6关节: state6/action6 · 笛卡尔: state3/action4 |
| 标签 | 统一中文动作标签 (等待测试结果等) |
| 时间戳 | 包meta.time + 帧相对timestamp = 绝对时间 |
| 图像 | 320x240 JPEG (q75) · IDLE 帧跳过训练 |
| 模型名 | act_cartesian.safetensors (静态URL固定名, 覆盖更新) |
| 推理口径 | infer_count 累计 · last_infer_ms 最近延迟 |

---

## 7. 质量与验收

### 7.1 训练质量
- loss 目标: < 1.5 (真机数据, 2000步)
- 基线对比: 同数据双训练 (MSE 提升≥5% 达标)
- 坏数据诚实标注: 黑图/合成数据不报假提升

### 7.2 闭环验收
- [ ] 采集→上传→训练→部署→推理 全自动 (无人工)
- [ ] infer_count > 0 (真推理, 非 mock)
- [ ] 模型静态URL 200 + 84MB 完整
- [ ] 训练 loss < 1.5 + 对比基线提升

---

## 8. 文档拓扑 (团队同步基准)
- **本文件** = 数据闭环全景 (唯一基准)
- `docs/DATA-FLYWHEEL.md` = 旧版(v2) → 已被本文件替代
- `docs/ARCHITECTURE-OVERVIEW.md` = 旧版 → 引用本文件
- 网站 `cicd.html` / `act-pipeline.json` = web 侧实现 → 对齐本文件
- Simulink 控制台 = 静静 GUI 实现 → 对齐本文件

> 任何环节改动必须更新本文件, 保证三体逻辑/数据一致。
