# 画布 JSON 编辑安全 + 连线方向规整 (2026-09-10 实锤)

适用: 直接改 `flows/state_space_obs.json` (或任何 flows/*.json) 的节点/连线/坐标。
本次(整体更新状态空间节点 + 连线梳理)踩到 5 个坑, 全部可复现。

## 1. python 改 json: 局部变量赋值不会写回 (最坑)
```python
nodes, links = d['nodes'], d['links']
links = [l for l in links if ...]     # ← 只改了局部变量! d['links'] 还是旧的
json.dump(d, ...)                     # 存下去还是 92 条, 不是过滤后的 74 条
```
**症状**: 脚本打印"删除 18 条 · 连线 74", 读回文件仍是 92 条; 反复跑永远不生效。
**修**: 末尾 `d['links'] = links`(nodes 用 append/in-place 时不受影响)。
**教训**: 任何"删/过滤列表"的脚本, 存盘前断言 `len(json.load(open(P))['links']) == len(links)`。

## 2. GUI 运行中会写回整份画布 → 覆盖外部编辑
- `studio.py`(simulink_module) 的 `_save_mode_to_flow`(切档/改模式写回)、`_save_flow`(手动保存)
  都会把**内存版**整份 dump 回 `flows/state_space_obs.json`。
- 实测: 10:06:48 写完, 10:06:58(10 秒后)被 GUI 覆盖回旧版。
- **流程**: 编辑前必须停掉**全部** studio:
  ```bash
  PIDS=$(ps -eo pid,args | awk '$2 ~ /gui-venv311\/bin\/python$/ && /studio\.py/ {print $1}')
  [ -n "$PIDS" ] && kill $PIDS
  ```
  改完 → 读回校验 → 再启动 GUI(加载新版) → git commit 锁版。
- **⚠️ `pkill -f "studio.py"` 会杀掉自己**: agent 的 bash -c 命令行里含 "studio.py" 字符串 →
  pkill 自匹配 → 命令 exit -15 中断。必须用上面 `awk '$2 ~ /gui-venv311\/bin\/python$/'` 精确匹配。
- GUI 可能**多个实例并存**(实测 2 个), 只 kill 一个文件仍被另一个覆盖 → 循环 kill 到 pgrep 为空。

## 3. row_bg 与 model 节点**同名** → 按 name 子串取 id 会取错
- 例: row_bg `🔧 L2 记忆 · 肌肉记忆 (固化标杆 → 快速直通 入库)` 与 model `🔧 L2 记忆 · 肌肉记忆 (小脑 · DMP式标杆回放)`。
- `nid(sub)` 必须排除 `type == 'row_bg'`, 且多命中时报错打印候选而不是取第一个:
  ```python
  def gid(sub):
      r = [n['id'] for n in nodes if n.get('type') != 'row_bg' and sub in str(n.get('name',''))]
      return r[0] if len(r) == 1 else None      # 多命中→None, 让调用方暴露
  ```
- 同理移动节点坐标时若取到 row_bg 的 id, 坐标"改了没反应"(实测: 执行器/物理世界右移不动)。

## 4. 连线方向规整 (老倪要求: 整体左上→右下)
判据(dx = t.x−f.x, dy = t.y−f.y, y 向下为正):
- ✅ 理想: dx>30 且 dy>30 (右下)
- ✅ 可接受: |dx|≤30 且 dy>30 (垂直下) · dx>30 且 |dy|≤30 (水平→)
- ❌ 要消除: **dx<−30 且 dy>30 (左下)** — 老倪明确抱怨"数据源输出向左下连到下面节点左侧"
- ⚠️ 结构性: dy<−30 (向上输入) — L4/L3 世界模型层接收下层感知数据, 层级顺序决定, 保留并打标
- ⚠️ 反馈回路: 右→左长线(物理世界→状态校正器 等) — 保留但 label 统一加 `↩ 反馈:` 前缀

造"左下"的常见原因与修法:
- 数据源/顶层行起点 x 太大 → **把顶行左移到画布最左**(数据源 x −340) → 其全部输出变右下斜
- 中枢/汇总节点在右侧却连回左侧记忆列 → 把中枢移到左上(或把连线翻成 下行方向 中枢→记忆)
- 决策行(调制器/安全)在控制行左侧 → 右移到校正器右侧 → 3 条左下反馈变右下
- 同行右→左(预测器→流形) → 把源节点挪到目标左侧
- 冗余反向线直接删(例: 安全边界→SK01..08 八条"决策赋值", 语义由 desc 承载)

方向统计脚本(每次改完必跑):
```python
cat = {'右下':0,'垂直':0,'左下':0,'右上':0,'左上':0,'水平→':0,'水平←':0}
for l in d['links']:
    dx, dy = pos[l['t']][0]-pos[l['f']][0], pos[l['t']][1]-pos[l['f']][1]
    ...
```
本次成果: 连线 92→72 条, 反向(右→左) 30→5(剩余全是反馈并已打 ↩ 标), 左下 0。

## 5. 改完的验证清单
1. 保存后 `sleep 4~5` 再读一次, 两次结果一致才算落盘(防 GUI 覆盖)
2. `link` 端点存在性: `[(l['f'],l['t']) for l in links if l['f'] not in ids or l['t'] not in ids]` 必须空
3. json 可 `json.load` 且节点/连线数符合预期
4. 改坐标要同步扩 row_bg 宽度(本次 w 3000→6200) 和顶行 row_bg 的 x, 否则背景框不住节点

## 6. 交叉最小化重排 (2026-09-24 老倪: "太挤, 整体加宽, 连线不要有交叉, 从左向右从上向下")
工具: **`tools/relayout_canvas_v2.py`** (v1 只做右推, 不搜交叉; v2 做真搜索)
```bash
python3 tools/relayout_canvas_v2.py --measure          # 纯静态体检 (v1 的 --measure 会偷偷重排, 别信它)
python3 tools/relayout_canvas_v2.py --sweep            # 多组对照(行序×排法×层距)取最优, dry-run
python3 tools/relayout_canvas_v2.py --apply --x-mode grid --pitch 700 --gap 300 --vgap 100
```
- 算法: 断环→DAG→rank 最长路径 → 行带语义不动, **行内顺序**当搜索变量 (重心双向扫 + 相邻交换局部搜索)
  → 参数网格取最优 → repair 保证每条 DAG 边严格左→右 → kill_overlaps → vspace 纵向留白 → 写入前硬断言。
- **关键事实: 交叉数是拓扑量** — 加宽/拉间距**不改变**它。v2 实测 551→571(几何已到极限)。
  真瓶颈是"线本身": 132 条里 **53 条是传递冗余候选** (A→C 同时有 A→…→C 绕行链);
  实测删除投影: 删 10 条 → 交叉 ≈265(-45%), 删 15 条 → ≈202(-58%), 删 30 条 → ≈103(-78%)。
  单条降幅最大: 能力档位→前馈加速器(-37) · 总装记忆中枢→Feature 清单(-33) · YOLO→L4环境渲染图像源(-32)。
  **删线属语义改动 → 必须老倪点头**(判据: 绕行链是否承载同一语义, 并在 desc 注明传递路径)。
- **因果序行带重排被实测否决**: 按"数据源→L2感知→L3→L4→L2收口→执行"重排行带 → 交叉 639/649 (>571),
  因为感知层上移后到下方记忆/收口层的连边变成更长的跨层线。**保留原行序**。
- **行带归属必须只按 y 判定** (2026-09-24 新修的坑): 原按 (x,y) 包含 → 行带宽度不够时节点被判"行外",
  `grow_bands` 就不会替它扩宽 → 行带框不住节点(原始文件里已有 4 个: 动作调制器/安全执行边界 等)。
- 收尾必做 (实测会崩/会被覆盖): ①坐标**全部整型化**(非 int → QRectF TypeError → GUI Fatal Abort)
  ②跑 `--measure` + 断言 (前向违规 0 · 重叠 0 · 端点全在 · 节点落在行带内 0 例外) ③显示布局改动后
  重启 studio (`tools/gui/launch_studio.sh`, DISPLAY=:0) ④GUI 起来后 **再复读一次 JSON 指纹** 确认没被覆盖。
- 本次成果 (83 节点/132 连线/16 行带): 画布 11400×6570 → **12260×7920** (高 +20.6%, 行间距 +100px);
  违反前向 **12→0**; 方框重叠 **8→0**; 行外节点 **4→0**; 右→左剩 1 条(真反馈回路 `ssworld→ssinnov`, 已标 ↩)。
  备份 `flows/state_space_obs.json.bak_20260924_070459`; 报告 `docs/design/canvas_layout_forward_20260924.md`。

## 7. 结构重构 + 完备性 (2026-09-24 老倪 8 条指令)
工具三条, 全部幂等可复跑:
- `tools/canvas_restructure_20260924.py` — 删行带 / 移节点(按名) / 新增节点 / 补断头边 / 去重 / 硬断言
- `tools/canvas_completeness_check.py` — **完备性终检**: 孤岛 0 · 断头 ⊆ 合法终端 · 悬空 ⊆ 数据源 ·
  无节点在行带外 · L2 功能不在 L4 带 · 坐标全 int · 无重叠
- `tools/relayout_canvas_v2.py` — 加宽 + 交叉搜索 + 纵向留白 + 断环打标

本次落地: 删「🌍 L4·光模块插拔链」行带 (渲染节点 → 可视化层, 策略/引擎 → 并入 L4 专家行);
💪L2 肌肉记忆技能库 从 L4 记忆行 → L2 记忆行; 🧿 n_dsvl → DeepSeek-V4-Flash; 新增 3 真节点
(🧬阶段专家 MOE / 🎛L4 LoRA / 🎛L3 LoRA, 均在 node_logic `_reg` + `_EXTERNAL_LOC` + capability_levels 注册);
补 23 条断头/悬空边; 结果 70 节点 · 152 连线 · 15 行带 · 18899×7362 · 孤岛 0 · 违反前向 0。

**新增节点要"进得了系统"三件事 (老倪: 进不了系统的节点删掉)**: ①`_reg("<key>", [名关键词], doc, fn)`
②`_EXTERNAL_LOC["<key>"] = (真源码文件, 行, 符号)` ③`capability_levels.py` 的 funcs 里加 {fid,name,desc,groups}
—— 缺任一就是"画上去但进不了系统"。节点函数要读**磁盘实况**(ckpt 大小/mtime、报告数字), 缺就报缺, 不写死。

### 🐛 断环 (FAS) 不幂等三连坑 —— 实锤, 每个都让画布每次跑都不一样
1. **DFS 起点**: `_find_cycle` 在 `set` 上迭代 → 字符串哈希随机化 → 跨进程起点不同 → 断环集 3~6 条乱跳。
   修: `for s in sorted(ids)`。
2. **打标反噬优先级**: 用 label 文本判优先级, 而脚本自己又会给断环边加 `↩ 反馈: ` 前缀 → 下一轮优先级变了。
   修: 优先级只看**剥掉自加前缀后的**标签 + tie-break 也用剥后的长度。
3. **语义回流边必须显式声明**: `PREFERRED_BACK = {(swworld,swds), (ss_mem_share,ss_mem_l2/l3/l4)}`
   —— 否则断环会去断"策略→引擎""记忆→图谱"这类**前向**线 (前者把三节点 x 顺序拆散, 后者让图谱节点成断头)。
判幂等: 连续跑 3 次 `--measure`, 断环集与 `back_dag` 必须逐次一致。

### 🐛 links 回写 (第二次踩, 与 §1 同一坑)
`links = d["links"]` → 过滤/追加后**忘了 `d["links"] = links`** ⇒ 新边全丢、新节点成孤岛, 而脚本断言
是在内存对象上跑的所以"全绿"。修: 断言前后都写 `d["links"] = links` + `assert len(d["links"]) == len(links)`。
