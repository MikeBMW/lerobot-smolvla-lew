# 前馈探针可视化数据链 + capability_levels 三级清单 (2026-09-08)

## 🧠 前馈激活探针数据链 (直方图/归因/Scope 光标) — commits 2c2a508e→c3886b16→f33705ee
- **数据源**: accel.probe — mlp_ff_forward 的 `_ff(obs)` 每次前向填 act_raw(3×512 激活)/
  layers/out_contrib/u_ff/obs/_seq (src/lerobot/policies/left_right/state_space/parallel.py;
  输入 o[:39] 内部按 sm/ss 归一化; 零方差通道置 0)。
- **GUI 链路**: 双击 hist/attrib 节点 → simulink_module `_open_viz_node` → 若
  `_ss_tr.probe_seq`>5 帧则灌全程 (`win.push` 逐帧, L9348); probe 桥 QTimer 300ms
  (`_ff_bridge_tick`) 推 `sim.accel.probe` 给已开窗 (按 _seq 去重); 播放 tick
  (L11200-11205) 逐帧推 `probe_seq[idx]`。轨迹存 `_ss_tr` (真实化 L10948 / 简化引擎
  L11061), 引擎引用 `_ss_last_sim`。**窗口 push 按 _seq 去重 → 推入帧 _seq 必须严格递增**。

### ⚠️ 坑1 — 闭包 dict (探针写不进)
`mlp_ff_forward(npz, probe)` 返回的 `_ff` 闭包**绑定 __init__ 时传入的那个 probe dict**。
重赋值 `accel.probe = {}` 只是换了实例属性引用, `_ff` 仍写旧 dict → 新 dict 恒空。
修: 保留同一 dict 对象 (要清就 `.clear()`; 但见坑2)。

### ⚠️ 坑2 — _seq 去重 (08-22 老倪复测"还是没有数据"实锤)
FFHistView.push 去重逻辑 `if sq > 0 and self._last_seq > 0 and sq <= self._last_seq: return`
→ probe._seq 必须严格递增。`probe.clear()` 把 _seq 也清了 → 每帧 `_seq=1` → 灌全程
343 帧被丢弃 342 帧, 窗口只剩 1 帧 = 看起来"没数据"。
修: 诊断前向**勿 clear** — `_ff` 覆盖全部 key (act_raw/layers/out_contrib/u_ff/obs) 且
`_seq = get+1` 自增, 保留旧值即递增。
验证法: `probe_seq` 每帧 `_seq` 严格递增 (1..343) 才算合格。

### ⚠️ 坑3 — sim_real 探针恒空 (直方图无数据根因)
真实化引擎主路径=解析伺服 (09-06 决策: 布局域外 MLP 输出反向, seed100 固定布局在训练
分布边缘) → `accel.forward` 被换成 `analytic_forward`, MLP 不执行 → probe 空 →
tr probe_seq 0 帧 → 直方图/归因无数据。**简化引擎 ⚡快演走 MLP, 一直有数据** —
所以只有真实化 ▶运行 是空的。
修: 引擎每步补一次真 MLP 前向 `_acc._ff(np.asarray(obs[:39], np.float32))` **仅填探针、
不参与控制** (u_ff 仍是解析值), probe_seq 逐帧真实激活。node_ss_s2 (画布单步/右键
⚡前馈节点, 域外走解析守卫) 同样补一次诊断前向。

## 🎯 FFAttribView 归因·分工窗 (老倪"都是一个样子"实锤 → f33705ee)
- 上半归因堆叠: 每帧 4 色柱 = 该帧 512 隐单元对 dx/dy/dz/gripper 的驱动能量
  `contrib_d = Σ_j|W3[d,j]·x3[j]|`, 随播放长柱, 顶部"当前主导"文本更新。
- 下半散点: 512 单元, 颜色 = `argmax|W3[:,j]|` **静态分工** (训练完固定, 不该变);
  位置 = PCA/t-SNE 投影 (150 帧激活 profile 相似度 → 功能分群); 点大 = 平均活跃。
- 缺陷: PCA 只在 `len(x3_buf)==10` (最早 10 帧) 算一次, x3_buf 滚动后永不重算 →
  播放到插入段散点仍是接近段的投影, 完全静止。
- 修: push 里 `elif pts2d is not None and not use_tsne: _npush+=1; if _npush%20==0: _project("pca")`
  (每 20 帧用当前 150 帧窗滚动重算, 512×150 SVD ~50ms 可接受) + `_draw_scatter` 画
  当前帧 top8 活跃单元白圈 (`np.argsort(x3_buf[-1])[-8:]`), 播放时跳动可见。

