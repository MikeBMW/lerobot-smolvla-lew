# 流形 3D 可视化 + 画布行级重排 (2026-09-08 凌晨, v5.0~5.2 期间)

## 一、pyqtgraph 第二 GL 窗口全崩 → QPainter 2.5D 自绘
症状: 新建第二个 GLViewWidget(独立窗口,如性能流形碗窗)时,该窗口**所有** GL item
绘制崩 (`OpenGL.error.GLError: glGetAttribLocation`)——pyqtgraph shader 全局缓存
(`opengl/shaders.py` 模块级)只在**第一个** GL 上下文编译,新上下文拿旧句柄 → 全崩。
3.3.0 修的"二次打开背景丢"只覆盖**复用同一窗口**,新窗口无解。
**正解 = 第二窗口不用 pyqtgraph GL,改 QPainter 2.5D 正交投影自绘**:
- 静态曲面(碗/网格)预渲染成 QPixmap(paintEvent 只在 resize/首次画),每帧只投影动态
  点/轨迹/竖线(几十行),零 GL 依赖,Windows exe 也稳。
- 投影: 固定相机 eye/right/up/fwd, `d=p-eye; x=cx+dot(d,right)*s; y=cy-dot(d,upv)*s`;
  半透明 quad 按中心 depth 远→近排序再 fill(合成正确)。
- 配套坑: ①`GLSurfacePlotItem(shader=None)` 本机崩 glGetAttribLocation → 用
  `GLMeshItem(meshdata=MeshData(vertexes, faces), color=单色, drawEdges=True)` 稳;
  ②`QPolygonF` 在 **PyQt5.QtGui**(不是 QtCore,ImportError 实锤),QPointF 在 QtCore;
  ③第一上下文内 additive items OK,但新窗口里 `setGLOptions("additive")` 也崩。

## 二、Scope/波形消费 tr **顶层** mani_* 序列,不是 io_trace
引擎 `state_space_sim.py` tr 有顶层 `mani_risk/progress/eta/V/rem/dperp` 序列,
Scope 流形格/波形/验证层消费这些(代码注释:"真实化轨迹仅引擎快演含流形格")。
sim_real(真实化)只给 io_trace 加流形 channel → **Scope 流形格仍空**(画布 demo 有值,
Scope 没有)。修 = sim_real tr 初始化加同 keys + 每步 append(except 分支补 0 对齐长度,
防 np.min 空数组崩)。画布节点播放 demo 读 DataWorld(io_trace);Scope 读顶层序列——
**两条消费链,两条都要喂**。

## 三、画布 row_bg 行级重排(flows json)铁律
- row_bg 节点字段: {id, type:"row_bg", name(大字行名), x(-20 全宽), y(行顶),
  w(3000), icon, color, h(行高), params:{bg(底色), desc, source}}。
- 重排顺序 = 每行 bg 平移 + **其业务节点显式跟随**(行 y 差 + 节点 y)。
- ⚠️ 勿用"最近行"(min |y-bg_y|)自动归属——行重叠/节点落行间隙时归错行,节点错位
  (实锤: 状态机行吞了技能节点)。必须**显式 id→行 map**,写死全部 40+ 业务节点。
- 行 y 分配: 顶行定 y0, `y_next = y_prev + h_prev/2 + h_cur/2 + 45`(缝 45),防 bg 重叠。
- 新旧坐标换算: **先 `git show HEAD:flows/x.json` 读基线坐标**,算 delta 平移;
  **绝不要 `git checkout -- flows/...` 覆盖工作区** —— 多并行会话(飞书端 agent)共享
  同仓库时,未提交的 v5.2.1 重排改动会这样被直接抹掉(git 无对象可找回,只能重建,
  实锤 2026-09-08)。重排/大规模改 flows 前: git status + git log 确认谁是 HEAD,
  改动后**立即 commit**,别攒。
- 校验: 行 y 升序且缝>50;节点行归属差集断言(`业务节点集合 == map 键集合`);连线
  数不变;links 只连业务节点(删空 bg 行安全)。

## 四、原子技能层落地模式(画布层,不碰引擎)
- 8 技能节点 = 八阶段模板 SK01-08, params.skill={template, stage}; name "① 接近 · SK01"
  (①-⑧ 前缀 match 唯一,防 match_node 最长子串误配)。
- node_logic: `_reg("sssk1", ["① 接近"], desc, node_ss_skill)` ×8; demo 播放特判——
  `_demo_node_output` 顶部 `if (match_node(name) or "").startswith("sssk"): return
  node_ss_skill(ctx)`(技能 fn 轻量读 module._ss_tr 当前帧,无 YOLO/LLM 副作用,播放可直跑)。
- node_ss_skill 读 tr[idx]: stage(当前技能)/target(决策实时赋值目标)/u_exec_vec
  (实际下发速度)→ 打印 ▶激活·模板实例化 vs 待命。
- 连线: 删 🛡安全限幅→🤖执行器 直连,改 🛡→8 技能(安全 action)→8 技能→🤖(技能执行
  指令);同 port 多入线允许(ssworld→ssvideo in1 双线先例)。

## 五、多并行会话抢 flows 的纪律(实锤升级)
- 另一会话(飞书端 gateway agent)在 HEAD 之上改 flows(改行名 L2/L3/L4/数据源置顶/
  VLM+DiT 合行/加 ssmani_exp)但**未提交**;本会话 `git checkout -- flows/...` 将其
  抹掉(只留 dangling commit 但无该内容)。恢复 = 按用户指示等价重建 + commit。
- 铁律: 与并行 agent 共仓库时, flows/studio.py 等共享文件的基线一律 `git show
  HEAD:<path>` 读,**禁止 checkout/reset 触碰工作区**;做完立即 commit+push 抢回所有权。
