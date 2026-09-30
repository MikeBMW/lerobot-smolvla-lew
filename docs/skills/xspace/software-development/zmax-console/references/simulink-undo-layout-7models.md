# 画布模板布局 / 撤销栈 / 输入链验证 (2026-08-07 七模型对比实战)

本次把五模型对比升级为七模型（+MLP蒸馏 +官方专家），踩坑与修复全记录。

## 1. 模板 layout 网格 — 兜底单行是"节点跑飞"根因

`load_reference_app(node_specs, link_specs, layout)`:
- specs 里**名字不在 layout 网格**的节点 → 走兜底单行 `(base_x + i*200, base_y)`，x 随 specs 索引爆炸（Interpolant 曾到 x=6620、交叉注意力 x=7920，显示区外十万八千里）。
- **铁律：新增 specs 节点必须同步 layout 行**，否则静默跑飞。
- 列距 260→200（全局常量，`base_x + c*200`、行距 230）；节点 w=150，50px 间隙够放连线标签。
- 共享节点（数据/YOLO开关/StateAdapter）出现在多行 → 取第一个未用位置，其余行占位空。
- layout 里出现 specs 没有的名字 = 无效占位（节点不创建，纯占位）。

## 2. 背景行 row_bg 与模型行错位

`_draw_model_rows(row_names, row_h=230, col_w=200, base_x=120, base_y=80, n_cols=10)`:
- 背景行从 `base_y` 首行起排：`y0 = base_y + r*row_h - 20`。
- **加一行模型 → 背景行 row_names 必须同步**（含 palette 加色），否则整体错位一行（ACT 背景盖在感知行上，AWE 行没背景）。
- `col_w/n_cols` 必须与 layout 一致（260/8 → 200/10），否则背景带超宽/覆盖错位。
- palette 每行一名一色；专家行用金色 #8f8a3d 表"真值锚点"。
- 批量添加背景行要挂 `_suspend_undo = True`（否则 8 行背景入撤销栈，Ctrl+Z 先删背景）。

## 3. 撤销栈 Ctrl+Z（2026-08-07 老倪: 挪动背景回不去上一步）

实现于 SimulinkModule + SimCanvas：
- **四类操作**：move（画布拖动结束入栈）/ 添加（add_node 自动 push del_node）/ 删除（delete_selected push restore_nodes）/ 连线（add_link push del_link）。
- **move 记录**：SimCanvas.mousePressEvent 记 `_drag_start=(id,x,y)`，mouseRelease 比较位置变化 >0.5px 才 push；恢复用 `item.setPos(ox,oy)`（itemChange 自动同步 node["x"]/["y"]）。
- **删除撤销 id 重映射（最易错）**：add_node 生成新 id，旧连线引用须重映射——**被删节点→新 id，存活节点→原 id**：`idmap.get(lk["f"], lk["f"])`（只查 idmap 不回退会丢连线）。
- **_suspend_undo 挂起**：模板加载（load_reference_app）与背景行批量添加期间挂起；读取用 `getattr(self, "_suspend_undo", False)`——**直接读属性会 AttributeError 被 except 吞掉**（画布从未加载模板时）。
- **快捷键**：`QShortcut(QKeySequence("Ctrl+Z"), canvas)` + `WidgetWithChildrenShortcut`（焦点在画布内才触发，不抢搜索框/输入框原生撤销）。
- clear() 清空撤销栈（新画布旧操作作废）；限深 50；撤销后 `_sync() + scene.update()`。
- 恢复节点/连线时也要挂 `_suspend_undo`（否则恢复操作自身入栈）。

## 4. 输入链完整性验证（防"输入空"）

老倪发现 DiT-B base VLA 输入空：VLA-Touch 路 DINOv2 视觉嵌入只连了 Interpolant，**跳过了 DiT-B base VLA**。
- 官方拓扑 π(a|s,I)：DINOv2 视觉嵌入**同时进** base VLA 与 Interpolant；base VLA 输入 = state39D + 视觉嵌入（双输入）。
- 验证脚本：AST 提取 specs + links → 计算每节点入边/出边 → 非数据源节点必须有入边。全量检查 51 节点。

## 5. PDF 图片中文乱码（matplotlib）

- 文字（reportlab）无乱码、图片（matplotlib）乱码 = matplotlib 缺中文字体。
- 修复：`_cfg_cjk()` → `matplotlib.use("Agg")` + `font_manager.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")` + `rcParams["font.sans-serif"]=["Noto Sans CJK SC",...]`。
- **必须用 .venv 的 python**（有 matplotlib；系统 python3 没有）。
- 验证：offscreen 画含中文标题的图，捕获 `Glyph ... missing` 警告（warnings.catch_warnings），0 警告 = OK；`findfont("Noto Sans CJK SC")` 确认选中。

## 6. 重启 GUI 与训练子进程（2026-08-07 实测细化，非绝对禁重启）

