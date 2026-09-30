# 画布前向布局重排 + 节点右键源码定位 (2026-09-14 会话)

归属: `simulink-flow-engineering` (flow JSON / 画布工程化)。

## 1. 前向布局重排 (老倪: "不要出现右侧是输入、左侧是输出的位置" + "可以增大画布的面积")

### 触发
用户看着画布说"你怎么断连了 / 太容易看不清" → **先证明数据层没丢**, 再做几何重排。

语义 diff (备份 vs 当前, 连线集合):
```python
import json
A = json.load(open("flows/state_space_obs.json.bak_YYYYmmdd_HHMMSS"))
B = json.load(open("flows/state_space_obs.json"))
k = lambda L: (L["id"], L["f"], L["t"], L.get("f_port"), L.get("t_port"), L.get("label"))
print("丢失", len({k(x) for x in A["links"]} - {k(x) for x in B["links"]}),
      "新增", len({k(x) for x in B["links"]} - {k(x) for x in A["links"]}))
```
本次: 0 丢失 / 0 新增 (94→94)。根因 = `sslimit` 曾按老倪要求挪到原子层行首, 于是它的输入来自右边
(`sssched` x=3520) 而输出全在左边 (算子A-C/SK01-08) → 视觉上像断线。

### 工具
`tools/relayout_canvas_forward.py`
- `--measure` 只体检当前布局 (基线); `--apply` 写入并自动备份 `flows/*.bak_<ts>`
- 环境变量 `RL_PITCH` (层级间距, 默认 380) / `RL_GAP` (同行相邻间隙, 默认 170)
- 体检项: 反向线 / 方框重叠 / 贝塞尔采样交叉 / 画布范围 / 节点数·连线数零丢失

### 算法 (四要点, 三个错都踩过)
1. **体检按渲染几何**: 先自算 (JSON `w`) 得"0 反向/0 重叠", 官方 `tools/verify_l4_layout.py`
   (offscreen 真渲染) 却报 `2D→3D → 43D obs` 仍退 152px + 记忆图谱与规划器重叠 → 净空 `MIN_CLEAR=220`、
   按 `max(w,360)` 留位后才干净。**JSON 宽度 ≠ 渲染宽度 (文字撑框)。**
2. **断环按优先级**:
   - Kahn / 最长路径: 控制回路里所有环内边都成环边 (35 条) → 无效;
   - 纯 Eades FAS: 只剩 2 条, 但落在主链 `sssched→sslimit` (用户投诉那条) → 不可接受;
   - 定稿: `protected` 主链边永不当断环点; 标签含 "反馈/回流" 的边优先断 → 剩 2 条, 均为真闭环
     (`ssworld→ssinnov` 观测反馈 / `swworld→swds` 渲染回流)。
   → 结论: 闭环在左→右布局中**必然**留一条反向线; 要零反向只能 (a) 去掉线改用"回流标注" 或
   (b) 挪层级带 —— 两者都要问用户, 不要自己决定。
3. **行内稳定排序**: 按 `orig_x` 排 (只右推避让), 不要按 rank 排 —— rank 会把原子技能行顺序搞反
   (实测 `SK01` 跑到最右、`SK08` 在左)。
4. **单行扇出必然穿框**: 一个端口 → 11 个同排目标 (`sslimit → SK01-08 + 算子A-C`), 直贝塞尔必压过中间方框;
   属渲染层局限, 彻底解决要绕行布线或拆行, 先问用户。

### 零回退闸 (必跑)
```bash
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_zero_regression.py
```
断言: ①档位归属 ②L2/L3/L4 执行集逐项不变 ③连线拓扑丢失 0 / 新增 0。
本次: 55→55 / 60→60 / 77→77 · 拓扑 94 条全在 ✅。

### 实测前后 (同口径)
| 项 | 前 | 后 |
|---|---|---|
| 反向线 | 3 (含主链 1) | 2 (均为真闭环) |
| 方框重叠 | 1 对 | 0 对 |
| 贝塞尔交叉 | 166 | 174 |
| 画布 | 7320×3235 | 13106×3235 |
| `sssched→sslimit` | 反向 (ax 3800 > bx 754) | 前向 60px ✅ |

截图 (体检器每次跑自动出, CLI 无附件通道 → 报绝对路径给用户):
`reports/canvas_full_<ts>.png` · `reports/canvas_l4_l3_layout_<ts>.png`

## 2. 节点右键"打开 VSCode 源码"定位 (老倪: "DiT 的右键怎么没有进入源代码呢?")

三条路, 任一断了都表现为"没跳进源码 / 跳到 GUI 自己":
1. `params.source` (+ `params.source_symbol`) — 相对路径按**仓库根**解析。
   - 只写文件不写符号 → 打开**第 1 行** (= 用户眼里"没进源码"); DiT 节点原状 `action_head.py:1`。
   - 描述式写法 `"tools/gui/node_logic.py · node_ss_ff_hist"` / `"路径 符号"` / `"路径 --flag"`
     会让 `os.path.isfile(join(root, 整串))` 失败 → GUI `open_in_vscode` 已改为拆出路径与符号;
     且 `source` 只落到 GUI 自身 (`tools/gui/node_logic.py`) 时**让位给 registry 真实现**。
2. registry 兜底: `match_node(名字)` (最长关键词匹配) → `_EXTERNAL_LOC[key]`;
   sym 必须是真实符号名 (`class Xxx` / `def xxx`), 写描述文字会定位失败。
3. 都没有 → 只能打开工程根。

### 三件工具
- `tools/check_node_source_map.py` — 全画布体检 (走哪条路 / 文件:行 / 符号是否存在 / "落到 GUI 自身"清单)。
  基线: 可定位 60 · 不可定位 0 · 落到 GUI 自身 9 (波形·视频·3D视图·档位·训练推理开关·算子 A/B/C — 实现本就在 node_logic.py)。
- `tools/fill_node_source_symbols.py [--apply]` — 只在 registry 文件与 `params.source` **同一文件**且符号真实存在时才补符号 (宁缺勿错); 本会话补 28 个, 含 DiT → `class SmolVLALewActionHead`。
- `tools/repoint_node_sources.py [--apply]` — 把"source 指向 GUI 壳、真实现在 src/"的节点重指向:
  `SK01-08 → src/lerobot/policies/left_right/state_space/skills/atomic_skills.py:46/59/72/86/100/113/127/142`
  (该文件自带声明"画布 SK01-08 右键源码指向本文件"), `YOLO / 2D→3D / 触觉 → src/lerobot/policies/yolo_3d/{yolo_state_aligner.py, gen_tactile.py}`
  (原指向的 `tools/gui/yolo_perception.py` 150 行里根本没有这些实现)。
- 无外部实现的显示类节点 → 打开 `node_logic.py` 是正确行为, 别硬指相近源码 (否则"多个节点源码看起来一样")。
- 两处同步铁律不变: 改 `params.source` 是改 flow JSON (数据层, 重新载入即生效); 改 `_EXTERNAL_LOC` / `open_in_vscode`
  是改 GUI 代码 (要重启控制台)。

## 3. 沟通口径 (老倪: "你搞错了，别选那么多")

- 报 bug 时**不给选项菜单** — 先定位真因、拿证据 (语义 diff / 行号 / 实测数字) 再修。
- "赶快修改" = 立刻改 + 跑验证 + 报结果, 不要再追加确认问题。
- 交付前先自己跑通并留证据 (体检器输出 / 截图绝对路径 / 零回退结论), 口头结论不算。
