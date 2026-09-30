# Model Tree 数据字典 + 数学化改造 (2026-08-12)

老倪需求原文: "在右侧,增加一个下拉菜单,参考 matlab workspace, 数据字典, 做一个画布上左右参数的 model tree, 让用户能够看到每个参数,可以标定,调节;最终可以像自动化控制原理的公式,能够计算 state, output,input等参数,可以用复数空间,研究系统的稳定性;开始数学化改造"

## 架构
- `tools/gui/model_tree.py` — 全部新代码 (ModelTreeDock + 数学内核 + PoleZeroPlot)
- `tools/gui/simulink_module.py` — 集成两处:
  1. `_build` 尾部: `from model_tree import ModelTreeDock; self.model_tree = ModelTreeDock(self); split.addWidget(self.model_tree); split.setStretchFactor(split.indexOf(self.model_tree), 0)` (try/except 兜底, 失败仅日志)
  2. `load_flow_file` 尾部 (`_assign_veh5_ids()` 之后): `if getattr(self, "model_tree", None): self.model_tree.refresh()`

## 🐛 2026-08-14: QDockWidget → QWidget (右侧面板一直没显示的根因)
- 原实现 `ModelTreeDock(QDockWidget)` + `self.addDockWidget(Qt.RightDockWidgetArea, ...)` — **面板从未显示**:
  SimulinkModule 是 `QWidget`(2897 行 `class SimulinkModule(QWidget):`), 没有 addDockWidget 方法 → AttributeError
  被 try/except 吞掉(log 只有一句"⚠️ 数据字典面板加载失败") → model_tree = None, 用户多次问"右侧的参数列表栏怎么一直没有"
- 修复三处: ①类基类改 `QWidget` ②构造函数 `super().__init__(parent)` + setObjectName/setMinimumWidth
  (QDockWidget 的 `super().__init__("标题", parent)` / setAllowedAreas / setFeatures 全删) ③内部 `self.setLayout(lay)` 替代 `setWidget(root)`
  ④集成处 `split.addWidget(self.model_tree)` 嵌进水平 split 最右列(库|展开条|画布|数据字典), import 去掉 QDockWidget
- 排查口诀: **"右侧/停靠面板一直没出现" = 先查 addDockWidget 的宿主是不是 QMainWindow, 再查 try/except 是否吞了异常**;
  QWidget 容器加侧栏 = 水平 QSplitter 加一列(带 setStretchFactor(0) 固定宽可拖), 别用 QDockWidget

## ModelTreeDock 结构
- `cmb_view` QComboBox: ["📚 数据字典", "⚙️ 参数标定", "🧮 数学分析", "🎛 状态空间设计"]
- `_switch_view(idx)`: math=idx==2, ss=idx==3; show=math or ss; tree.setVisible(not show); lbl_math/plot.setVisible(show); ss→_show_state_space(), math→_show_math(), else refresh()
- `refresh()`: 清树重建 — 系统参数组(采样周期 dt=module._sim_dt, 功能节点数) + 按行分组(round(y/10) → 行 y=N*10) + 节点(行内按 x 排序) + 参数叶子(setData UserRole=(node, key)); expandAll
- `_on_item_dbl`: 仅参数叶子(tuple)触发 QInputDialog.getText 标定 → 按旧值类型转换(bool: val in true/1/yes/是; int/float: type(old)(float(val)); str 原样) → 写回 → module._refresh_node(node) + module._log + refresh()

## 数学内核 (GUI 系统 python3 有 numpy 2.5 无 scipy — 全手写)
- node_transfer(node) → (num, den):
  - hardware → [1]/[1] (数据源单位增益)
  - action → [K]/[1, a] (执行器 K/(s+a))
  - switch/train_gate/yolo_gate → [1]/[1] (路由直通)
  - condition → [1]/[T, 1] (判定 1/(1+Ts))
  - model/system → [K]/[T, 1] (K/(1+Ts))
  - 默认 → [1]/[1]
  - 参数读 params.gain/time_const/pole, 默认 K=1 T=0.1 a=2
