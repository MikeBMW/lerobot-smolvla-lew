# 前馈PD 最终版: 纯规则二阶代数方程 + 感知链 K_obs 改名 (2026-08-15 深夜终版)

老倪贴完整拉普拉斯推导后要求"将这些在前馈PD里实现" — 数学内核从
refs/ffpd-dual-channel-math-and-ui-2026-08-15.md 的"双通道校正 Kd_eff=Kp·Kd"升级。
⚠️ **本文件是终版, dual-channel 里的 Kd_eff=Kp·Kd 已被取代** (用户推导 Kd 直接加 b)。

## 纯规则前馈PD 二阶代数方程 (analyze_system ff_pd 分支)

```
时域: m·ẍ + b·ẋ + k·x = F(t);   F = K_ff·r + Kp·e + Kd·ė   (e = r − x)
s域: [m·s²+(b+Kd)s+(k+Kp)]·X(s) = [Kd·s+(K_ff+Kp)]·R(s)
闭环: G_cl(s) = (Kd·s + K_ff+Kp) / (m·s² + (b+Kd)s + (k+Kp))
特征方程: m·s² + (b+Kd)s + (k+Kp) = 0   ← K_ff 不进特征方程 (只移零点, 不改稳定性)
特征解: s₁,₂ = [−(b+Kd) ± √((b+Kd)²−4m(k+Kp))]/(2m)
ωₙ = √((k+Kp)/m);  ζ = (b+Kd)/(2√(m(k+Kp)))
稳态: T0 = G_cl(0) = (K_ff+Kp)/(k+Kp);  静差 e_ss = 1 − T0
```

**关键差异 vs 旧版**: Kd 直接进 `(b+Kd)` 系数 — **不乘 Kp**。旧"串联校正 C=Kp(1+Kd·s)
→ Kd_eff=Kp·Kd"的模型是 2026-08-14 的中间版, 用户 08-15 推导的纯规则 PD
(F=K_ff·r+Kp·e+Kd·ė) 里 Kd 就是微分增益本体。

## 参数来源 (z700_internal 节点 params, 画布可标定)

| 节点 | key | 默认 | 语义 |
|---|---|---|---|
| 感知链 | K_obs | 1.0 | 前馈观测增益 y=Cx (非PID组件) |
| 双脑 | K_ff | 0.2 | 前馈增益 (左脑预测动作) |
| 状态机 | Kp | 2.0 | 比例增益 (增益调度) |
| 动作 | Kd | 0.3 | 微分增益 (阻尼) |
| 动作 | m/b/k | 1.0/2.0/5.0 | 末端质量/机械阻尼/环境刚度 |

## 感知链 Kp→K_obs 改名 (老倪"为什么感知链是kp呢")

感知链的 "Kp=1.0" 实为观测增益 (y=Cx 的 C), 与状态机比例增益 Kp 撞名误导。
**全链路改名**: ①flows/ff_pd_top.json params ②_paint_internal 的 _pkeys 列表加
"K_obs" ③analyze_system 的 `_p("感知链","K_obs",1.0)` ④on_ff_pd_config keys 列表
加 ("K_obs", 0.0, 10.0)。数学结果不变 (F_gain = K_obs·K_ff)。

## 增益调度 5 阶段 (用户推导表, 转移/插入体现临界/过阻尼意图)

接近 Kp2.0/Kd0.3 → 欠阻尼快速趋近; 抓取 0.1/0 锁定; 抬起 0.8/0 z比例;
转移 0.6/**1.2** → 临界阻尼; 插入 0.5/**2.0** → 过阻尼绝对无冲击。
⚠️ 实测默认 m=1/b=2/k=5 下全阶段 ζ<1 仍欠阻尼 (转移 ζ=0.68/插入 0.85) —
用户表格是设计意图, 实际类型按算出来显示, 别硬标"临界/过阻尼"。

## ⚠️ 改 analyze_system 字段必须同步 _show_math 引用

本会话把 Kd_eff/T 从 ff_pd dict 删除后, _show_math 旧显示代码还引用
`fp["Kd_eff"]`/`fp["T"]` → KeyError 崩 (offscreen 验证才暴露)。
**铁律: 改 analyze_system 返回结构 → grep _show_math 对 ff_pd dict 的所有引用同步改**。
显示文本五段: 时域→s域→闭环传函→特征方程/特征解/ωₙ/ζ→前馈补偿效果→增益调度表。

## 验证

- 特征/零点多项式与手算 np.array([m, b+Kd, k+Kp]) / np.array([Kd, F_gain+Kp]) 全等
- 5 阶段极点 = np.roots(每阶段特征多项式) (注意阶段级也用 Kd 直接加, 不乘 Kp)
- _show_math 文本含 "纯规则前馈PD"/"特征方程"/"ωₙ"/"不进特征方程" 等关键段
