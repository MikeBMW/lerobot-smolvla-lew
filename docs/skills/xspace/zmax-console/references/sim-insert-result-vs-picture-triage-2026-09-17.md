# 用户拿「仿真画面」质疑仿真结果时怎么办 — 2026-09-17 (三次同族提问, 已定界+取证)

老倪三连问: ①「现在的仿真渲染, 光模块最后没有插入槽内, 插槽与光模块插入的位置, 水平相差一段距离」
②「仿真渲染的视频, 光模块与插槽, 横向有偏差, 什么问题?」 ③(早前)「点击运行后, 仿真渲染的图像不动」。

## 定界顺序 (别先猜代码, 先把"他在看什么"钉死)

1. **窗口**: `DISPLAY=:0 wmctrl -l` —— 本次只有「📺 输入图像」开着 (**没有** 3D 视图窗口) ⇒ 看的是
   metaworld 真渲染流, 不是 DreamView3D。
2. **引擎在不在跑**: `/tmp/ss_live_frame.json` 的 `t` 与当前时间差 + `systemctl --user status zmax-studio`
   + `ps`(GUI 进程是否加载 mujoco)。本次文件最后落盘是**我自己的诊断进程** ⇒ 用户窗口那副画 = 引擎 idle 的静止初始帧。
3. **档位**: 画布 `flows/*.json` 的 `cap_switch/cap_level`(本次 L2) + `SimulinkModule._ss_vision_on` 定 R1/R0。

## 静止初始帧长什么样 (给数字, 别让用户猜)

`tools/diag_idle_frame_scene.py` —— 用**窗口同一个对象** `node_logic._yolo_ensure_aligner(None).env` 量:
光模块平躺台面, 中心 (0.1235, 0.6938, 0.020); 插槽孔口 (-0.2318, 0.651, 0.1303)
⇒ **水平相差 358mm (Δx 355)**, 还低 110mm。metaworld 初始布局本来就是"光模块躺台面 + 插槽在盒上"
⇒ 那副画面**永远不会**变成插好的样子 (帧率照样显示 12.5, 很能骗眼睛)。

## 真值口径 (站点只是"引擎以为", 用户眼睛看的是几何体)

- `tools/diag_insert_offset_truth.py`: 跑一轮引擎, 沿孔轴分解 **depth / lateral** 并落逐帧 CSV
  (`--vision 0/1 --cap L2/L3 --seed 104`)。
- `tools/diag_insert_geom_truth.py`: 不看站点, 直接打**几何体** —— 光模块 geom(box `0.015/0.015/0.12` =
  3×3×**24cm**, 长轴=世界 x) 的中心/两端 + 盒子立柱, 对比初始态与终态。
- 实测 (seed 104):
  | 档 | 步数 | done | 深度 (孔深 66.0mm) | 相对孔口横向 |
  |---|---|---|---|---|
  | L2 R0 真值档 | 350 | True | **65.7mm** | 2.1mm |
  | L2 R1 视觉档 | 357 | True | **64.8mm** | 2.5mm (途中 1 次 遇阻#1→🌀螺旋搜索→🛡回撤脱离→回退转移重对孔) |
  | L3 full (R0) | 875 | True | 插→**拔出**→AOI→回程→**放回原位** | 终态光模块回到台面 (0.030,0.524,0.012) |
- 几何体核对: 跑完光模块中心 (-0.1425, 0.4241, 0.1283), y 与插槽中心线差 **0.2mm**, 约 **9.8cm** 在盒体内
  ⇒ 物理/渲染对齐在毫米级; 用户看到的"一段距离"是**初始布局**, 不是插偏。
- ⚠️ **L2(insert) 收尾=插好; L3/L4(full) 收尾=拔出→AOI→放回台面** ⇒ 全链档"最后不在槽里"是**设计如此**,
  先问档位再判"失败"。

## 取证基础设施 (本次新增, 以后直接读文件)

- 引擎每 5 步 `ss_publish_metrics(ss_insert_metrics(...))` → `SS_LIVE_FRAME["metrics"]`, 由 `_ss_write_status()`
  1Hz 落 `/tmp/ss_live_frame.json`; **`run()` 收尾强制 `_ss_write_status(force=True)`** —— 否则 R0 整轮 ~1s
  (350 步), 1Hz 节流只留首帧样本 (本次实测踩到: 文件里始终是 step 5)。
  字段: `step / stage / depth_mm / lateral_mm / grasped / peg / hole / goal / viewer_consumed`。
  ⇒ 用户点 ▶运行 后不必让他截图, 直接读文件就能报"他那轮进孔多深 / 横向多少"。
- 引擎 idle 时窗口画面**压横幅** (`yolo_input_viewer._banner`: 顶部 7.5% 压暗 ×0.25 + 橙字
  「⚠️ 引擎未运行 · 静态初始帧 — 这幅画面没有在跑仿真 (点 ▶运行 看实况)」), 有实况帧则**原样显示**。
  取证 `tools/verify_viewer_idle_banner.py` (6 项: idle 有横幅 / 实况无横幅且字节一致 / 帧过期回横幅)。

## 3D 分层视图 (DreamView3D) 写死几何清单 (顺带核对, 本次 x/y 未违反)

`tools/gui/ss_dreamview.py`: `_HOLE_MOUTH=[-0.1685,0.4623,0.1309]` · `_HOLE=[-0.2345,0.4623,0.1309]` ·
`_BOX_CENTER=[-0.2645,0.4623,0.095]` · `_PEG_CENTER_OFF=[-0.03,0,-0.01]` · `_PEG_SIZE=(0.20,0.03,0.03)`。
- 槽/孔/盒 **由 `tr["_meta"]` 覆盖** (引擎发 `hole_mouth/goal/box_center`) → 实测 Δ=**0mm** ✅ (老"偏 3.8cm"已修)。
- **光模块几何**走 `tr["peg"] + _peg_center_off`, 而 meta 里**没有** `peg_head_off` ⇒ 走写死默认 `[-0.13,0,-0.01]`
  → `center_off=[-0.03,0,-0.005]`。实测终局: 视图画的中心 vs 真值 = **Δx/Δy=0, Δz=+5mm**;
  另 `_PEG_SIZE[0]=0.20`(画 20cm) 而真值 **24cm** ⇒ 画的杆短 4cm (要精确就补 meta 的 peg 几何)。
- `tools/diag_view_vs_truth_pegalign.py` 一键出这三行对照, 改这块前先跑它。

## 通用教训

1. **"画面里 X 不对"先钉"哪面窗 / 哪一档 / 引擎在不在跑"**(wmctrl + 取证文件时间戳), 再谈代码 ——
   本次三次提问里两次的答案是"那是 idle 初始帧 / 全链收尾放回", 不是 bug。别急着改几何常量。
2. **显示面必须自证**: 状态栏 + 画面上横幅 + 1Hz 取证文件三件套, 让"哪一路、哪一帧、有没有在跑"可被程序核对。
3. 诊断脚本一律**从真值入手** (站点 + 几何体 + 逐帧 CSV), 结果给 mm 级数字; 不要用再截一张图当证据。
4. `_make_env()` 只建 env, 推进前必须 `env.reset()` (否则 `AssertionError: self._target_pos is not None`);
   `sim.run()` 内部会再 reset 一次。
5. 诊断预算: R0 全链 ~1s/350 步; R1 视觉档 ~0.2s/步 (357 步 ≈ 70s)。长跑用 background + notify。