- series_chain(nodes): np.polymul 连乘
- main_chain(module): 无入边(不在 links.t)非 row_bg 节点为源, 取第一个源 BFS 沿 links.f→t 最长链 (跳 row_bg, visited 防环)
- tf_to_ss(num, den): 可控标准型 — trim_zeros; n=len(den)-1; A[:-1,1:]=I, A[-1,:]=-den[1:][::-1]/den[0]; B[-1]=1; C=(num[1:]-num[0]*den[1:]/den[0])[::-1]; D=num[0]/den[0]; n==0 退化 1x1
- analyze_system(module): {chain, num, den, poles=np.roots(den), zeros=np.roots(num), stable=all Re<0, A,B,C,D}

## 状态空间设计视图 (老倪思想落地)
同构映射: obs=状态x · action=输入u · 右脑=转移 f(x,u)
```
u(t) ─▶ [感知 C] ─▶ x(t)=obs ─▶ [左脑 K] ─▶ u'(t)
                    │
                    ▼
              [右脑 f(x,u): x'=Ax+Bu]
                    │
              [状态机: x∈X_safe 硬约束]
```
- 节点→控制角色 (名字/类型匹配, 顺序敏感):
  - "YOLO"/"2D→3D"/"Adapter"/"Marker"/"obs" → 观测模型 y=Cx
  - "左脑" → 控制器 u=-Kx
  - "右脑" → 状态转移 x'=f(x,u)
  - "接触判定"/"➤"前缀 → 硬约束 x∈X_safe (滚动时域)
  - "metaworld"/"数据源"/hardware → 输入 u(t)
  - "LeftRightPolicy" → 输出 y(t)
  - "训练"/"推理"/"视频"/"PDF" → 监督/交付
- 理论四元组: A=[[-1/T]] B=[[1/T]] C=[[1]] D=[[0]], T=0.1
- 谱半径 ρ(A)=max|eig|; 稳定性三层次:
  ① 纯网络推理 (权重固定): BIBO 稳定 (Lipschitz 激活)
  ② 右脑自回归 (WM 开环预测): ρ<1 收敛 / ρ≥1 误差滚雪球 (JEPA 核心瓶颈)
  ③ 混合确定性 (左脑+状态机): 工程稳定 — 物理阈值硬约束拉回安全集
- 李雅普诺夫 1 阶解析: P=T/2>0 且 2*A[0,0]*P<0 → 渐近稳定
- 可控性/可观测性: rank(B)/rank(C) 判据
- 结论文案: "连续推理交给物理规则(状态机), 离散时机判断交给网络(右脑) — 混合确定性 = 工程最优解 (防潜空间状态失控)"

## PoleZeroPlot (QPainter 手绘复平面)
- setMinimumHeight(180); set_data(poles, zeros, stable) → update()
- paintEvent: 坐标轴(灰 1px), 单位圆(虚线段), Re/Im 标签, 极点×(红 #ff4444 不稳定 / 绿 #3fb950 稳定), 零点○(#58a6ff)

## 验证要点
- offscreen: dock.show() + app.processEvents() 后 isVisible 才为 True (不 show 恒 False — 环境问题非代码问题)
- 断言: cmb_view.count()==4; tree.topLevelItemCount()>=2; _switch_view(2) 后 lbl_math 含 "G(s)"/"极点"; _switch_view(3) 后含 "状态空间设计"/"谱半径"/"混合确定性"/"A=[[-10"; _switch_view(0) 后 tree.isVisible()
- 数学内核单测: series_chain([hardware, model(K=2,T=0.5), action(pole=2)]) → den 长度 3; tf_to_ss → A.shape[0]==2, B.shape==(2,1)

## 踩坑
- patch 大 (model_tree.py 14KB 新文件) 用 write_file 一次写, 别用大 patch
- Pyright 报 PyQt5 import 无法解析是环境误报 (GUI 用 /usr/bin/python3 有 PyQt5)
- 老倪"使用lerobot标准代码训练推理" = 训练已走 config_left_right.yaml + lerobot_train 容器 (标准), 推理走 gen_insert_video (自定义状态机, 因双脑+状态机架构非标准 eval 可覆盖); 汇报时说明"训练=lerobot 标准, 推理=双脑状态机定制"
