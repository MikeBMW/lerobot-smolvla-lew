# 视觉引导抓取技能 `L2.grasp_vision` — 设计与判据 (2026-09-22)

老倪: 「你能判断一号位或二号位, 哪个有光模块, 并进行抓取么?」→「你先把这个动作编写成一个
**视觉引导**的技能, 保存数据, 小版本迭代; 等我确认安全了再实际发送。」

状态: **技能已注册 + 自检全绿 + 真机 dry-run 通过; 真发等现场确认 (`--apply`)**。

## 一、判位 = 双路独立证据, 一致才认

| 路 | 手段 | 判据 | 依赖 |
|---|---|---|---|
| A 模型 | YOLO `peg` 框(与 `cam_rs.png` 同帧) **框底心** ↔ 槽位示教点的手眼投影 | 横向 `\|Δx\| ≤ 12px` (两槽横向差 ~46px) 且 `框底−投影 ∈ [−5, +25]px` (夹爪咬合高度带) | 内参 `models/real_cam_calib.json` + 手眼 `models/handeye_state.json` + 当前 TCP (`/robot/tcp_pose`, 只读) |
| B 像素 | 模块所在竖直带内「竖直棱边能量」**列剖面**找峰列 (平滑窗 25, 峰间 ≥30px) | 峰列与该槽投影重合 `≤ 20px` (只认唯一归属) | 只读原图, **不依赖任何模型** |

出口: `A==B` → 认账; 冲突 / 只有单路有信号 / 无检出 / 帧不新鲜 → **不出结论** (宁缺勿假)。

**实测 (08:41, 真机)**:
```
当前 TCP [0.491494, 0.417166, 0.254241] · 帧龄 0.09s
slot1 投影 像素(404,171) 距相机 0.424m      slot2 投影 像素(358,174) 距相机 0.425m
路A: slot1 Δx=43.1px ✗   slot2 Δx=3.3px 框底-投影=+12.9px ✅
路B: 棱边峰列 [358, 465, 44] → slot1 最近峰距 46.4px ✗ · slot2 0.0px ✅
⇒ 双路一致: **slot2 有光模块, slot1 空槽**
```
证据图: `docs/design/evidence_20260922/slot_occupy_evidence.png` (白框=各槽投影 ROI, 十字=投影点, 粗框=YOLO peg)

## 二、执行 = 四段, 逐段真值到位才进下一段 (执行由 L2 收口)

```
阶段1 到模块所在槽正上方 (+30mm)     tol 1.0mm · 守卫 下降≤400mm
阶段2 下降到抓取位 (含 0mm)          tol 0.5mm · 守卫 下降≤40mm · 到位即停·禁下压
阶段3 合爪 force40                  夹爪回执 curr_pos 是唯一真值 (空爪≈21 / 夹住模块≈185)
阶段4 抬升 50mm 离槽 (相对当前位姿)   tol 1.0mm · 姿态不变
守卫总闸: z_floor = 该槽示教抓取位 (绝不低于它) · 直线 > 500mm 拒发 · 限速 30
```

## 三、视觉门在**执行器内**再判一次 (fail-closed)

`data/skills/l2_atomic/registry.json` 里条目带 `vision_gate`; 执行时 `l2_daemon.run_stages` 先调
`vision_grasp_skill.judge_slot()`, 把阶段里的**占位点 `slot_vision`** (含各级 `z_floor_point`) 解析成真实槽位:

```
判不出 / 两路冲突 / 视觉模块异常 / 解析出的槽位不在点位库  → 🛡 拒发 (零下发)
```
⇒ 就算有人手滑把 `point` 指到没有模块的槽, 也会被视觉门改写/拦下; 未部署视觉门时占位点解析不到 → 同样拒发,
**不会退化成"盲发到默认槽位"**。

## 四、零下发自检 (30 项全绿 · 真机零接触自证)

`tools/test_vision_grasp_skill.py`: A 结构 6 项 · B 视觉判据 9 项 (正例 slot1/slot2、两路冲突正反向、无检出、
框偏出咬合带、负帧龄、帧龄 99s、视觉不过→总闸不过) · C 执行器内视觉门 8 项 (判不出拒发/解析成功 dry 四阶段/
占位点解析/阶段1 计划/z_floor 解析/反证未解析必拒/远离 600mm 拒/真值过期拒/未到位只发一条) · D 非回归 7 项
(L2.slot1/slot2 仍两阶段 · L2.pull_module 仍五段 · 唯一 vision_gate · 老路径点位解析不变 · 技能数未减)。

**加固**: 三个下发出口 `chan_send / _call_remote / _service_call` 在自检里全部换成记录器 → 断言
`SENDS=0, GRIP=0`。同一加固也打到了 `tools/test_slot_skills.py` (它原来只关位姿直读, 运动步仍走真通道)。

## 五、用法

```bash
# 只判位 + 计划 (零下发) —— 默认就是这个
gui-venv311/bin/python tools/vision_grasp_skill.py
# 真发 (需现场确认; 走 FIFO → l2_daemon, 逐段真值到位; 完成后自动复判槽位应变空 + 夹爪回执)
gui-venv311/bin/python tools/vision_grasp_skill.py --apply
# 逐段核对 (更稳): FIFO 里带 stages
echo '{"skill":"L2.grasp_vision","stages":[1,2]}' > ~/zmax_data/l2_cmd.fifo
```

事后验收 (只看真值): ① 复判槽位 (被抓走后该槽应变空/不再双路命中) ② 夹爪回执 `curr_pos`≈185 (夹住) 而非 21 (空爪)。

## 六、文件

- 技能本体: `tools/vision_grasp_skill.py` (判定/前置闸门/编排/事后验收) · 注册: `tools/register_vision_grasp_skill.py`
- 执行器钩子: `tools/l2_daemon.py` → `_vision_resolve()` + `_apply_vision_names()` + `run_stages()` 首段
- 复核工具: `tools/slot_occupy.py` (单路版, 保留) · `tools/slot_occupy_verify.py` (像素复核 + 证据图)
- 自检: `tools/test_vision_grasp_skill.py` · `tools/test_slot_skills.py` (已加固)
- 版本: `tools/bump_version.py` (小版本一条龙)
- 证据: `docs/design/evidence_20260922/vision_grasp_result.json` · `slot_occupy_evidence.png`