## 📊 StateSpaceScopeDialog 时间轴光标 (老倪: 播放时感知当前时间位置 → fc73e1bf)
- 原实现 (09-05) 只"画到播放光标"= 波形前缀增长, 无醒目当前时间指示。
- 改: 通用格 (距离/前馈/残差/接触/流形 前 6 格) 传**全量信号** (`plots` 不再 `[:_k]`),
  格内 x 轴 `t0/t1` = 全量全程 → 已播段 `[0:_kk]` 亮色实线 + 未播段 `[_kk:]` 暗色虚线
  (`QColor(color)` setAlpha(90) + DashLine) + 播放头竖线 `#00d4aa` 2px 在
  `X(_t[min(_kk, len(_t)-1)])` + "t=xx s" 标签。
- 插深/错位放大格 (0.5s 验收窗, `opt["ins"]`) 保留局部窗逻辑不变; 空信号格 (真实化无
  mani_*) 保留"该轨迹未采集此信号"提示 — 分支里**勿 continue 吞掉提示**。
- 验证: 离屏 `QWidget.grab()` 渲染多播放位置不崩 (DISPLAY=:0 + gui-venv311)。

## 📋 三级能力清单 capability_levels.py (L2/L3/L4 + 测试映射) — 09-08 侦查, **未完成待续**
- `src/lerobot/verification/capability_levels.py` (07:40 建):
  `CAPABILITY_LEVELS` dict {L2: 基础辅助 9 功能 (L2-A01 目标检测…L2-A09 物理执行) /
  L3: "高级 NOA" 3 功能 (L3-B01..03) / L4: "专家城区 NOA" 7 功能 (L4-C01..07)};
  每功能 `funcs[].groups` = verification_layer 方法名前缀 (regex `t_<g>($|_)` 匹配);
  `resolve_tests(level)` 展开 → L2 161 / L3 54 / L4 82 个真实断言方法 (纯方法名存在性,
  非执行)。CLI: 直接跑该文件打印; 单用例 `ZMAX_VERIF_ONLY=F-xx`。
- verification_layer.py: FEATURES 45 项 (F-A01..F-G10; 域 A 引擎/B 六层/C 感知/D 大模型/
  E 标定流形/F 画布/G GUI 手动); FEATURE_META (fid → (基本功能|泛化功能, 角色, spec))
  并行 dict **在 main() 前** (勿插 FEATURES 后错位行号锚点)。断言模板 `t_xxx(self, np)`
  return (bool, msg); 引擎域 `self.engine()` = 简化引擎 StateSpaceSim 缓存单跑。
- **注意**: 现有 `t_aoi_*` 13 个测的是 `yolo_3d/quality_check.py` AOIQualityChecker
  (业务 SCN-03 图像质检), **不是引擎 AOI 检测闭环** (13 段 full 链)。
- **待办 (下次会话续做)**:
  ① 命名 "高级 NOA/专家城区" 未对齐画布行名 "🚀 L3 高级自动功能 / 🏆 L4 专家自主功能"
     (capability_levels 06:40 早于画布 07:09 重排; 老倪此前要求同步到 capability_levels.py/docs)
  ② L2 状态机仍写 8 段/旧摘要, 未含 13 段 拔出/AOI转移/AOI检测/回程/放下 与 AOI 工位;
     L3 缺 VLM 通用视觉编码 + Flow-Matching DiT action 双通路 (直通执行端/肌肉记忆) +
     AOI 设备识别 条目
  ③ 13 段 full 链/AOI 引擎报告**无对应 t_ 测试** — 需新增 (参考模板: 跑
     `RealStateSpaceSim(seed=104, vision=False, mode="full")` ~1-2s 可自动) +
     FEATURES/FEATURE_META 条目 + capability funcs.groups 挂 "chain" 组
  ④ docs/capability_levels_L2L3L4.md 与 docs/state_space_feature_list.md 同步命名
- 关联: 画布三级行 (flow.json row_bg): 🏆L4 专家自主·标定 / 🏆L4 专家自主·世界模型(流形) /
  🚀L3 高级自动·端到端 (VLM+DiT) / 🔧L2 基础辅助 六行 (检测/融合/控制/状态机/技能/执行)。

## 通用调试法 (本批问题均适用)
- GUI 可视化"没数据"三步查: ①数据源是否产生 (CLI 跑引擎查 tr key/probe) ②GUI 是否消费
  (灌全程/桥/播放 tick 谁推) ③窗口去重/时序是否吞帧 (_seq 递增)。
- 改 GUI 代码必重启 studio.py; 离屏验证用 `QWidget.grab()` 存 PNG (DISPLAY=:0)。
