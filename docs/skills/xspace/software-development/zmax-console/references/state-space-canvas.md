# 状态空间画布全套 (2026-08-17/18 实测)

Z-MAX 控制台的「🧮 状态空间」画布: 六层源码 + 仿真引擎 + 节点注册 + 库同步 + 视频导出。
数据链路: flows/state_space_obs.json (画布) → src/lerobot/policies/left_right/state_space/*.py (六层源码)
→ tools/gui/state_space_sim.py (仿真引擎) → tools/gui/gen_state_space_video.py (视频)。

## 文件清单
- `flows/state_space_obs.json` — 画布唯一数据源 (14 节点: 4 背景行 row_bg + 10 功能节点 + 13 连线)
- `src/lerobot/policies/left_right/state_space/` — 六层源码: perception/parallel/dynamics/cognition/safety/execution
- `tools/gui/state_space_sim.py` — 仿真引擎 (按画布拓扑驱动六层源码, 光模块插拔物理模型)
- `tools/gui/gen_state_space_video.py` — 视频渲染 (Pillow 帧 + ffmpeg)
- `tools/gui/node_logic.py` — 14 节点注册 (ss_* key + _EXTERNAL_LOC 外部源码映射)

## 六层源码 API (引擎调用契约)
- perception.py: `fuse_sensors(rgbd_feats39, force_6d, tactile4)` → 43D obs (OBS_DIM=43=39+4)
- parallel.py: `FeedforwardAccelerator(w_ff).forward(obs)` → u_ff 4D (解析逆动力学: Kp·(target−pos) 限幅 0.5 + 近距<0.03 最小推力 0.03 + 夹爪近距闭合); `AdaptiveStateEstimator(A,K,B).predict(latent,action)/update(latent_pred,z_k)` — **B 必须 = dt**(速度指令积分), 默认 A=0.95 每步衰减会造虚假残差
- dynamics.py: `PriorDynamicsPredictor(A,B).predict(latent,action)`
- cognition.py: `state_correction(prior,z_k,K)` → (corrected,residual); `contact_probability(residual,gain)`; `CognitiveScheduler(w_ff,contact_th,veto_th,w_contact,align_th,insert_depth,max_veto)` — **6阶段状态机**: advance(contact_p,dist_h,gripper,depth) 证据推进 (接近→抓取→抬起→转移→插入→完成), decide 按阶段融合 (接近=慢通道0.3 / 抓取插入=前馈推力0.85), 否决权 (残差>veto_th→减速, 连续 max_veto 次→异常)
- safety.py: `saturate(u,limit)` — **夹爪通道不受限幅** (开关量, 限幅只作用位置/速度)
- execution.py: `RobotExecutor(n_joints).execute(u)`; `PhysicalWorld(noise,seed).observe(state)` — 带高斯噪声 (卡尔曼残差来源)

## 仿真引擎关键坑 (全部实测调通)
1. **A/B 参数物理自洽**: 状态转移 A=1.0 + B=dt (位置保持+速度积分), 默认 A=0.95 每步衰减 → 虚假残差 0.5 → 频繁否决 → 机器人不动
2. **力残差 = 实测接触力, 不走卡尔曼平滑**: 力是外部事件不可预测 (预测力恒 0); 若用 state_correction 的残差, 潜状态力维被校正吃掉 → 接触信号消失 → 调度器收不到 (contact_p 恒 0.5); 残差力维手动覆盖 `residual[3]=force_norm` 才触发接触
3. **夹爪指令直通**: 不参与 w_ff 加权融合 (0.3×1.0=0.3 夹不紧), 也不受 saturate 限幅; 在 decide 后/限幅后各覆盖一次 `u[3]=u_ff[3]`
4. **接触阻尼才有接触**: 物理世界要挡末端 (d<D_INSERT: v[:2]*=0.3; d<D_CONTACT: v[:2]*=0.75, v[2]*=0.95), 否则末端穿过孔位, 残差=0 接触永不发生
5. **比例控制近距蜗牛爬**: 接近时 Kp 项→0 + 阻尼 → 稳态 8µm/步, 10s 走不完最后 6mm → 近距 (dist_h<0.03) 叠加最小推力 0.03·dir_vec
6. **decide 否决返回标量 0** → saturate 后 0 维数组 → `np.ndim(u_vec)==0: u_vec=np.zeros(4)` 兜底
7. 仿真 500 步纯 numpy <0.1s 快跑 → 抽 20 快照播放动画 (3s), 别逐帧播 290 轮 (232s)

## 节点注册模式 (node_logic.py)
- 14 节点全部 `_reg("ss_*", [唯一关键字], doc, fn)` + `_EXTERNAL_LOC["ss_*"] = (path, line, sym)`
- 双击/右键「查看/编辑节点逻辑」→ NodeLogicDialog → match_node(最长关键字) → get_external_source 显示真实源码 (只读)
- 关键字必须唯一且最长匹配: "任务调度器" vs "安全执行边界" vs "物理世界" vs "物理闭环" 互不包含
- **get_external_source sym 匹配必须支持 class X: 冒号** (2026-08-18 实测): 匹配逻辑 `s==sym or startswith(sym+"(") or startswith(sym+":")` — 只匹配 sym/sym( 时类定义 "class CognitiveScheduler:" 匹配不上 → 回退旧行号 → 重写类后行号偏移 → 弹窗只显示几行 (用户"代码怎么这么少")

## 模块库同步 (数据一致性)
- `_load_state_space_library_group()` 从 flows/state_space_obs.json 动态生成 LIBRARY 组 — **画布 JSON 是唯一数据源, 改画布即同步库, 杜绝手抄漂移** (仿 _load_skill_library_groups 模式)
- 库按钮支持条目级 type: 渲染处 `t=it.get("type", ntype)` (状态空间组混合 model/system/hardware/row_bg)
- 验证: 画布节点集 == 库条目集 双向零缺失 + LIBRARY_SEQ 自动编号 + data_space 自动扫描
- patch 重复字符串坑: json 里两个相同 source 字符串时 patch 只改第一个 → 按 id 精确改 (python json load)

## 视频导出 (▶运行自动出)
- 引擎 tr 记录完整轨迹: x/gripper/force (视频渲染用) — run() 的 tr 里补这三个 list
- 渲染: Pillow ImageDraw (线程安全) + wqy-microhei.ttc 中文字体 + ffmpeg libx264; **严禁 QPainter/QImage 在工作线程** (SIGSEGV, 见 pyqt5-gui-development 5b)
- 导出链路: `_ss_finish` → threading.Thread: make_video → sshpass scp 到 ECS datadrive.world → chmod 644 → `_safe_log` 打印 https://datadrive.world/state_space_sim.mp4 (后台线程日志必须 _safe_log/QMetaObject, 不能直接 _log)
- 渲染脚本独立运行需 QApplication (offscreen), 但 GUI 内 import 时 QApplication.instance() 已存在

## 环境自适应 (容器无 /mnt/c)
- open_node_source: `os.path.isdir("/mnt/c") and shutil.which("explorer.exe")` → WSL 老链路 (复制 C:\zmax_src_view + explorer); 无 (纯 Docker Desktop 容器) → SourceViewDialog 弹窗查看 (绝对路径+行号+📋复制路径按钮+只读源码, QPlainTextEdit + 行号边栏)
- 行号边栏: _CodeEditor(QPlainTextEdit) 子类 + _LineNumberArea 子 widget, resizeEvent 同步几何 (sizeHint 按 blockCount 算宽)

## 验证命令
```
cd tools/gui && timeout 30 python state_space_sim.py   # 引擎自检 (完成 True + 阶段序列)
python gen_state_space_video.py                        # 视频自检
# 集成: offscreen + SimulinkModule 加载画布 → start_sim → 等 _ss_timer 停 → 断言汇总+视频链接
```
