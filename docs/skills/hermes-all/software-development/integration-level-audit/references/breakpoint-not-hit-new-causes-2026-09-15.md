# 「断点进不去」再取证 — 新增 3 类根因 + 探针行号铁律 (2026-09-15 实录)

背景: 2026-09-14 已用探针坐实过一次 (见 `references/breakpoint-not-hit-branch-audit-2026-09-14.md`:
训练 loss 行 + L4 档 pop 掉 SS_L3)。**09-15 老倪就同一处断点又问了一遍**
(「单步运行, 为什么这个代码进不去?」), 说明只给"这一处的原因"不够 —— 要能当场给出**通用诊断树**。
本轮新增 3 类更通用的根因, 以及一条会**把真执行误判成假接入**的探针 bug。

## 通用诊断树 (先跑探针, 再逐条对)

0. **先取证再解释**: 跑 `tools/probe_l4_callchain.py <场景> <步数>` 拿函数级+行级计数,
   不要读代码猜"应该会进"。
1. **这条链上没有这份代码**: 档位装配主动 `os.environ.pop("SS_L3")` + `install_direct_act` 直驱
   ⇒ 整个 `action_head.py` 一行都不执行 (09-14/09-15 两次实测均 `(无)`)。
2. **是训练分支**: 断点那行在 `forward` (flow-matching MSE loss), 运行/单步走的是同类另一个方法
   `predict_action` (@torch.no_grad 去噪循环), 两者零重叠; 全库唯一调用 loss 的地方在
   `SmolVLALewModel.forward` 内, 且被 `if not has_action: return {"action_loss": 0.0}` 把门。
3. **画布节点是结构节点 (本轮新增)**: `tools/gui/node_logic.py::node_action_head` 只
   `log(action_dim/chunk_size)` + `return (True, "配置")`, **一行都不实例化模型**
   ⇒ 在画布「🎯 Action Head」节点上右键/单步/双击永远进不了 src 源码。
   判据: `grep -n "def node_<名>" -A25 tools/gui/node_logic.py`, 看有没有真调用模型;
   只打印参数的 = 结构节点。通用化: 「节点名里有模型名」≠ 运行期调用它。
4. **真推理在跨 venv 子进程里 (本轮新增)**: `src/lerobot/policies/intact/runtime/model_adapter.py`
   用 `subprocess.Popen([<INTACT repo>/.venv/bin/python, tools/intact_worker.py, ...])` 起常驻子进程
   (行式 JSON 协议), INTACT 依赖只装在自己的 .venv ⇒ **父会话断点物理上断不到子进程代码**。
   父进程侧能断的落点: `IntactIntentService.run_once` / `build_skill_ctx` /
   `install_direct_act` / `IntactNode.step`。想断子进程: 在其 venv 里 in-process 重放, 或 attach debugpy。
   **汇报时必须说清"断点在父进程还是子进程"**, 否则会被误判成假接入。
5. **断点绑错文件 (本轮新增)**: `gui-venv311` **没装 lerobot** (`import lerobot` → ModuleNotFoundError),
   引擎按 `src/` 路径 importlib 加载 ⇒ 断点必须落**绝对路径**
   `/home/ubuntu/lerobot-smolvla-lew/src/lerobot/policies/smolvla_lew/action_head.py`;
   绑到 site-packages 副本或同名文件 (`vla_jepa/action_head.py` 也有一份同名 head/forward) 不命中。
   核对法: 在 `predict_action` 里 `print(__file__)` 或看断点旁的路径。

## 探针铁律: 行号必须运行时定位 (本轮踩到的假证据)

`tools/probe_l4_callchain.py` 的 `micro()` 把断点行**写死成 307**; 文件后来加了 `l4_cond` 形参,
loss 行漂到 **351** ⇒ 探针打印「forward() → loss=1.9193 · 行 307 命中 **0** 次」, 读起来像
"forward 没进", 实际 forward 进了 (已执行行列表里 330-351 全在, loss 行 351 命中 1 次)。

- 正解 (已改): 按源码内容定位 `_find_line(ACTION_HEAD, "return (loss * valid_mask).sum()", 307)`,
  并在输出里带上实际行号: `forward@53 / predict_action@354 / loss 行@351`。
- 通用教训: **"0 次命中" 的结论先查行号是否漂移, 再说"代码没跑"**。反方向误判
  (把真执行当假接入) 与"把没跑说成跑了"同样致命。
- 同族坑: `action_head.py:53` 是 `TimestepEncoder.forward`; loss 分支入口是
  `SmolVLALewActionHead.forward` (322)。`def forward(` 一个文件里有多处 —— 只 grep
  `def forward` 会把断点指到错的函数上。

## 本轮实测数字 (L4 档 5 步; 与 09-14 的 40 步同口径, 结论一致)

| 计数 | L4 档运行 |
|---|---|
| `action_head.py` 已执行行 | **(无)** |
| loss 行 351 / forward 入口 53 / predict_action 入口 354 | 0 / 0 / 0 |
| `IntactNode.step` · `IntactIntentService.run_once` · `build_skill_ctx` | 5 / 5 / 5 |
| micro 正对照 `forward()` | loss 行命中 **1** (增量) |
| micro 正对照 `predict_action()` | loss 行增量 **0** |

命令 (系统 python3 无 torch, 必须用带 torch 的 venv; 探针内部自行 `CUDA_VISIBLE_DEVICES=""`, 不抢 GPU):

```bash
cd /home/ubuntu/lerobot-smolvla-lew
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py micro      # 正对照, 秒级
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L4 5       # INTACT 直驱
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L3 2       # 625M 模型 CPU 加载, 慢 (>3min → background)
```

## 回答这类问题的结构 (老倪认这种)

1. **一句话结论**: 这行是训练 loss 分支, 运行/单步永远不进;
2. **静态唯一入口**: 唯一调用者 (文件:行) + 把门条件 (`if not has_action: return 0.0`);
3. **运行期证据**: 探针数字表 (谁在跑 = 计数非 0, 谁没跑 = 0), 并说明正对照怎么证明打桩有效;
4. **正确落点**: 想断住该打哪里 (父进程/子进程分开说);
5. **顺带修掉的工具 bug**: 如探针写死行号 → 已改动态定位 (避免下次再被假 0 误导)。
