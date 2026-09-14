# 前馈 PD 内部模块独立绘制 + 特征解方案进阶 (2026-08-15 深夜终版)

承接 refs/ffpd-dual-channel-math-and-ui-2026-08-15.md 的 ⑥⑦, 本文件补两处
用户连报后才到终版的内容: ⑦b 完全独立绘制(字重叠最终方案) + ⑧ 二阶特征解/
根轨迹/极点配置设计器(老倪"将这些放到标定参数里")。

## ⑦b 用户仍报"字还是重合" → 完全独立绘制 _paint_internal (最终方案)

三区布局仍叠: 通用 paint 路径有**多个残留绘制源** — 默认类型标签("系统", y=22,
`NODE_TYPES.get(t).get("cn")` 的 else 分支) + **参数摘要**(y=36, `first=list(params.items())[0]`
画 `Kp=1.0`) 与三区文字叠。跳过类型标签后 y=36 参数摘要仍在。**教训: 在通用路径里"插三区"
必然漏残留绘制源, 改一处漏一处 — 用户连报 3 次"字重叠"才到终版**。

**终版 = paint 开头完全独立分支** (row_bg return 之后立即):
```python
if self.node.get("params", {}).get("z700_internal"):
    self._paint_internal(painter, None, QColor(COLORS.get(t, "#58a6ff")), "idle")
    return
```
⚠️ 独立分支在 paint 的 `pal = THEMES[_CUR_THEME]` / `status` 定义**之前** → 调用传
None/"idle", `_paint_internal` 内 `if pal is None: pal = THEMES[_CUR_THEME]` 自取。
专用方法 `_paint_internal` 自画: 渐变背景+边框 / 标题(y2, 9px Bold, elide) /
角色标签(▸ 前馈·观测, y22, 蓝#58a6ff) / desc(y37, 灰#8b949e 7px elide) /
参数每行(y52 起 15px, 名青#58a6ff Bold 左 + 值白#e6edf3 右, Consolas 8px) /
**端口锚点必须保留**(in1 左/out1 右, 连线依赖 — 通用路径的端口绘制被 return 跳过)。

**验证 = 像素级文本带检测** (不是"有字"布尔):
```python
def text_pixels(img):  # 文字特征色(白/青/灰亮)按 y 分布
    out = {}
    for y in range(88):
        cnt = sum(1 for x in range(4,166,2) if is_text_color(img.pixelColor(x,y)))
        if cnt >= 2: out[y] = cnt
    return out   # 按间隙>4px 分段 → 文本带列表
# 断言: 4 个内部模块文本带 ≥3 条(标题/desc/参数) 且 bands[i][1] < bands[i+1][0] 无重叠
```
注意: 角色标签是蓝 #58a6ff (r=88 < 110), 检测脚本的"文字色"过滤条件会漏掉它 —
验证脚本判据别用"蓝色也计入", 否则误报"角色标签带缺失"(实际画了, 只是检测没算)。

## ⑧ 特征解方案进阶 — 二阶系统 + 增益调度根轨迹 + 极点配置设计器

老倪贴完整拉普拉斯分析(质量-弹簧-阻尼二阶系统) + "将这些放到标定参数里":
- **二阶特征解**: 特征方程 m·s²+(b+Kd_eff)s+(k+Kp)=0 (m/b/k 物理参数: 末端质量/
  机械阻尼/位置刚度, 画布可标定); ωₙ=√((k+Kp)/m), ζ=(b+Kd_eff)/(2√(m(k+Kp))),
  判别式 Δ=(b+Kd_eff)²−4m(k+Kp) 三分支 → 欠阻尼(共轭复根)/临界(实重根)/过阻尼(两实根)
- **增益调度根轨迹 root_locus**: STAGE_PD 5 阶段(接近 Kp2.0 Kd0.3 / 抓取 0.1 /
  抬起 0.8 / 转移 0.6 / 插入 2.0) 各算一组极点, 复平面图(PoleZeroPlot.set_data 加
  root_locus 参数) 按阶段着色× + 阶段名 + 虚线连线 → "增益调度 = 特征根在复平面跳跃"
- **FreeResponsePlot 自由响应曲线**: y(t)=e^{σt}cos(ωt) + 包络 ±e^{σt} (灰虚线),
  前馈补偿曲线 σ→σ(1+K_ff) 更快收敛 — 特征解物理含义(σ=衰减速率/ω=振荡频率)
- **PolePlacementWidget 极点配置设计器** (⚙️参数标定视图 idx==1 显示): 输入
  Ts(调节时间)/Mp(超调%)/m/b/k → ζ=-ln(Mp)/√(π²+ln²(Mp)), ωₙ=4/(ζTs) →
  Kp=mωₙ²−k, Kd_eff=2mζωₙ−b, **画布 Kd=Kd_eff/Kp** → 💾写回状态机.Kp/动作.Kd
  (遍历 z700_internal 按节点名匹配; 无内部模块画布弹 QMessageBox 提示先开前馈PD顶层)
- 验证: np.roots 核对 5 阶段极点与手算一致 + 极点配置写回后节点 params 断言

## 用户反馈节奏 (2026-08-15 连报 5 轮 UI 问题)

"背景字显示不全" → "数据字典对应上了么" → "变量是啥啊字都重叠了" → "还是重合" →
"还是重叠" — 每轮都只解决了**一个**残留绘制源。规律: **UI 布局问题一次修干净,
别挤牙膏** — 通用路径里叠加专用布局必漏残留绘制源, 直接上"完全独立绘制 + return"
一次性隔离; 验证用像素级文本带检测而不是"有字/没字"布尔。
