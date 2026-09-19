# 多层记忆架构 (v5.10 · 2026-09-19 整理)

| 层 | 类型 | 真实写入者 | 真实读取者 | 存储 |
|---|---|---|---|---|
| L2 | 肌肉记忆(固化标杆→直通) | 原子技能成功回放 | 技能执行/直通判定 | data/muscle_memory.json |
| L3 | 流程记忆(跨段序列入库) | 技能序列完成事件 | 任务规划器/编排器 | macro_memory.knowledge |
| L4 | 宏观记忆(画像/归因/建议) | 任务复盘+LLM汇总 | 画布总装记忆中枢 | macro_memory |
| MEM | 工程记忆(文档/技能/条目) | tools/eng_memory.py | LLM 层问答 | macro_memory.engineering |
| 感知 | 感知/场景记忆(本轮新增) | tools/perception_chain_real.py | 规划器/异常推理器/总装记忆 | macro_memory.perception + data/scene_state.json |

真实链路: 真机帧 → YOLO(L2) → 板坐标系3D(工序系·免手眼) → DeepSeek VL(L3) → scene_state(单一真源) → macro_memory.perception → perception_chain.jsonl(可回放)
