---
name: l5-live-arm-marking
description: Use when 实时标注臂相机画面或 overlay_spec 被覆盖.
---

# L5 臂相机实时标注 (光模块 + 14 槽位)

目标: 老倪在 `http://10.163.146.78:8793/station` 第一格 (🦾 臂上 D405) 看到**持续更新**的框,
他挪相机后自动重算, 无需人工触发。产物: `tools/l5_live_mark.py` + `tools/l5_live_mark_run.sh`。

## 架构铁律
- 服务 `tools/cam_live_stream.py` **每帧热读** `data/scene/overlay_spec.json` 渲染到 `ov_arm.jpg`, 端点
  `/snapshot/overlay_arm.jpg`; overlay-fps=10 ⇒ 标注器写 spec 5Hz 就够 (写更快无意义)。
- 框**必需字段 `xyxy=[x1,y1,x2,y2]` 像素整数** (`tools/scene_overlay.py:draw_spec`, `xyxy = b.get("xyxy")`) ——
  缺它被判"无几何"跳过; label/origin/kind/conf 只是附加。
- **只改自己 origin 的框** (`origin='l5live'`), 其余 origin 一律保留原样。整份重建 spec 会覆盖别人相机的框
  (老倪投诉过)。实现: 读现有 spec → 只替换本 origin → 写回 (实测 "kept":4, mine:1)。
- 常驻: `l5_live_mark_run.sh` 是 `while true; do python ...; sleep 2; done` 守护壳 (单实例+崩溃自动重起);
  Hermes 里用 background+`persist_on_release=true` 或 `setsid nohup` 起, 别前台阻塞。

## 检测器要点 (踩过的坑)
- 光模块: `models/yolo_peg_live.pt` (类别 {0:'peg',1:'OPT_Gold'}), conf 0.20 保留低置信但**label 上写 conf**。
  实测: conf 0.2~0.28 在**空槽**上有误检 (真模块 ≈0.67-0.75) ⇒ 要干净就 `--conf 0.35`。
- 槽位: 纯几何。锚线取 5 条长横边 (rim_top / 槽底 / 分隔条 / 下排槽底) → 行带内折叠方差定 pitch
  → 1D NCC 定槽心 → 格点一致性清洗 → 等间距格子补齐 7 个。
- **周期只在画面中央窗内估**: 全宽会吃进背景/托盘侧壁的非周期结构, pitch 被带偏 (61.5 → 94)。
- **长竖边掩码**剔除托盘侧壁: 真槽侧竖边只跨行带 (0 行强竖边), 侧壁贯穿整帧 (13~26 行) ⇒
  `tall_thr = max(6.0, 0.03*H)`, ±0.15p 窗内超阈则弃。
- **证据门槛**: 一行至少 3 个实测槽位才认作真治具行 (证据不足宁可报未检出, 不乱画); 外推框 conf=0.30 且
  label 标 `[ext]`, 实测 conf=0.75。`slot_state` 要把 reject 原因逐行写出来, 不能只说"0/14"。
- 合理性断言: 宽高 8~200px 且在画面内, 否则丢进 `bad` 并计数。
- 帧静止检测: 帧 md5 连续 3s 不变 ⇒ 状态写 `画面静止 Ns(源可能卡住)`。

## 取证法 (可复现, 不碰机器人)
相机被挪走后无法在页面上诚实标治具 ⇒ 用**帧桩**做受控实验证明"自动跟随":
1. `frame_stub.py 8899` 供 `stub_current.jpg`; `make_test_frames.py` 从真实帧派生 位移/缩放/无治具 三种帧。
2. 标注器第二实例 `--http http://127.0.0.1:8899/frame.jpg --spec spec_test.json` (绝不写生产 spec)。
3. `follow_test.py` 分阶段换帧, 采样 spec 里框心: 实测位移 +39px (生成 +40) / 中心距比 1.175 (生成 1.18) /
   无治具 0 框 / 回原帧坐标复现 ⇒ 跟随成立。
4. `latency_test.py`: 换帧→spec 可读新框 102~203ms (≤1 个周期)。
5. `sample_spec.py`: 数 spec.ts 变化 ≈ 实际 Hz (实测 5.08Hz)。
6. 对齐自检用**数值剖面**而不是只看图: `g[y0:y1,:].mean(0)`, 凹槽暗带 [233,266] 对框 [233,267] ⇒ ≤1px。

## 现场结论口径
- 相机**停在别处**时正确定义为: 全 0 个槽位框 + `slot_state` 写逐行原因 + 只保留 YOLO 模块框 +
  进程照跑 (5Hz), 不能崩、不能猜。局部可见的行 (被画面边缘截断) 目前也报未检出 (栅格需完整行结构)。
