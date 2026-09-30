# 记忆拓扑 + 工程记忆→总装同步 (2026-09-19 v5.8.0) — 我这边 ↔ 飞书端 商量稿

> 老倪: 「先修改大模型层的连线问题…环境数据要输入给技能编排层的大语言模型…其它节点怎么都是悬浮在那呢?
> 要设计好连接拓扑关系。然后同步飞书的任务, 飞书正在优化多层记忆架构。同步后, 中版本迭代, 保存数据, 技能。
> **跟飞书端商量好, 当前的工程记忆, 要同步到大模型层的总装记忆节点**」

## 一、我这边的落位 (已实现, 已验收)

### 1) 画布拓扑 (大模型层 + 记忆/意图层, 悬空节点清零)
- 新增节点 `n_eng_mem` = **📚 工程记忆 · 技能与经验库** (大模型层), 连线进 🧠总装记忆中枢 `[in5]`
- 新增 **31 条连线** (`tools/gui/gen_llm_layer_topology.py`, 幂等):
  | 组 | 边 | 含义 |
  |---|---|---|
  | 环境 → 大模型层 | ssdata→ssskill `[in1]` · ssz700→ssskill `[in2]` | **环境数据入技能编排器** (老倪点名要的) |
  | 现场 → 推理 | ssobs→ssreason `[in2]` · sslimit→ssreason `[in3]` | 状态/安全否决计数 → 异常归因 |
  | 推理 → 上层 | ssreason→ssskill `[in3]` · ssreason→ssllm `[in4]` | 异常归因 → 技能修正/重规划 |
  | **工程记忆 → 总装** | n_eng_mem→ss_mem_share `[in5]` · ss_mem_l2/l3/l4→ss_mem_share · n_mem_links→ss_mem_share | 三层记忆 + 图谱 + 工程记忆 → 总装 (`in1..in5` 五路入线) |
  | 图谱/意图/词典 | ss_mem_l2/l3/l4→n_mem_links · ssskill→n_skill_dict · n_skill_dict→sssched · ssintact_dec→n_intent_direct · n_intent_direct→sssched · ssllm→n_intent_bundle · n_intent_bundle→ssintact_dec | 原**全悬空**的 4 个节点全部接上真实读写 (memory_graph / decoder) |
  | 数据源·档位·标定 | ssdata→ssmode→sscap→{ssintact, ssvlm, ssff} · ss2d3d↔sscalib · sscalib→sslat · ssvlm→sslat · sslat→{ssmani_exp, ssdec} | 数据源→模式→档位分发; 标定层与 2D→3D/潜空间互喂 |
- 复查: 悬空(无进无出) = **0**; 仅两个**源节点**无入线 (📦 metaworld 数据源, 📚 工程记忆 — 本身就是源头)

### 2) 画布布局: 按数据流层级定列 (右→左清零, 只留真双向)
- `tools/gui/gen_ss_obs_layout2.py`: DFS 切反馈边 → DAG 最长路分层 → **x = 层级** (所有非双向边必然向右);
  y 按语义行 (数据源→大模型层→L4→L3→L2 感知/融合/控制/决策/原子技能/执行→验证→可视化); 行高自适应
- 三版对比 (官方工具 `verify_l4_layout.py` 同一把尺): 右→左连线 **基线 7 → 首版 40 → 现在 13**,
  且 13 条**全部是真双向关系** (记忆上报/下发 · 编排器↔规划器 · 校正器→状态机 等), 由脚本自动标 `↩`;
  方框重叠 0 · 连线穿框 47→25 · 交叉 208→202; 零回退 ✅ (档位归属无变化 / L2 57 / L3 62 / L4 79 / 连线丢失 0)
- ⚠️ 坑 (已入技能): `verify_l4_zero_regression.py` 按**行背景名里有没有 L2/L3/L4** 推断档位归属,
  行背景改名会被判"档位回退" → L 档行名一律保留 L 标记

### 3) 环境输入真接上 (不是画线了事)
- `node_ss_skill` 新增 `_skill_spec_from_env()`: 把 ①实时帧来源+帧龄 (真机 D405 旁路帧 / metaworld 渲染帧)
  ②场景理解结果 (SceneVLM describe) ③顶层宏观记忆下行建议 汇成规格文本 → `SkillComposer.compose()`
- 缺哪一路**如实打印** (实测无 VLM 时打印「环境帧不可用; 场景理解未就绪」, 但仍把宏观记忆建议注入了编排)
- `node_ss_llm` 同款: 规划前打印「规划上下文: 场景/总装条目」, 取不到就写「仅用指令文本」

### 4) **工程记忆 → 总装记忆节点** (老倪这次的核心要求)
- 新模块 **`src/lerobot/memory/eng_memory.py`** (`class EngMemory: collect() / sync_to_macro() / summary()`)
- 真读三类文件: `docs/memory/*.md` (跨端同步记忆 **59 篇**) + `~/.hermes/memories/*.md` (Hermes 记忆 **2 个**)
  + `~/.hermes/skills/**/SKILL.md` (技能库 **163 条** / 小节 1581) → 共 **224 文件 · 997 记忆条目(§) · 1581 技能小节**
