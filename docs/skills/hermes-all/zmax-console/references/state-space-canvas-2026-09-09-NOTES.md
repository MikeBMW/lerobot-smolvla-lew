# 2026-09-09 v5.4.2 关键坑 — 执行链/重启/档位 (供未来会话速查)

详见 `references/exec-chain-cap-switch-2026-09-09.md`(本会话已写入, 主题覆盖):
- 能力档位 radio 三档开关(数据源层, 单击直选/双击循环, 档位持久 params)
- 执行链纪律: 单步/播放 `_ss_order`/`_ss_step_order` 必须排除 ①cap_switch 开关节点
  (执行=切档副作用, L4→L2 实锤) ②观察器/质量门 (params.viz_kind 自动弹窗 4 窗叠开
  not responding; verif_layer 自动跑用例) + 按能力档位过滤 (row_bg 色带层级)
  + 切档必须重置执行序 (否则 L2→L3 后单步永远进不了 VLM/ActionHead)
- 🔄重启: 真实化引擎 daemon 线程从不终止 → 重启开新引擎 = 双 metaworld env 并发
  mujoco C segfault → run() 支持 _abort + GUI 存线程句柄 + stop_sim 轮询 join (≤10s)
- 🔄重启语义 09-09 用户两次纠正推翻 09-04: 永不自动运行, 只复位待命
- GUI 档位大写 "L4" vs 引擎判小写 "l4" → run(cap) 入口 str.lower() 归一
- 画布孤立节点 = "没有输入输出" 排查三连 (入度/出度统计 + 注册 grep + io channel)

本文件为指针冗余备份 — SKILL.md 大文件 patch 被 read-before-write 机制拒绝时,
未来 curator 合并指针可引本目录下任一 2026-09-09 reference。
