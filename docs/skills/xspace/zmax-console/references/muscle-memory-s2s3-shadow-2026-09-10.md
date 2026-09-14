# 肌肉记忆 S2/S3 扩展: io 契约 + 技能词典 + 影子模式 (2026-09-10)

承接 `muscle-memory-v5-1-0-2026-09-08.md`(v5.1.0 快通道) 与
`canvas-json-edit-safety-2026-09-10.md`(画布/意图丛节点)。
本次为"三层能力共享(意图丛)"落地的 S2/S3 切片 — **零训练**, 纯检索/记录层。

## S2 — L2 技能契约工程化

- **io 契约**: `tools/gui/muscle_memory.py`
  - `begin_episode` 缓冲加 `seg_io`; `feed()` 记录该段 `entry`(首帧) / `exit`(末帧) 的
    状态[:3] + 动作[:4] + `frames`;
  - `end_episode(ok=True)` 把 `seg_io[st]` 写进 `db[(seed, stage)]["io"]`(**成功轮才写**);
  - `_load/save` 带 `io` 字段(旧数据 `None` 兼容, 不要假设字段存在)。
  - 用途: L3 编排的**段间接力条件**(前一段 exit ≈ 后一段 entry) / L4 组合调用 L2 标准动作。
- **技能词典**: `tools/gen_skill_dict.py` → `models/skill_dict.json`
  (`models/` 不入 git, 可随时重生成); 在线等价 API 在
  `src/lerobot/memory/memory_graph.py`: `skill_dict()` / `intent_direct(dz)` /
  `skill_io(skill)` / `recall(stages, seed)` / `link(...)` / `sync_l2_from_muscle()`。
  - Δz 由标杆 `champ_x` 首末差算; 实测 7 技能(各 107 次练习 / 18-20 个种子桶) 全部带 io。
  - `intent_direct` 命中延迟 ~15ms(首次读盘), 参照 INTACT Direct 论文 2.9-5.5ms。

## S3 — 影子模式 (只记录不接管)

- **引擎全段对比**: `state_space_sim_real.py` 主循环在快通道之后加影子块 —
  **所有段**(含快通道禁用的插入/完成) 取 `get_champ(seed, stage)`, 与实际 `u_ff` /
  `self.x` **同帧**比较 → 段级 `{n, du_mean, du_max, dx_mean, dx_max}`;
  段末派生 `gate_ok = dx_max < 0.002` (2mm); 汇总 `tr["shadow"]` + 共享记忆 `l3.shadow`;
  开关 `SS_SHADOW=0`。
- **观察必须与快通道解耦 (踩过)**: muscle 库对象**总是加载**(影子/io 采集需要读标杆),
  快通道单独由 `SS_MUSCLE` 控, 观察单独由 `SS_OBSERVE` 控。
  最初三处 `if _mm_on and self.muscle:` 共用一个开关 → `SS_MUSCLE=0` 时 begin/feed/end
  全停 → io 契约"0 段已采集", 影子也没数据。
- **回归口径 (红线)**: 影子/io 属纯增强, 必须验证控制零改动 — `SS_MUSCLE=0` 基线
  `mode="insert", max_steps=600` 应 **done=True / 343 步**(与改造前一致)。
  注意 `max_steps` 给小了(如 400)会误判"未完成"; 而 `SS_MUSCLE` 打开时既有现象是
  insert 900 步未完成(历史遗留, 与影子改动无关, 需单独排查)。

## 关键结论 (影子首轮数据)

- 全 7 段 `gate_ok=False`, dx 偏差 12.6mm(接近) → 188mm(插入), 远超 2mm 阈值。
- 解读: 现有标杆库是**历史累积, 混入过不同代码版本的轨迹**(R1 成功轮污染史) →
  **"L2 标杆先验直接接 L3/L4"会跑偏**; 正确路径 = 清库 → 当前代码在 R0 重练 3-6 轮 →
  影子复测 gate 转 ✅ 再决定启用。
- 方法论: **影子模式的价值 = 接管前先用数据证明可行性**, 而不是接了才发现回退。
  给用户报进展时把"引擎修复的成绩"与"模型能力提升"分开说, 别把前者算成训练突破。
