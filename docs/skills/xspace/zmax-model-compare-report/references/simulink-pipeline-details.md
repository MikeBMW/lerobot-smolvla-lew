# Simulink Pipeline 完整细节 (给 web 汇总 cicd.html 数据闭环方案页)

> 2026-08-06 老倪: "结合simulink的pipeline, 小芳在cicd页面总结数据闭环完整方案…静静你要配合将simulink的所有细节告诉web"
> 仓库文档: `docs/SIMULINK-PIPELINE-DETAILS.md` (已推送)
> 实现参考: `tools/gui/simulink_module.py` (CICDPanel 6环节) + `tools/cicd_pipeline.py`

## 总体链路 (6 环节环形)
```
①采集(Orin) → ②训练(4060) → ③验证(合规) → ④集成(ECS) → ⑤部署(Orin) → ⑥推理(产线) ─┐
└──────────────── 数据回流 (推理→采集) ───────────────────────────────────────────┘
```
物理链路: Orin(192.168.23.66) → Mac(192.168.23.1) → ECS(39.102.211.79 relay) → 4060 WSL → 静态URL → 小芳部署 → Orin 推理 → 回流

## 每节点 I/O + 数据质量 (cicd 页面要展示的核心表)
| 节点 | 输入 | 输出 | 质量要求 |
|---|---|---|---|
| ①采集 | 相机图+6D关节+4D动作 | orin_6d 数据集 | IDLE禁训·图var≥3000·时间戳相对·episode连续 |
| ②训练 | LeRobotDataset | model.safetensors | loss<1.6·训练锁·三阶段渐进 |
| ③验证 | checkpoint+flow | PASS/FAIL | 维度匹配·拓扑完整 |
| ④集成 | 模型84MB | pkg_npz→ECS | 单包≤100M·size校验 |
| ⑤部署 | ECS模型/静态URL | Orin加载 | 心跳<30s·模型名确认 |
| ⑥推理 | 产线位姿 | 动作块+infer_count | count>0·延迟<70ms |

## 全链路管理手段
1. auto_loop.py: WS 事件驱动(数据到达即训) + 60s 轮询兜底 + 断线5s重连 + 训练锁
2. waterflow_dds.py: 每10s 刷写 7 节点状态 (dds_node_state + dds_flow 时间序列)
3. disk_guard.py: 采集60包/训练4个/日志5MB/水流2万行
4. 模型铁律: 静态 URL 覆盖即部署 (不弹栈)
5. cicd.html 监控: Orin CPU/GPU/内存/磁盘/带宽/温度 + 快照直播

## KPI
闭环<5min · 推理479ms(v2)/1051ms(v1) · 训练loss 1.543(真机6D)/1.551(仿真4D) · 单包≤100M

## 端侧分工 (小芳 docs/END-SIDE-PIPELINE.md)
- Orin: 采集→过滤(JOINT_EPS=0.01rad+200ms)→打标→上传; 推理→心跳(含sys性能)
- Mac: 中转(唯一通公网+内网) + 监听器(拉模型自动部署) + 影子模式(sim-to-real 4D对比)
- 接口: /sim_joint_trajectory(6D) · /robot/tcp_pose(笛卡尔) · /motion/initialization_complete

## 协同: Simulink 五模型对比 ↔ 闭环
- 仿真数据(metaworld) → 训练 5 模型 → 4D 笛卡尔模型 → 影子模式 sim-to-real 迭代
- 端侧 14 节点图 (现场层 N1-N9 / 云端层 N10-N13 / 控制台 N14) 与 Simulink 6 环节是同一闭环的两套粒度视图
