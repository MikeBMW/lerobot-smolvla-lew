# 🧮 状态空间模型画布 (2026-08-17 老倪: 贴 flowchart 流程 → 做"状态空间"新按钮打开模型画布)

## 需求
老倪贴 flowchart(传感器融合→43D obs→并行快慢分离→认知决策否决权→执行器→物理世界+卡尔曼反馈闭环),
要求: "做一个状态空间的新按钮, 打开这个模型画布, 在simulink功能里"。

## 产物
- `flows/state_space_obs.json` — 14 节点 13 连线, 4 层 row_bg 分区:
  - S1 时空感知前端 y=-190: 📡传感器融合(hardware, x=120) → 🧩43D obs(system, x=460, out1/out2)
  - S2 并行处理层 y=40: ⚡前馈加速器(model, x=120, #FFD700, params.ff_accel, w_ff:0.3)
    ‖ 🔮自适应状态估计器(model, x=480, #87CEEB, params.kalman_estimator, out1/out2)
    → 📈先验动力学预测器(model, x=860, params.prior_predict)
    → 🧪创新检测与状态校正器(model, x=1120, #FF6B6B, params.innovation, in1/in2, out1/out2)
  - S3 认知决策层 y=320: 🧭认知任务调度器(system, x=380, #FF6B6B, params.cognitive_scheduler, in1/in2, w=280, h=100)
    → 🛡安全执行边界(system, x=780, #d29922, params.sat_limit)
  - 执行层 y=550: 🤖机器人执行器(hardware, x=380) → 🌍物理世界(hardware, x=780)
  - 反馈闭环 2 连线: 物理世界→创新检测(z_k 传感器反馈) + 创新检测→先验预测器(校正后潜状态)
- 节点 id 统一 ss 前缀: sssensor/ssobs/ssff/ssest/sspred/ssinnov/sssched/sslimit/ssact/ssworld
- 所有节点 params 带 `state_space: True`(双击分发判据)

## 工具栏按钮 + 打开方法 (与 open_ff_pd_top 同款模式)
```python
self.btn_state_space = mk_btn("🧮 状态空间", "状态空间模型: ...", self.open_state_space, "#87CEEB")
tl.addWidget(self.btn_state_space)   # 放 ⚙️前馈 PD 后, ⏹停止 前

def open_state_space(self):
    self.clear()
    flow = os.path.join(self._repo_root(), "flows", "state_space_obs.json")
    if not os.path.exists(flow) or not self.load_flow_file(flow, confirm=False):
        self._qmsg_info("🧮 状态空间", "状态空间模型画布加载失败"); return
    # 5 条引导日志 (S1/S2/S3/执行层 + 反馈闭环)
    QTimer.singleShot(300, self._state_space_hint)   # 高亮认知调度器 + 气泡
```

## 双击分发 + 详情
- on_node_activated 加分支 (编号 1.81, 放 z700_internal 分支后):
  `if params.get("state_space"): self._show_state_space_detail(node); return`
- `_show_state_space_detail(node)`: 按 params 键分发
  (ff_accel/kalman_estimator/prior_predict/innovation/cognitive_scheduler/sat_limit/传感器融合 in name)
  → QDialog + QTextBrowser html(640x460, 深色 QSS 同 _show_internal_detail 模式), 每层一个
  状态空间环节解释(公式+组件对照表+物理含义)。
- 内容要点: 快慢分离(快=前馈毫秒级无迭代, 慢=递归校正给置信) / 卡尔曼组件↔GRU门控对照 /
  残差 r=z_k−ĥ(x̂) & 校正 x̂=x̂₋+K·r / 否决权(残差>阈值强制减速重试) / 动作融合 u=w_ff·u_ff+(1−w_ff)·u_fb /
  43D=39D 视觉结构+触觉 4D。

## 坑
- **patch 大方法区时函数头会被吞**: 用 `dlg.exec_()` + 下一方法体当 old_string 边界,
  new_string 忘了带 `def on_ff_pd_config(self, node):` → 函数体悬空挂到上一方法。
  症状: py_compile 报缩进错/方法名 undefined。修复 = 单独 patch 补回 def 行。
  铁律(再次验证): **patch 一个方法区域, 所有涉及方法的签名都要成对出现在 old/new 文本里**,
  改完立即 py_compile + grep 方法边界。
