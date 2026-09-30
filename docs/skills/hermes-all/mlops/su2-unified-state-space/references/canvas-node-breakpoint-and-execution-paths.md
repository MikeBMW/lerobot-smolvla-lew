# 画布节点"断点不进入"六根因 + 执行路径分流 (2026-09-20 实测)

用户报: 「运行后，为什么不进入这个断点?」(断点设在 `su2.py::SU2UnifiedState`)。
排查顺序如下, **前四条与断点本身无关**, 别一上来就怀疑 debugpy。

## ① 执行路径分两条: ▶运行 ≠ 真实执行 (最常被忽略)
- `▶运行` → `_ss_tick` 每帧 `execute_node_logic(..., demo=True)` → `_demo_node_output()`
  **只读 DataWorld 当前帧里引擎算好的 out 来显示, 不重跑节点真实函数**(v3.4.8 为防冷加载卡播放)。
- 实测同一节点: `demo=True` 时真实函数被调用 **0 次**(断点必然不命中);
  `⏭单步` / 右键「运行节点」(`demo=False`) 调用 **1 次**。
- 因此: 用户说"断点进不去" → **先问是按的 ▶运行 还是 单步/右键**。
- 修法(让便宜的重计算节点在 ▶运行 时也真跑): `_demo_node_output()` 里加分支
  ```python
  if (ctx.get("params") or {}).get("<flag>") or "<关键词>" in name:
      return node_xxx({**ctx, "demo_light": True})
  ```
  节点函数读到 `demo_light` 时**跳过一切冷加载**(不调 `_ss_ensure_obs43`/YOLO/metaworld), 只用
  `_SS_STATE` 缓存; 无缓存就退单位元并在日志里说明(不编造)。实测 1 ms vs 完整路径 2229 ms →
  播放不卡, 断点可命中。

## ② harness/假模块的属性是 truthy
`FakeMod.__getattr__` 万能兜底返回 lambda ⇒ `trace = bool(getattr(module, "_trace_nodes", False))`
变 True ⇒ 走 `_trace_exec` 逐行执行 ⇒ 节点"执行失败且无日志"的假象(本次排查最费时的一环)。
给假模块**显式**写 `_trace_nodes = False`(以及 `_ss_tr`/`_ss_round`/`_ss_io_frame` 等)。

## ③ 双击语义 ≠ 执行
被面板化的节点(如 `params.su2_unified_state`)双击是**开观测面板**; 执行入口只有
`▶运行` / `⏭单步` / 右键「运行节点」。新增双击分支必须放在 **source 分支之前** ——
带 `source` 字段的节点会被"数据源切换"分支抢先(历史上多次踩)。

## ④ 断点所在的文件/进程不对
- 断点必须设在**真源码**上(右键 open_in_vscode 打开的是仓库真路径);
  `open_node_source` 复制到 `/mnt/c/zmax_src_view/<name>` 的**副本**上设的断点永不命中。
- 目标进程必须由 VSCode **F5/attach** 启动; 终端裸起 `studio.py` 的进程不绑任何断点
  (可用 `ps` 看命令里是否带 `debugpy ... launcher` 判断)。
- `launch.json` 里 `env: {}` 只影响框架自带的 `debugpy.breakpoint()` 钩子
  (`ZMAX_DEBUG_BREAK=<节点名子串>`), **不影响**自己设的行断点。

## ⑤ 节点名/注册与画布不同步
画布节点名必须与 `node_logic` 注册关键词一致; 若画布上还是旧名(旧 flow 未重新加载), 会匹配到
旧执行函数 ⇒ 新代码根本不跑。画布加载会重映射 node id ⇒ 查找节点按**名字**, 不按 json id。

## ⑥ 改完代码没重启进程
GUI/常驻进程改代码后必须重启(旧进程内存里是旧代码); 常驻执行器还要"杀掉 → 由保活脚本拉起 →
看启动日志第一行"才算真起来(语法检查过 ≠ 能起来, 运行时 NameError 只有启动时才暴露)。
