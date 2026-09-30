# 直方图 UI v3.2-v3.4 迭代教训 (2026-09-05, 老倪连发: "字体重叠"→"怎么变曲线"→"三层一样?"→"整体分布没变化?")

承接 qt-paint-crash-silent-blank-2026-09-05 (v3 三坑: QFont float 整窗空白 / QLabel 拉伸 / cv2 xcb 污染)。
本文件 = 同日下午四轮用户反馈后的修正与语义实测。涉及 ff_hist_view.py / ff_attrib_view.py / simulink_module.py。

## 坑 5: 192DPI 文字重叠根治 = 矩形 wrap + 流式行距 (不是缩字号)
- v3.1 已用 fontMetrics 流式累加仍重叠 → 流式累加只在"每段一行、宽度放得下"时成立。
- **终极方案 (v3.4, 结构上零重叠)**: 每段文字画在矩形里自动换行:
  `h = fm.boundingRect(QRect(0,0,w,2000), Qt.TextWordWrap, text).height()` →
  `p.drawText(QRect(x, yy, w, h), Qt.TextWordWrap, text)` → `yy += h + gap`。
  状态条/每行标题/轴标/左列全走它 — 任何 DPI/文字长度/窗口宽度不重叠不截断。
- **坐标必须 int**: drawText 传 float y → TypeError (v3.2 实测, 又被 try 吞成"绘图异常" 0.001)。
  流式 yy 从 `int(y0)+6` 起, 每处 `int(yy+fh)`。
- **验证双 DPI**: `QT_FONT_DPI=192` 与默认各渲染一次, 内容比都 ≥0.1 才算过 (offscreen 96DPI 通过 ≠ 真机 192 不重叠)。
- 用户流程教训: 一轮"字号调小"→"太小看不到", 一轮"字号调大固定行距"→"重叠" — 别再在字号上反复,
  直接上 wrap 布局一次到位。

## 坑 6: 直方图画成波形 = 误导 (老倪: "不是直方图么?怎么变成曲线了?")
- 最近一帧叠加**禁用连线折线** (视觉=波形); 改**亮点列** (每 bin 中心 5×5 方块, 无连线)。
- **0 值巨柱压扁非零分布**: ReLU 输出 ~50% 为 0 → 0 值占第一个 bin 顶天巨柱, 其余柱矮到看不见。
  修: 直方图只统计非零 (`pos = buf[buf>0]`), 0 占比(休眠率)作数字放标题/左列; x=0 虚线标左缘提示截断。

## 坑 7: 窗口单例悬垂 deleted (老倪报错 "wrapped C/C++ object of type FFHistView has been deleted")
- 用户关窗 → Qt 删 C++ 对象 → module._ff_hist_win wrapper 悬垂 (非 None) → 再双击/桥/播放 push → RuntimeError。
- 修: 统一 `_viz_win(kind)` helper (sip.isdeleted → 置 None); _open_viz_node / _ff_bridge_tick /
  _ss_tick push 三处访问全经它 (None 自动重建)。Scope 的 _ss_scope_wins 登记列表同样过滤 isdeleted。

## 长函数变量遮蔽 (Scope 阈值线崩第 8 格, 同批修复)
- Scope _paint 内层阈值线 `_tv = float(opt["thr"])*1000` 把外层时间数组 `_tv` 覆盖成 float →
  下一个 ins 格 `len(_t)` 抛 "object of type 'float' has no len" → 整窗 0.001。
- 教训: 内层局部变量别复用外层数组名 (用 `_thr_v`); paint 长函数命名前缀化。

## 图形语义: 用户问 "这是啥/为什么一样/为什么没变化" → 先实测统计再答, 再让差异可见
- **"三层怎么一样?"**: 蒸馏 MLP 三层都是 512 输出 (39D 是**输入**不是层)。ReLU 网络三层分布形状天然相似
  (0 占比 50/54/49%, 非零均值 0.26/0.21/0.28) — 实测 60 帧层间数值 0 帧相同、corr≈0 = 不是复制 bug。
  答用户前先跑探针 (层间 allclose/相关/分桶统计) 拿数字, 别空答"应该不同"。
- **"整体分布好像没变化?"**: 不是没变, 是 **150 帧累积窗口把阶段变化平均掉了** + 动态归一
  (vmax=percentile) 把强弱阶段拉成同形状。实测按 d 分桶: 非零均值 远 0.51→中 0.24→近 0.21 (差 2.5 倍);
  层2 帧间 0 占比波动 **±12pp**; 活跃单元远/近重合 Jaccard 0.71-0.77 (~30% 换人)。
  修: 每层标题两行 = 行1 累积统计 (稳定基线) + 行2 "本帧: 0占比/非零均值/能量 ← 随阶段跳变"
  (单帧算, 播放时数字明显跳动)。数字统计比形状更能暴露差异。
- 铁律: 任何"静态/没变化"观感先怀疑显示聚合抹掉了变化, 分阶段/分帧实测后再改可视化。
