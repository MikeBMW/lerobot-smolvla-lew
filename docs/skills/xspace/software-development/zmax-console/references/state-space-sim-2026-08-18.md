# 状态空间画布 — 仿真引擎/Scope/操作视频 (2026-08-18)

## 架构
- 画布: flows/state_space_obs.json (16节点15连线: 4背景行+10功能+Sope+操作视频)
- 六层源码: src/lerobot/policies/left_right/state_space/{perception,parallel,
  dynamics,cognition,safety,execution}.py — 画布=源码=运行一条链路
- 引擎: tools/gui/state_space_sim.py — importlib 按文件路径加载六层 (避开
  lerobot 包级 torch 依赖), 纯 numpy, 500步<0.1s
- GUI: start_sim 检测 state_space 节点 → _start_state_space_sim (引擎快跑→
  20快照播放动画→每轮真实数值→完成汇总); ⏹ 可打断

## 物理建模 5 坑 (全部实测, 数值必须物理自洽)
1. **状态转移 A=0.95 每步衰减 → 虚假残差 → 频繁否决**: 物理自洽 = A=1.0 (位置
   保持) + B=dt (速度指令积分)。AdaptiveStateEstimator.predict 原实现漏乘 B,
   速度指令被全量加入 → latent 被推飞 → 补 B 参数。
2. **卡尔曼平滑吃掉接触信号**: 力维走估计器 → 残差被校正吸收 → 调度器收不到
   接触。接触力是外部事件不可预测 → 力残差 = 实测力 (residual[3]=force_norm,
   不经卡尔曼)。
3. **夹爪是开关量, 不参与加权融合/限幅**: w_ff=0.3 稀释 → 夹爪永远闭不到阈值;
   saturate(0.6) 也截断 1.0。u[3]=u_ff[3] 直通, 限幅后 u_sat[3] 还原。
4. **比例控制近距力小 + 接触阻尼 → 蜗牛爬行**: 10s 走不完最后 6mm → 近距
   (dist<0.03) 叠加最小趋近推力 0.03·dir_vec (真实力控插入)。
5. **调度器融合权重按阶段切换**: 接近=慢通道主导 (0.3前馈+0.7校正, 防碰撞);
   抓取/插入=前馈推力主导 (0.85+0.15, 力控) — 否则推力被稀释。

## CognitiveScheduler (任务调度器) — 真实状态机
- 6阶段: 接近→抓取→抬起→转移→插入→完成; advance(contact_p, dist_h, gripper,
  depth) 证据驱动推进 (力觉/几何证据, 不靠外部硬推 stage_idx)
- 否决权: residual > veto_th → 减速重试; 连续 max_veto 次 → 异常上报
- history 记录阶段切换原因
- 引擎 done 判定 = sched.stage()=="完成"

## GUI 语义 (老倪 2026-08-18 明确)
- **仿真结果的呈现 = 📊仿真波形 (Scope 内容)**: 距离/前馈/残差/接触概率 2x2
  曲线 + 阶段切换竖线 (StateSpaceScopeDialog, QPainter, wqy 字体)
- **操作视频 = metaworld 训练后 rollout**: 状态空间画布双击 → 播放 MLP 策略
  现成 mp4 (前馈加速器≈左脑MLP), 不弹通用 ACT/SmolVLA 三模型
- 容器无 .venv/torch/权重 → rollout 生成必失败 → 诚实标注, 直接播现成视频
- 视频选片: 排除 rot180/rot 变体 (内容旋转过=文字反着), 固定优先级
  (发送_MLP插拔成功 > mlp_insert_success_final > ...)

## 终端白字 (log_box)
- QSS 颜色若不在 switch_theme 映射表 → 暗色下暗底深灰字看不清
- 修复: 固定暗底白字 (background:#0d1117; color:#ffffff) + switch_theme 循环
  `if wdg is self.log_box: continue` 跳过

## 源码查看器 (容器环境)
- 容器无 /mnt/c + 无 explorer.exe (WSL interop 断) → open_node_source 老链路
  必挂 → SourceViewDialog 弹窗 (绝对路径+行号+📋复制路径+只读源码)
- get_external_source sym 匹配必须支持 `class X:` 冒号 — 否则重写类后行号
  偏移 → 源码截错位置 (显示几行)
- 画布新节点必须注册 node_logic (match/EXTERNAL_LOC), 否则双击"没有独立逻辑"
