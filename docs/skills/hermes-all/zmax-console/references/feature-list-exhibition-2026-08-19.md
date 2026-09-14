# Feature List 展品特征清单 — 编写规范 (2026-08-19 老倪)

入口: 菜单栏最右「帮助文档」→ 第一项「✨ Feature List · 产品特征清单」→
FeatureListDialog (tools/gui/feature_list.py, QTextBrowser 弹窗, 非模态)。

## 内容规范 (用户明确要求, 展品/对外场景)
- **不强调模型架构**: 禁 ACT/SmolVLA/MLP/VLA-Touch/AWE/LEW/latent/backbone/
  transformer/蒸馏/坐标叠加/39D/58D 等词 (程序校验: grep re.I 必须为空)
- **从工程需求角度 + 标准接口角度**定义展品特征
- **偏向: 场景 / 功能 / 标准接口 / 性能指标**

## 5 板块结构 (老倪认可)
1. **产品定位**: Z700 (L4 全自主) / Z700F (Fix L2 固定工位) / 服务对象
2. **应用场景**: 技术协议 v3 5 大场景表 (场景/作业对象/工位/节拍/成功率)
   - FW Loading+EEPROM ≤6s · 上下料搬运按趟 ≥99.5% · BI老化箱插拔 ≤60s ·
     热海柜体电口+光口插拔 ≤20s · ATS检测插接 ≤15s (成功率均 ≥99%)
3. **核心功能** (工程需求视角, 8 项): 端侧自主作业 / 精细操作技能库 /
   力控保护 / 多阶段作业编排 / 边学边练闭环 / 仿真先行验证 /
   多方案统一管理 / 大屏指标监督
4. **标准接口** (7 项): 部署(热更新) / 数据(SN追溯) / 监控(HTTP上报) /
   消息(飞书) / Web(datadrive.world) / 训练(容器化) / 硬件(Orin+7轴+传感)
5. **性能指标**: 插拔成功率 (验收口径 ≥99% / 仿真实测 抓起6-8/8 插入4-6/8
   **如实标注** 不吹牛) · 节拍 · 负载 (插拔>1.00kg 搬运≥5kg) · 端侧轻量化
   <1M 参数 · 24h 连续作业

素材来源: docs/Z700_technical_agreement_v3.md (5场景/节拍) +
factory_fine_ops_demand.md (需求) + 实测评估 (reports)。

## 技术坑
- **QTextBrowser HTML 别用 % 格式化!** CSS `width:100%` 和数据里 `≥99%` 的裸 %
  会被 % 格式化吞成占位符 (TypeError: not enough arguments) → 用 replace 占位符
  (%TEXT% 等) + .replace() 链
- 窗口标题禁 emoji (VcXsrv 变 ??) — 菜单项可带 emoji (现有菜单大量使用)
- 弹窗必须非模态 (show(), 不 exec_) — 弹窗零容忍铁律
- 容器环境 (Docker Desktop, 无 /mnt/c/explorer.exe) 下文档打开链路不可用 →
  对外展示内容直接 GUI 弹窗, 不依赖外部打开器