- 落点 = 顶层宏观记忆 `data/macro_memory.json` 的 **`engineering` 段** (飞书端 09-19 新建的 macro_memory.py):
  - **追加式**: 只新增 `engineering` 键, **不碰** `knowledge / capability / diagnosis / advice / seen / meta` (已回读验证)
  - **幂等**: (路径+大小+mtime) 指纹 → 内容没变就跳过 (实测第二次运行「内容未变(幂等跳过)」)
  - **原子写 + 回读**: `tmp` + `os.replace` → 再读回比对指纹才报 ok
  - **诚实**: 无 `SS_MACRO_LLM_URL` 时 `llm=false`, 明确标注"只做结构化同步, 未做语义归纳"

## 二、请飞书端确认/接手的三件事 (商量)

1. **消费 `engineering` 段**: 你们的 `downlink()/advice` 里请把工程记忆纳入下行建议
   (例如"该阶段历史上踩过哪些坑/有哪些既定技能可用"), 数据现成在 `store["engineering"]["files"]` /
   `counts` / `newest`; 需要整篇内容再读文件即可 (我只写了清单+指纹, 没搬正文, 避免双份真相)。
2. **总装记忆节点 (ss_mem_share) 的 fusion**: 你们的 `node_ss_mem_share` 现在读三层记忆 store 汇总;
   建议加一行把 `engineering` 的 counts 也汇总进去 (我这边不动你们的 mem_nodes.py, 避免抢改)。
   node desc 我已写成五路入线口径 `in1..in5` (L2/L3/L4/图谱/工程记忆), 与代码对应。
3. **LLM 端点**: 顶层宏观记忆要把"记忆"变成"知识"需要 `SS_MACRO_LLM_URL` (OpenAI 兼容) —
   老倪说需要 key 会给我。我这边本地 VLM 已就位 (Qwen2.5-VL-3B, 无需 key), 但**宏观层是文本 LLM**,
   等你确认走哪个端点 (本机 vLLM / 4090 机 / API key) 我再打开 `llm=true`。

## 三、验收证据 (可复跑)
- 拓扑+环境输入+工程记忆同步: `/tmp/hermes-verify-llm-topology.py` → 四条全绿
- 画布零回退: `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_zero_regression.py` → ✅
- 布局度量: `... tools/verify_l4_layout.py` → 右→左 13 (全 ↩ 双向) / 重叠 0 / 穿框 25 / 交叉 202
- 工程记忆单独跑: `gui-venv311/bin/python src/lerobot/memory/eng_memory.py --sync`

## 四、第二轮全局整合 (2026-09-19 早, 老倪: 整合全局数据通路 + INTACT 桥接真连线 + LLM 视觉)
- **INTACT 意图解码器补输入** (原来只有 [INTACT策略, 意图丛] → 现 6 路): + 数据源真帧 224²+39D · 真机帧+位姿 ·
  VLM 潜空间 z · 视觉语义条件
- **新增节点 👁 视觉语言大模型 (Qwen2.5-VL / Qwen3-VL)**: 输入 环境帧(metaworld) / 引擎真图 / 真机帧;
  输出 → 任务规划器 · 异常推理器 · 技能编排器 · INTACT 意图解码器 · 总装记忆 (LLM 真"看到"场景)
  (源码 `scene_vlm.py`; 本地 Qwen2.5-VL-3B 无 key, `SS_VLM_MODEL` 可换 Qwen3-VL, 或 `SS_VLM_URL+KEY` 走 API)
- **L4 演示链 ↔ 主流程桥接真连线**: 数据源→环境渲染 · L4策略→演示链策略(同一契约) · 同一 Z-MAX 物理引擎 ·
  演示渲染视频→操作视频 · 档位→演示链 · YOLO 目标清单→渲染标注 (原来演示链只有内部闭环, 桥接是"口头结论"没有边表达)
- 可视化/验证支路补来源: 3D框→3D视图 · 前馈激活→直方图 · 调度→旁路可视化 · 43D→仿真波形 · 执行结果→用例执行 · 总装记忆→功能清单
- 结果: 81 节点 / 156 连线 · **孤立节点 0** · INTACT 相关节点全部有真实读写 (无需删节点)
- ⚠️ 代价: 反向(右→左)连线 13 → **20 条, 全部是真闭环** (记忆上报4 · 层间反馈5 · 视觉↔世界回路3 · 桥接/零搜索8)。
  闭环系统整合度越高回路越多 —— 这是结构事实, 已全部标 ↩。
- 口径提议 (接前面第②条): `verify_l4_zero_regression.py` 把 cap-0 (回路外) 新增节点算进 L2/L3 执行集 → 判 ❌。
  建议按你们 tool 的 docstring 精神 ("L4 只允许增加") 把**回路外新增节点**同等放行; 我这边保持不动你们工具。
