# 画布 JSON 编辑安全 + 连线方向规整 (2026-09-10, 老倪: "不整洁 / 整体连线从左上到右下")

实例: flows/state_space_obs.json (状态空间主画布, 69 节点 / 连线 92→74)。
背景: 一次"整体更新状态空间节点 + 梳理连线"任务里连踩三个坑, 每个都表现为"改了没生效"。

## 一、⚠️ 最大坑: GUI 在跑时改画布会被整份覆盖

- **机制**: studio.py 的 `_save_mode_to_flow`(切档/切模式写回) 会把**内存里那份画布** dump 回
  flows/state_space_obs.json。此时你在磁盘上改的节点/连线 10 秒内被打回 —
  实测: 脚本写入 74 条连线, 立刻读回 92 条; 反复出现"删掉的连线又回来了",
  误判为"自己去重没生效"。
- **判定**: `ls -la --time-style=full-iso flows/*.json` 看 mtime 是否在你写入之后被刷新;
  `ps -eo pid,lstart,args | grep studio.py` 确认 GUI 在跑。
- **正解 = 停 GUI → 改 → 重启 → 校验稳定(隔几秒再读一次)**:
  ```bash
  PIDS=$(ps -eo pid,args | awk '$2 ~ /gui-venv311\/bin\/python$/ && /studio\.py/ {print $1}')
  echo "GUI PIDs: $PIDS"; [ -n "$PIDS" ] && kill $PIDS; sleep 3
  ps -eo pid,args | awk '$2 ~ /gui-venv311\/bin\/python$/ && /studio\.py/ {print "残留:", $1}'
  ```
  - awk 按**第 2 字段 = python 可执行文件路径**匹配, 不匹配 bash 自身命令行 —
    比 `pkill -f "studio.py"`(会打到自己的 bash, exit -15)更稳, 也比 `[s]tudio.py` 直白。
  - **常有两个 studio 实例**(旧进程残留 / 叠窗), 必须全停; 停完 pgrep 复验,
    否则第二个实例照样把你写回。
  - 重启用绝对路径: `cd <repo> && DISPLAY=:0 <repo>/gui-venv311/bin/python tools/gui/studio.py`
    (后台启动; 相对路径启动会让 venv 失效)。

## 二、脚本改 JSON 必须写回容器键 (静默失效坑)

```python
nodes, links = d["nodes"], d["links"]
links = [l for l in links if not drop(l)]   # ← 只重绑局部变量!
json.dump(d, open(P, "w"))                  # d["links"] 仍是旧列表 → 删除全部丢失
```
- 修: `d["links"] = links` 后再 dump; 节点删除同理。
- 收尾三件套: ①幂等(同脚本可重复跑) ②读回断言(`len(json.load(...)["links"]) == 预期`)
  ③打印前后统计 + 异常清单。
- 想验证"到底改到哪去了": 写一个只读体检脚本, 逐条 link 算 dx/dy 分类并打印,
  别靠肉眼看 JSON。

## 三、连线方向规整 (老倪偏好, 布局类改动按此做)

判定: 对每条 link, dx = t.x - f.x, dy = t.y - f.y → 分类
右下✓(dx>30,dy>30) / 垂直下(|dx|≤30,dy>30) / **左下✗**(dx<-30,dy>30) /
右上(上行) / **左上✗** / 水平→ / 水平←。目标: 左下 = 0, 水平← ≈ 0, 上行只留"下层供上层计算"。

手法 (按收益排序):
1. **数据源行放画布最左上** (x 取最小) → 其全部 fan-out 自动变右下斜 (原来与下方左列节点
   同 x = 一排垂直长线, 视觉"往下灌")。
2. **记忆列在左时, 中枢也放左上**: 中枢原在 x2360(最右) → "中枢→L2/L3/L4 记忆" 三条横穿
   全画布成反向。把它移到最左后同样三条线全变右下。
3. **执行/物理/观察层整体右移**: SK 技能行在 x1420-2645, 执行器原在 x2100(夹在中间) →
   SK05-08→执行器 反向; 执行器→2900 / 物理世界→3250 后全正向, 观察层(3D/波形/视频/
   Feature/Test/直方图)再排到 3600-5500 便都是右下。
4. **决策行右移到上游右侧** (调制器/安全边界移到校正器 x 右侧) → 3 条"反馈→调制器"左下
   变右下。
5. **删除语义冗余/重复线**: 安全边界→SK01..08 这类"决策赋值"线删掉(输出语义已在安全→执行);
   元层(标定层/潜空-流形)的入线全删(元层由 desc 说明, 别画 4 条反向线);
   去重按 (f, t, label)。
6. **保留的反馈线必须打标**: label 前缀 `↩ 反馈: z_k 观测 / contact+残差 / 恢复建议 / 质量门`。
   反馈允许反向, 但必须一眼可辨是反馈而不是乱连; 上行输入线标 `⬆`。
7. 行背景宽度: 节点右移到 x≈5500 后 row_bg `w` 同步加宽(3000→6100), 否则末段节点在背景外。

## 四、新增画布节点三件套 (真源在 src, 老倪红线)

1. **src 真源**: 节点实现写进 `src/lerobot/memory/mem_nodes.py`(记忆族)等框架层文件,
   GUI 只薄注册转发; 函数签名 `fn(ctx)`(`ctx["log"]` / `ctx["module"]`), 真实读数据,
   无数据时返回 False + 明确 reason, 不伪造。
2. **node_logic 注册**: `_reg("<key>", ["<节点名关键词>"], "<一句话说明>", fn)` +
   在 `from lerobot.memory.mem_nodes import (...)` 里加导入 + except 兜底 lambda。
   关键词是 name 的子串匹配 → 节点名写全("🧠 意图丛 · 四槽语法" ← "意图丛")。
3. **画布 JSON 节点**: `{"id": "n_xxx", "type": "model", "name": "...", "x":…, "y":…,
   "w": 270, "h": 68, "icon": "🧠", "color": "#a371f7",
   "params": {"state_space": true, "desc": "...", "source": "src/lerobot/memory/mem_nodes.py · fn"}}`
   `params.source` 指 src 文件 → 右键/双击源码映射可到真实文件;
   新增节点后按第三节把它的入/出线接到已在链路里的节点(别留孤立节点)。
4. 验证: ①`NODE_LOGIC` 里 key 数/新 key 存在 ②每个新 fn 用假 ctx(`{"log": print}`)真跑一次
   看输出 ③画布 JSON 合法 + 无悬空 link(端点 id 必须都在 nodes 里)。
5. 记忆类新节点实例(2026-09-10 落地): 🧠 意图丛·四槽语法 / 🧬 技能词典·L2 动作基 /
   🔗 跨层连接·记忆图谱 / 🔮 意图直读·Direct — 真源 memory_graph.py(links / recall /
   skill_dict / intent_direct)。
