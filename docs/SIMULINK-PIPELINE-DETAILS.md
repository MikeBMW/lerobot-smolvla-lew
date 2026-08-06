# Z-MAX 数据闭环 Simulink Pipeline 完整细节 (给 web 的总体方案素材)

> 2026-08-06 · 静静交付 · 请 web 汇总到 cicd.html 数据闭环方案页
> 对应实现: tools/gui/simulink_module.py (CICDPanel 6环节) + tools/cicd_pipeline.py

---

## 1. 总体链路图 (6 环节环形闭环)

```
┌─────────────────────────────────────────────────────────────┐
│ ①采集 → ②训练 → ③验证 → ④集成 → ⑤部署 → ⑥推理 ──┐          │
│  (Orin)  (4060)  (合规)  (ECS)   (Orin)  (产线)   │          │
│  └─────────────────────────── 数据回流 (推理→采集) ─────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**物理链路**:
```
Orin(192.168.23.66 采集) → 小芳Mac(192.168.23.1 中转) → ECS(39.102.211.79 relay)
→ 4060 WSL(训练) → 静态URL(模型) → 小芳部署 → Orin(推理) → 回流
```

---

## 2. 每个节点的说明 / 输入 / 输出 / 数据质量

### ① 采集 (collect)
- **说明**: 拉取 Orin 真实数据, 修复 action, 落地本地
- **实现**: `on_collect` → GET `/api/relay/status` + `/api/relay/orin/status` → 拉数据包
- **输入**: Orin 相机图像 + 6D 关节状态 + 4D 动作标签 (MCAP/JSON)
- **输出**: `data/orin_live/*.json` (采集包) → `data/orin_6d/` (LeRobotDataset)
- **数据质量**:
  - ⛔ **IDLE 标签数据禁止训练** (动作全 0 污染模型, build 时过滤)
  - ✅ 非零动作帧 ≥ 90% (验收)
  - ✅ 图像 var ≥ 3000 (真画面, 非黑图/灰图)
  - ✅ 时间戳 = episode 内相对 (0, 1/30, ...), 绝对时间戳会双重偏移
  - ✅ episode_index 连续编号 (IDLE 过滤后必须重编号)
  - ⛔ 单包 > 100M 拒绝 (nginx 100m + relay MAX_PKG 413)

### ② 训练 (train)
- **说明**: ACT 训练, 优先 Orin 真实数据 (metaworld 仿真为预训练)
- **实现**: `on_train` → `lerobot_train --config_path config_act_loop.yaml` (2000步)
- **输入**: LeRobotDataset (state6D/action6D 或 state3D/action4D) + 配置 (steps/batch/lr)
- **输出**: `outputs/train/act_loop/checkpoints/002000/pretrained_model/` (model.safetensors)
- **数据质量**:
  - ✅ loss 收敛 < 1.6 (真机 6D 基线)
  - ✅ 训练锁 (输出目录存在即跳过, 防并发破坏数据集)
  - ✅ IDLE 包不触发训练 (frames≥20 才拉)
  - ✅ 三阶段渐进: S1 metaworld 冻结 backbone → S2 零样本测 RealityGap → S3 真机低 lr 微调

### ③ 验证 (validate)
- **说明**: 模型标准合规校验 (Model Advisor 对标)
- **实现**: `on_validate` → 校验 config.json 维度 / 节点拓扑 (7节点6连线)
- **输入**: 训练产物 checkpoint + 拓扑 flow
- **输出**: PASS/FAIL (zmax_canvas_flow.json 校验)
- **数据质量**: ✅ 维度匹配 (state 维度 = 输入特征) · ✅ 节点拓扑完整

### ④ 集成 (integrate)
- **说明**: 打包 checkpoint → ECS 中转
- **实现**: `on_integrate` → scp/upload 到 ECS `/root/zmax-relay/data/`
- **输入**: `model.safetensors` (~84MB)
- **输出**: `pkg_<ts>.npz` (ECS 队列) 或覆盖静态 URL
- **数据质量**: ✅ 文件完整 (size 校验 87576920B) · ⛔ 单包 > 100M 拒绝

### ⑤ 部署 (deploy)
- **说明**: 推送模型 → Orin, 心跳验证
- **实现**: `on_deploy` → 小芳监听器拉取 → Orin `act_model.safetensors` 覆盖 → 重启推理服务
- **输入**: ECS 模型包 / 静态 URL
- **输出**: Orin 加载新模型 (心跳上报 model 名)
- **数据质量**: ✅ Orin 在线 + 心跳 < 30s · ✅ 模型名 = act_model.safetensors

### ⑥ 推理 (infer)
- **说明**: Orin 推理状态 (infer_count / 延迟)
- **实现**: `on_infer` → GET `/api/relay/orin/status` 读 infer_count/last_infer_ms
- **输入**: 产线 TCP 位姿 / 6D 关节 → 模型推理
- **输出**: 动作块 (7,6) + infer_count 递增
- **数据质量**: ✅ infer_count > 0 (真实推理发生) · ✅ 延迟 < 70ms (Orin 实测 479ms v2)

---

## 3. 全链路数据质量管理方法

| 环节 | 质量手段 | 落地位置 |
|---|---|---|
| 采集 | IDLE 过滤 + 图像 var 检查 + 非零动作率 | build_orin6d_dataset.py |
| 传输 | 100M 单包上限 + 缓冲总量 100M + 拉取即删 | nginx + zmax_relay.py |
| 训练 | 训练锁防并发 + IDLE 不触发 + loss 阈值 | auto_loop.py |
| 模型 | 维度校验 + 静态 URL 覆盖即部署 | validate + ECS models/ |
| 部署 | 心跳监控 + 模型名确认 | orin/status |
| 推理 | infer_count + 延迟监控 | cicd.html |

## 4. 管理手段 (全链路)

1. **自动闭环守护** `tools/auto_loop.py`: WS 事件驱动 (数据到达即训练) + 60s 轮询兜底 + 断线 5s 重连 + 训练锁
2. **水流 DDS** `zmax-website/waterflow_dds.py`: 每 10s 刷写 7 节点状态到 dds.db (dds_node_state + dds_flow 时间序列)
3. **容量守卫** `tools/disk_guard.py`: orin_live 限 60 包 / 训练保留 4 个 / 日志 5MB / 水流 2 万行
4. **模型传递铁律**: 静态 URL `https://datadrive.world/models/act_cartesian.safetensors` (不弹栈, 覆盖即部署)
5. **监控**: cicd.html (Orin CPU/GPU/内存/磁盘/带宽/温度 + 快照直播)

## 5. 端侧分工 (小芳)

- Orin: 采集 (相机+6D关节) → 上传 ECS → 部署模型 → 推理服务 → 心跳上报 (含 sys 性能)
- Mac: 中转 (唯一通公网+内网) + 监听器 (拉模型自动部署)
- 接口: `/sim_joint_trajectory`(6D) · `/robot/tcp_pose`(笛卡尔) · `/motion/initialization_complete`

## 6. 指标 (KPI)

- 闭环周期: 采集→部署 < 5min (实测 41s 传输 + 2.5min 训练)
- 推理延迟: Orin v2 479ms / v1 1051ms
- 训练: 2000 步 loss 1.543 (真机 6D) / 1.551 (仿真 4D)
- 容量: 单包 ≤ 100M / 队列 ≤ 100M / 磁盘守卫自动清理
