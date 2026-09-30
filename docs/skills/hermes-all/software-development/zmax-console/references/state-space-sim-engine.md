# 状态空间仿真引擎 (state_space_sim.py) — 设计与参数标定坑

GUI 集成: `tools/gui/state_space_sim.py` + `gen_state_space_video.py` (Pillow 渲染)
源码: `src/lerobot/policies/left_right/state_space/*.py` (六层, importlib 按文件加载避开 torch)
画布: `flows/state_space_obs.json` (▶运行 检测 state_space params → 引擎而非占位观察模式)

## 架构

引擎按画布拓扑驱动六层真实源码 (importlib.util.spec_from_file_location 加载, 仅 numpy 依赖):
```
📡fuse_sensors(43D obs) → ⚡FeedforwardAccelerator.forward(u_ff)
  ‖ 🔮AdaptiveStateEstimator.predict/update (卡尔曼)
  → 📈PriorDynamicsPredictor.predict (先验) → 🧪state_correction (残差+校正)
  → 🧭CognitiveScheduler.decide (否决/融合) → 🛡saturate (限幅)
  → 🤖RobotExecutor → 🌍PhysicalWorld.observe (噪声 z_k) → 闭环
```
- 潜状态 4D = 位置3 + 预测接触力1; 观测 z_k = 位置(噪声) + 力觉归一化
- 物理世界: 位置积分 + 接触阻尼(孔壁) + 夹爪一阶 + 插入判定
- 阶段推进: 调度器 advance() 状态机 (证据: contact_p/dist_h/gripper/depth), 引擎不再硬推 stage_idx

## 参数标定坑 (全部实测, 2026-08-18)

1. **A=0.95 默认状态转移 = 虚假残差**: 每步位置衰减 5% → 预测 vs 观测差出
   u_ff 量级 → 频繁否决。物理自洽: A=1.0 (位置保持) + B=dt (速度指令积分)。
   AdaptiveStateEstimator.predict 原实现漏了 B (直接 +action), 必须 B=dt。

2. **卡尔曼平滑吃掉接触信号**: 力维进潜状态后被 est.update 校正 → 残差力维≈0
   → 调度器收不到接触。修复: 力残差 = 实测接触力 (接触力是外部事件不可预测,
   预测力恒 0), 不经过估计器平滑: `residual[3] = force_norm`。

3. **夹爪指令被融合权重稀释**: u = 0.3·u_ff + 0.7·u_fb → gripper 1.0 变 0.3,
   夹爪永远闭不到阈值。修复: 夹爪是开关量不参与位置加权融合, 直通
   `u[3] = u_ff[3]`, 且饱和限幅也不作用于夹爪通道。

4. **比例控制近距蜗牛爬行**: Kp·(target−pos) 近距→0, 接触阻尼 0.75 每步衰减,
   稳态 v≈8µm/步, 10s 走不完最后 6mm。修复: 近距 (<0.03) 叠加最小趋近推力
   (0.03·dir_vec, 真实力控插入语义)。

5. **融合权重 0.3 稀释插入推力**: 接触后 u_ff 推力被 0.3 权重稀释 → 蜗牛。
   修复: 认知调度按阶段切换权重 — 接近=慢通道主导(0.3 前馈, 防碰撞),
   抓取/插入=前馈推力主导(0.85 前馈 + 0.15 校正兜底)。

6. **decide 把"接触"当否决**: 接触概率>阈值直接停车 → 永远到不了插入。
   修复: 接触=阶段推进信号(→抓取), 只有残差>veto_th 才否决, 连续 max_veto 次
   报异常。

## 视频输出 (▶运行 完成后自动)

- 引擎 tr 记录 x/gripper/force 完整轨迹 → Pillow 渲染帧 (俯视图: 孔位/夹爪/
  轨迹渐变/HUD) → ffmpeg 合成 → scp 传 ECS (datadrive.world) → 终端打印链接
- 线程安全铁律见 gui-crash-pitfalls.md (Pillow 线程内渲染 OK, Qt 禁入工作线程)
- 画布节点: 📊仿真波形 (双击 Scope 2x2 曲线: 距离/前馈/残差/接触概率 + 阶段
  切换竖线) + 🎥操作视频 (双击 → InferenceVideoDialog metaworld rollout 对比)

## 验证铁律

- quick_run: 插入完成 5.8-7.9s, 残差峰值≈0.8 (接触力), 接触概率峰值≈1.0,
  阶段序列必须含 接近→抓取→抬起→转移→插入→完成 全链路
- 集成测试: offscreen + QTimer 驱动 加载画布→start_sim→播放完→视频线程→8s 存活