GUI `closeEvent` 的 pkill **只匹配固定模式**：
```python
pkill -f "lerobot.scripts.lerobot_train"   # ACT/SmolVLA/LEW 类
pkill -f "tools.cicd_pipeline"
```
**不匹配独立脚本**：`train_yolo.py` / `train_vla_touch.py` / `train_awe_zflow.py` / `distill_expert.py`——这些进程重启 GUI 时**存活**（YOLO 训练实测 36 分钟进度未被杀）。
- 重启决策：`pgrep -f 'lerobot.scripts.lerobot_train'` 有结果 → 不能重启；只有独立脚本在跑 → 可以安全重启。
- **重启后防双训练抢 GPU**：`studio.py::_auto_run_compare5`（ZMAX_AUTO_RUN=1）启动时先 `pgrep -f "train_yolo|train_vla_touch|train_awe_zflow|distill_expert|lerobot.scripts.lerobot_train"`，busy → 只 `open_compare5()` 加载画布、跳过 `start_sim()`，日志提示"跳过自动训练, 仅加载画布"。这个保护应常驻（防多训练打架）。
- 撤销/布局修复等"代码已加载在内存"的 GUI 改动，只有重启进程才生效；刷新画布（重新 open_compare5）加载的是内存旧常量，无效。

## 7. 连线视觉遮挡 → 端口垂直分布（2026-08-07 LeWorldModel"输入空"真因）

老倪报"LeWorldModel 输入空"——**拓扑有输入**（数据→LEW 视频+动作），但**视觉上看不见线**：
- 根因 A：数据源 9 条出线全从同一 out1 端口点 `(w, h/2)` 出发 → 线束完全重叠只剩最上一条。
- 根因 B：SimLinkItem z=5 < 节点 z=10 → 长线（跨 3+ 模型行）被中间节点盖住。
- 修复（纯绘制层，不动拓扑）：
  1. `_draw_links` 预计算每节点出/入线数，逐 link 写入 `lk["_fo"]/_no/_ti/_mi`（出线序号/总数、入线序号/总数）。
  2. `SimLinkItem._path` 端口 y = `src.h*(fo+1)/(no+1)`（dst 同，`_ti/_mi`）；switch 节点保持固定双端口不分布。箭头 by 同步。
  3. `SimNodeItem.paint` 非 switch 节点按 `n_in/n_out` 画 n 个端口点（同公式分布）；0 线保持中间单端口（拖线交互不变）。
- 验证：offscreen 实例化 → add_node+add_link → 断言 `_fo/_no` 字段 + `_path().elementAt(0).y` 等距互不重叠（注意期望值要加场景 y 偏移，节点 y=100 时起点=112.5/125/137.5）。

## 8. 验证方法论（本次实战）

- **布局静态验证**：AST/正则提取模板 specs+layout → 重放 load_reference_app 分配逻辑 → 断言零兜底 + 列对齐（ActionHead 列7、训练/基准列9）。不启动 GUI。
- **撤销运行时验证**：`QT_QPA_PLATFORM=offscreen` + QApplication + 实例化 SimulinkModule → 真实调用 add_node/delete_selected/undo 断言状态。注意 links 段边界：specs 结束 `], [` → layout 注释前（`seg.rindex("], [")` 会与 index 撞同一位置导致 links 段为空）。
- 七模型对齐约定：列3=输入编码/主干、列7=Action Head、列9=训练/基准（全部模型行对齐）。

## 9. 数据源节点双击 → 属性信息框（2026-08-07 老倪）

on_node_activated 的 `params.get("source")` 分支从"纯切换"改为 `_show_source_info(node)`：
- 非模态 QDialog（WindowStaysOnTopHint + _show_nonmodal，WSLg 安全），每候选数据目录一个白底卡片：
  实际路径（绝对路径加粗蓝色）+ `_probe_dataset(dp)` 属性（info.json 的 total_frames/episodes/
  features 维度/fps + episodes 目录数 + mp4/npz 计数 + 大小 MB）。
- 未激活节点给「🔀 切换为激活数据源」按钮（调 _toggle_source 保留原能力）。
- 候选目录：metaworld→data/metaworld_act,mt50,peg；orin→orin_live,real_v1,archive,closed_loop。
- 验证：offscreen 实例化调 `_probe_dataset` 断言 dict 键；注意相对路径在 offscreen cwd=tools/gui
  下会探测空——真实调用走 `os.path.join(self._repo_root(), p)` 绝对路径。

## 10. outputs/train 磁盘清理规则（139G→39G 实测）

- **训练中目录绝不碰**（smolvla_peg_v7 12+ ckpt 持续增长，验证脚本按固定数断言会误报"失败"）。
- 每目录只留最后 checkpoint（load_policy 用 glob 取最新，中间无人用；多 ckpt 目录 7→1 释放 ~18G/3目录）。
- 删旧日期试训目录（`^(act|smolvla|smolvla_lew)_2026080[456]_` 时间戳目录 110 个 ≈ 81G）；
  保留命名目录（act_metaworld_final 等，GUI 基础模型引用）与 07 链最终目录。
- 清理后验证：GUI 引用目录在、曲线/报告/视频产物在、训练进程存活、磁盘 % 下降。
