# INDEX — 「集成审计」新增内容 (SKILL.md 指针因写入门禁未能落, 先读本文件)

> ⚠️ 本文件是补位的索引: 2026-09-14 想把下面第 1 节写进 `SKILL.md`, 但被
> "read-before-write + skill_view dedup 不返回内容"的交互卡住 ⇒ 内容完整落在此处。
> 下次前台会话请把第 1 节并入 SKILL.md, 并按第 4 节补 `## 参考` 指针。

## 1. 「断点没进来」= 分支级取证 (最高频追问形态) — 应并入 SKILL.md

老倪的症状是**行为级的**: 「我点了运行 + 选 L4, 断点在 `return (loss*valid_mask).sum()...` **没有进来**, 查」
——追问的真身是「这段代码到底是不是每帧在跑」。**读代码猜不行, 必须给运行期计数**。三步定案:

1. **先看那行属于哪个分支**: `forward(loss)` / `compute_loss` 是**训练分支**; 推理走 `predict_action` /
   `predict_action_chunk` / `select_action`。**训练 loss 行在推理里永远不会命中**, 不管 L2/L3/L4 哪档 ——
   最常见的一类"断点不进来"。判据命令:
   ```bash
   grep -rn "class <Head>\|def forward\|def predict_action" src/**/<model>.py   # 方法清单
   grep -rn "\.forward(\|<Head>(" --include=*.py src/ tools/                   # 谁调用它
   grep -rn "policy.forward(" tools/gui/training_backend.py   # 训练模板 = loss 行唯一执行者
   ```
2. **再确认该分支在那条链上有没有被构造/调用**: 档位装配会**主动关掉**别的档的开关 (实例: L4 装配里
   `os.environ.pop("SS_L3")` → L3 模型类**根本没被实例化**; 断点不是"没进", 是"链上没有这份代码");
   直驱装配 (`install_direct_act`) 会绕过解析控制器 → 引擎自有 u_ff 槽位整条不在链上。
3. **仍不确定就上探针** (`templates/probe_runtime_callchain.py`): **函数级计数** (importlib 取类 → 裹
   `__init__/forward/predict_action`) + **行级计数** (`sys.settrace`, 只对目标文件放行局部 tracer) +
   **静态调用者清单**。必须带**正对照**: 微型对象直接调一次 `forward()` 证明打桩有效 (命中 loss 行),
   而 `predict_action()` 增量 0。

**铁律**:
- 探针必须 `CUDA_VISIBLE_DEVICES=""` 跑 (训练占着 GPU 时探针加载模型会抢显存把训练搞挂)。
- 输出同口径数字才被认 (「`action_head.py:307` 命中 0 次 · `IntactNode.step` 40/40」); 另打印"本次已执行到的
  行"证明文件真被加载执行过, 否则读者怀疑你没 import。
- **复刻 GUI 的装配路径** (同一份 `install_direct_act` / `attach_intact`), 别另写一套跑法。
- 结论必须给**可命中的替代断点位置** (实测命中的行), 不能只说"你的断点打错了"。
- 区分「模型没跑」与「跑了但被硬闸拒绝」: 槽位计数 0 有两种真因 (缺 skill_ctx / 未标定 → 模型侧抛错),
  看 `_stats.err`, 别猜。

## 2. 假接入第 8 形态 (应并入 SKILL.md 的清单)

8. **画布拓扑画了、运行期不调** (画在链上的节点在真实装配里被 `pop` 掉 / 被直驱绕过) → 运行期计数 0,
   属"画了没接"。判据同第 1 节第 2 步。

## 3. 本次证据文件

- `references/breakpoint-not-hit-branch-audit-2026-09-14.md` — 完整数字与复现命令 (Z-MAX L4 场景)。
- `references/trigger-path-audit-2026-09-14.md` — 触发路径对照表 (运行 / 双击 / E2E 各走哪条链)。
- `templates/probe_runtime_callchain.py` — 探针模板 (改 ROOT / TRACE_FILES / patch 清单即可复用)。

## 4. 待补的 SKILL.md `## 参考` 指针

```
- references/breakpoint-not-hit-branch-audit-2026-09-14.md — 「断点没进来」取证数字 (训练 loss 行 + 档位 pop 双因)。
- templates/probe_runtime_callchain.py — 运行期调用链探针 (函数级 + 行级计数)。
```
