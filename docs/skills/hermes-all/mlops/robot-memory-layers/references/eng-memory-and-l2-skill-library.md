# 工程记忆节点收"机器人可执行技能库" + L2 示教点位库 (2026-09-24 实测)

## 1. 工程记忆节点 (📚 技能与经验库) ↔ 可执行技能库

老倪要求: 「把『回到金手指点1』这类**机器人技能**，在**工程记忆**这个节点增加」。

- 落点: 画布节点 `n_eng_mem` = `📚 工程记忆 · 技能与经验库`
  → `src/lerobot/memory/eng_memory.py::EngMemory` (`collect()` / `sync_to_macro()`)
  → 同步进顶层宏观记忆 `data/macro_memory.json#engineering`。
- **原实现只收** `docs/memory/*.md` + `~/.hermes/memories/*.md` + `~/.hermes/skills/**/SKILL.md`
  ⇒ 只看得见"Hermes 技能清单"，**看不见机器人能执行什么**。
- **扩展后** 追加: `data/skills/l2_atomic/registry.json` (L2 原子技能库 = GUI 技能清单与常驻执行器同一真源)
  + `data/skills/l2_muscle/*.json` → 快照含 `l2_skills`(id/name/group/ros/point) 与
  `counts.l2_skills` / `counts.l2_muscle_skills`，并写进 `macro_memory.engineering.l2_skills`。

### ⚠️ 指纹坑 (会"静默不生效")
`sync_to_macro()` 用幂等指纹 `fp_src = json.dumps([[path,size,mtime] for f in <文件列表>])`。
**新增的技能库文件必须一起进指纹**，否则技能库改了却判"指纹相同 → 幂等跳过"，同步永远不发生。
加库/加文件后先确认返回 `wrote=True`，再**读回** `macro_memory.json#engineering.l2_skills` 验证。

### 幂等语义 (别误报失败)
第二次调用返回 `{"ok":true,"wrote":false,"why":"内容未变 (指纹相同) — 幂等跳过"}` 是**正常**。

### 可观测性
节点执行日志要带"机器人可执行技能 N 条"并在册点名，例:
`🤖 可执行技能 (AOI检测组 14 条): … 🎯 回到金手指点1`
否则"技能到底进没进工程记忆"没人看得见。

## 2. L2 示教点位库 + 回位技能

- 点位库真源: `data/skills/l2_atomic/taught_points.json`
  (`{pos:[3], quat:[4], desc, recorded_at, source, n_samples, spread_pos_m, spread_quat}`, frame=base_link)。
  **`data/` 不进代码库 = 运行时状态**（真机现场改点位不需要提交）。
- 回位技能写法 (`registry.json`):
  `{"id":"L2.goto_gold_pt1","ros":"line_abs","point":"金手指点1","point_locked":true,"quat":"taught"}`
  → **点的是"点名"不是坐标** ⇒ 点位一更新技能自动跟随；
  常驻执行器**每次执行都重读点位库**(热加载) ⇒ **改点位不用重启执行器**。
- 记录纪律:
  - 多帧采样取**中位**；
  - **抖动量判据**: 位置抖动 > 0.5mm = 还在动 → **拒绝记录**（不拿动着的位姿当示教点）；
  - 覆盖同名点位前把旧值追加进 `reports/aoi_points/<name>.history.jsonl` → **可回滚、可审计**；
  - 位姿读不到 → **不写库**并如实回报（绝不造假点位）。
- 真机验证纪律:
  - 验证回位链路**只用 dry-run**（算 Δmm/Δdeg + 打印将下发的命令，不下发）；
  - 确需端到端时，先确认执行器对"点位不存在"的行为是**拒绝且不动**（`if name not in pts: log(拒绝); return None`）；
  - 任何真机下发都要**如实告知用户**（本次实测: FIFO 发 `{"skill":"L2.goto_gold_pt1"}` → 执行器受理并按该点位下发
    `/move_line`；因臂已在该点，实际位移 0.1mm，无风险 —— 但必须报备，不能默认静默）。
- 便捷通道: `echo '{"skill":"L2.goto_point","point":"<名>"}' > ~/zmax_data/l2_cmd.fifo`
  （走常驻执行器 = 自带闸门/限幅/日志）；窗口里给"复制回位命令"按钮让人能粘到终端执行。
