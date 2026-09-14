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
