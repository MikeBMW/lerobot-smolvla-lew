# 取证工具自身的完整性 (否则真执行会被印成「0 次」) — 2026-09-15 实录

审计结论的可信度 = 取证工具的可信度。本次一轮「为什么这段代码进不去」的排查里, 三类工具缺陷
连续制造了**假 0 / 假阴 / 无法归因**, 每一条都会让审计报告写反。跑任何计数型探针前先对这三条。

## 铁律 1: 行号/名称必须运行时定位, 不许写死

- 症状: `tools/probe_l4_callchain.py::micro()` 把断点行写死成 **307**; 之后源码加了 `l4_cond` 形参,
  loss 行漂到 **351** ⇒ 探针打印「forward() → loss=1.9193 · 行 307 命中 **0** 次」——读起来像
  「forward 没进」, 而「已执行行」列表里 330-351 全在 (loss 行 351 命中 1 次)。
- 修法: `_find_line(<相对路径>, "<源码片段>", <默认>)` 运行时定位 + 报告里带上实际行号
  (`forward@322 / predict_action@354 / loss 行@351`)。
- 同族坑 (更隐蔽): 一个文件里 `def forward(` 有多处 —— 全文件第一个是 **`TimestepEncoder.forward`(53)**,
  但报告把它标成「loss 分支函数入口」, 差点把结论带偏。正解: 加类锚点
  `_find_line(path, "def forward(", 322, after="class SmolVLALewActionHead")`。
- 通用: **「0 次命中」先查行号是否漂移/指错函数, 再说「代码没跑」**。反向误判 (把真执行当假接入)
  与「没跑说成跑了」同样致命。

## 铁律 2: 探针绝不许吞日志 (静默 = 无法归因)

- 症状: 探针构造引擎时写 `log=lambda *a: None` → 引擎的 `⚠️ … 推理失败 (已熔断…)` 全被吃掉。
  现象只有 `l3_calls=0`、`SmolVLALewPolicy.__init__=1`, 完全看不出为什么加载了却不执行
  (实际是加载/预处理阶段抛异常被熔断)。
- 修法: 收集 log 行 + 报告单列「告警回放」段 (原样贴 `⚠️/失败/熔断/error` 行);
  **没告警时要显式写「门控没放行, 不是静默异常」** —— 把两种\"0\"区分开。
- 与既有红线一致: 老倪零容忍\"静默降级\", 探针自己也不能静默。

## 铁律 3: 必须有正对照, 且门控参数可控

- 症状①: 探针内部写死 `os.environ["SS_L3_EVERY"] = "4"`, 命令行传 `SS_L3_EVERY=1` 被覆盖;
  跑 2~6 步时正对照 `l3_calls=0` → 看起来\"L3 档没接上\"。
- 症状②(更值得记): 同一场景 2 步/6 步两次都 0 (冷加载 334s, 引擎日志被静默), 第三次 (热加载 45.7s)
  就正常了 ⇒ 某些\"0\"是**那一轮的加载异常**, 不是稳定行为。历史轮次没有日志就**无法事后归因**, 只能重跑取证。
- 修法: 步数/频率类参数允许外部覆盖 (`os.environ.get("SS_L3_EVERY", "1")`); 每一步都跑**正对照**
  (micro 场景同进程直接调 `head.forward()` → loss 行命中 1 次, 而 `predict_action()` 增量 0), 用它证明
  打桩/门控有效, 再下\"这条链没跑\"的结论。
- **归因站不住就当场更正**: 本次一度把假阴归因为 every=4 写死, 复测 `SS_L3_EVERY=4` (6 步) 发现
  select_action 照样进 2 次 (第 0/4 步) ⇒ 归因不成立, 已在回答里显式撤回。**错归因比没有归因更坏**。

## 附: 该探针可复跑的场景 (2026-09-15 定型)

```bash
cd /home/ubuntu/lerobot-smolvla-lew
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py micro     # 正对照, 秒级 (无模型加载)
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L4 5      # INTACT 直驱: action_head.py 一行不执行
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L4line 30 # 引擎意图直连线: frames/ran/applied/manifold
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L3 6      # 625M CPU 加载, 冷/热差 7× → 用 background
```
判据与本次数字: 见 `references/canvas-edge-data-flow-audit-2026-09-15.md` 与
`references/breakpoint-not-hit-new-causes-2026-09-15.md`。
