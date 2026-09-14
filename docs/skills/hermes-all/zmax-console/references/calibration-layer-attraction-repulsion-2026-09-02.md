# 标定层 = 回路外元层模式 (2026-09-02 v3.4.3, Drifting Models 引力/斥力)

## 需求模式
老倪要在**不改变任何现有拓扑/流程/架构**的前提下加"标定/元层" — 收集/展示/调节引擎散落超参数, 不参与推理。
命令式: "增加标定层, 注意不要改变任何当前的拓扑结构/流程/现有架构"。
同类需求还会出现(标定/审计/监控层), 这是一套可复用的落地模板。

## 落地四件套
1. **框架层独立目录** `src/lerobot/<module>/`(与 datasets/、policies/ **同级别**, 如 calibration/),
   纯数据/计算类, 无 GUI/torch 依赖; 数值与引擎源码**同源**(注释标来源, 如 cognition.py STAGE_V_CAP)。
2. **画布模板纯 append**: `flows/*.json` 只追加(row_bg + 节点 + 一条数据源 link),
   新 row_bg 的 y 取现有最大 y 之下(画布从上到下 y 递增, 大模型层 y=-900 在最上, 执行层 y=550 在下);
   **绝不改现有节点/连线** — append 前 assert 新 id 不存在。
3. **node_logic 注册 + 双击/右键分流**: `node_ss_*` 函数(importlib 加载真实模块, mock module._ss_tr 取运行状态)
   + `_reg` 注册 + `_EXTERNAL_LOC` 映射(注意行号双查);
   **标定类节点双击 → 专属 Dialog, 不是 NodeLogicDialog** — `on_show_node_logic` 开头按节点名分支。
4. **验证四连**: 模块计算(势函数/平衡偏差手算对照) / 节点执行(mock `module._ss_tr` 结构) /
   UI 构造(offscreen) / 模板节点数(31 节点 29 links 含新节点)。

## 引力/斥力二分 (第一性原理, Drifting Models arXiv:2602.04770)
论文核心: 反称漂移场 Vp,q(x) = −Vq,p(x), q=p ⇒ V=0(平衡/无漂移)。
映射到机器人控制超参数:
- **引力 Attraction = 快速动作**: Kp 比例增益 + 各阶段速度上限/下限(STAGE_V_CAP 8 阶段, 每阶段一个明确标定量) + 前馈限幅 + 安全限幅。
- **斥力 Repulsion = 状态预测**: K_kalman(状态校正增益) + 残差 EMA α + 接触概率增益 + 否决阈值 + 反馈增益 + 先验状态转移 A。
- **平衡偏差** = 引力势 − 斥力势:
  - 引力势 = min(1, |速度| / 阶段上限)
  - 斥力势 = 0.7·min(1, |残差|/否决阈值) + 0.3·(1−接触概率)
  - |偏差| < 0.15 = ⚖平衡; >0 引力↑动作偏快; <0 斥力↑状态修正偏强。

## UI 形态 (CalibrationDialog)
- 引力组: QTableWidget 8 阶段速度上限表, 当前运行阶段行高亮(#1f6feb)。
- 斥力组: QDoubleSpinBox(K_kalman / EMA / 接触增益 / 否决阈值 / 反馈增益)。
- 平衡点: 偏差 → QProgressBar(range -100..100, 中心=平衡), 实时数值标注。
- 💾 导出 reports/calibration_*.json, **回路外明示**: 参数可调但引擎仍用源码常量, 要生效改 calibration_layer.py 后重启。
- 运行状态取数: `module._ss_tr[idx]` — stage(去"阶段 "前缀) / u_sat 前3维模=速度 / residual / contact_p, idx 同 `_ss_tick` 映射(min(_ss_round, len(t)-1))。

## 关键文件 (2026-09-02 落地)
- `src/lerobot/calibration/calibration_layer.py` — CalibrationLayer(ATTRACTION_CALIB/REPULSION_CALIB + 势函数 + equilibrium_gap + export)
- `src/lerobot/calibration/__init__.py` — 包导出
- `tools/gui/calibration_dialog.py` — CalibrationDialog
- `tools/gui/node_logic.py` — node_ss_calib + _reg("ss_calib") + _EXTERNAL_LOC(行号 51)
- `tools/gui/simulink_module.py` — on_show_node_logic 标定层分支
- `flows/state_space_obs.json` — ssbg6 row_bg(y=800) + sscalib 节点 + lkcalib1 link(ssworld→sscalib)

## 同类先例
外观质量检测真实化(同日): 新建 `src/lerobot/policies/yolo_3d/quality_check.py`(AOIQualityChecker 真实图像处理:
拉普拉斯方差/霍夫直线/斑点/灰度偏移/边缘密度, 对照 DET-AOI-01~04)+ node_ss_aoi 接真实帧(YOLO 缓存帧或同源采样)
+ _EXTERNAL_LOC 映射 — "新增节点接真实源码三件套"的又一实例。
