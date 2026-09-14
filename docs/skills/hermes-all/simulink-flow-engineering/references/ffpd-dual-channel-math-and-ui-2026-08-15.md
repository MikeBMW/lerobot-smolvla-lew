# 前馈 PD 双通道校正数学化 + 内部模块 UI 布局 (2026-08-15 午后)

老倪设计: "感知链和双脑,是前馈校正系统,状态机P和动作D是串联校正系统,你来设计参数"。
紧接着报 "字都重叠了,你好好设计一下UI"。与上午的 refs/vcxsrv-flicker-and-math-fixes-2026-08-15.md
(前 5 个问题) 同会话, 这是 ⑥⑦ 两题。

## ⑥ 双通道校正数学化 (model_tree.py analyze_system)

升级上午的"黑盒 PD"为**双通道校正**结构:

```
r(t) ──►[感知链 K_obs]──►[双脑 K_ff]──┐  前馈校正(回路外) F=K_obs·K_ff=0.2
                                      ▼    不改极点, 补偿静差
r(t)──(+)──►[状态机P]──►[动作D]──►[Z700 G(s)]──►y(t)
       ▲        └────── 串联校正(回路内) ──────┘ 决定系统特征
```

- **串联校正 C(s) = Kp·(1+Kd·s)**: ⚠️ **Kd_eff = Kp·Kd** — D 在 P 之后串联,
  等效 PD 的微分增益必须乘 Kp! (Kp=2.0, Kd=0.3 → Kd_eff=0.6, 不是 0.3)
- 被控对象 G(s) = 1/(1+Ts), T=0.1 (右脑一阶近似)
- 特征方程 (T+Kd_eff)s + (1+Kp) = 0 → **s = −(1+Kp)/(T+Kd_eff) = −4.286**
  (Kp=2/Kd=0.3 时; 若误用 Kd=0.3 不乘 Kp → 极点错成 −7.5)
- 时域原函数 y(t) = T0·(1−e^{s*·t}), T0 = (F_gain+Kp)/(1+Kp) = 0.733
- **前馈校正 F(s)=K_obs·K_ff 不进特征方程** (回路外, 经典结论): 只改稳态
  e_ss = 1−T0 = 0.267 vs 纯反馈 1/(1+Kp) = 0.333 → 削减 20%
- 验证: `"F_gain" not in str(res["den"])` (前馈不进特征多项式) + K_ff→0 时静差回纯反馈值
- _show_math 输出: 双通道结构图 + C(s)/G(s)/F(s) + 特征方程/特征解/τ/原函数/静差削减%
- ⚠️ **读取 z700_internal 参数必须按节点名过滤**: `_p(name,key)` 里
  `if name in n["name"] and key in n["params"]` — 感知链也有 Kp=1.0(观测增益 y=Cx,
  非 PID 组件), 不点名会读到第一个含 Kp 的节点 → Kp 错读成 1.0 (极点错成 −5)

## ⑦ 内部模块节点 UI 三区布局 (老倪"字都重叠了,好好设计一下UI")

**根因① (最隐蔽) — JSON w/h 不生效**: load_flow_file 只写 `n["w"] = spec.get("w", 150)`,
而 SimNodeItem 的 `self.w/self.h` 在 add_node 创建时已固定默认(w=150/h=50) → JSON 里
改 w/h 完全无效(h 更惨, 加载代码根本没写 n["h"]!)。**修复** (load_flow_file 内):
```python
n["w"] = spec.get("w", 150)
n["h"] = spec.get("h", DH)
_it = self._items.get(n["id"])
if _it is not None:
    _it.w = n["w"]; _it.h = n["h"]
    _it.prepareGeometryChange(); _it.update()
```
**根因② — 布局拥挤**: 标题+参数一行拼接挤 50px 高节点 + desc 根本不画。
**重排三区 (170×88)**: 标题(y4, 9px Bold) / 角色标签 `▸ 前馈·观测`(y24, 映射
感知链→前馈·观测/双脑→前馈·预测/状态机→串联·P/动作→串联·D) / desc(y40, 灰#8b949e
7px elide) / 参数每行一个(y55 起, 变量名青#58a6ff Bold 左 + 值白#e6edf3 右对齐,
Consolas 8px; list 格式化 "[−1, 1]")。每模块 2 参数(Kp+limit/K_ff+limit/Kp+thresh/
Kd+limit) 55+15×2=85 贴底正好。
- 验证: offscreen 渲染节点到 QImage → 标题区(y12)有像素 + 参数区(y55-85 多行扫描)有像素;
  像素检测别用单行 y=70 (两参数行边界恰好无字), 扫 58/62/66/72/76/80 多行
- 关联: JSON 里 4 内部模块 w=170/h=88 是必须的 (感知链 x=150+170=320 < 双脑 340 不重叠,
  且各在自己分区内: 前馈区 -20..520 / P 区 520..860 / D 区 860..1240)
