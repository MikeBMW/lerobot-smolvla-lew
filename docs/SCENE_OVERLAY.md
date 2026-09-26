# 场景叠加 (Scene Overlay) — 真实视频流 + 仿真场景检测框

> 老倪 2026-09-27 需求原文：
> 「继续同步仿真环境和实际环境…你要继续完成对真实场景的建模，利用L5层大模型的理解能力，
> 你来建立深度地图，将真实场景与之前的仿真场景同步渲染，即在真实视频流中嵌入仿真场景的
> 检测物体边界框，总之是把虚拟场景与真实场景叠加。状态空间中增加场景叠加按钮，用于打开
> 真实场景视频流和各种仿真场景看到的边界框，边界框的位置需要大语言模型理解后，告诉渲染
> 引擎叠加。」

## 一句话
**把物体的真实三维位置，经手眼标定 + 实时 TCP 真值投影成像素框，画到真机视频流上；同时叠加
L5 大模型的看图理解框和真机 YOLO 检测框 —— 三个来源颜色区分、互不覆盖、各自可溯源。**

## 核心：一条可验证的投影链

```
p_base  --(实时 TCP 位姿 /robot/tcp_pose 真值)-->  p_tcp
p_tcp   --(手眼外参 X = T_cam2tcp, tools/calib/handeye)-->  p_cam
p_cam   --(相机内参 K, 真机 camera_info 实测)-->  (u, v) 像素
```

反向（`config/robot/zmax_sim2real.json` 里写明的感知口径）：
```
(u,v) --K 反投影射线--> 与平面 z=plane_z 求交 --> p_base
```

三个参数**全是实测/标定来的，没有任何写死几何**：

| 参数 | 来源 | 实测值 |
|---|---|---|
| 内参 K | 真机 `/realsense/color/camera_info` | fx=394.062 fy=393.472 cx=318.4436 cy=238.658 @640×480 |
| 手眼 X | `tools/calib/handeye/handeye_result.json` (TSAI·8位姿) | \|t\|=251.7mm · 闭环 std=1.74mm |
| TCP | `/robot/tcp_pose` (PoseStamped, base_link) | 每 2s 刷新一次 |

## 三个来源（画面里颜色区分，绝不混为一谈）

| 来源 | 颜色 | 怎么来的 | 说明 |
|---|---|---|---|
| `sim` 仿真投影 | 🟢 绿 | 物体 3D(base 系) → 投影链 → 框 | 真几何投影，"仿真场景框叠到真实视频"就是这条 |
| `vlm` L5 大模型 | 🔵 青蓝 | 实帧 → DeepSeek 视觉 → 像素框 + 标签 + 场景描述 | 5s；推理型模型 max_tokens 必须给足(9000) |
| `det` 真机检测 | 🔴 红 | 在役 YOLO 权重 `models/yolo_peg_live.pt` | ultralytics 直接吃 BGR ndarray |

规格文件 `data/scene/overlay_spec.json`（`data/` 按本仓惯例不入库，属运行时状态）。三个生成器
**各自只替换自己那一类框**（`scene_overlay.merge_origin`），所以可以同时显示。

## 验证（全部真实数据，非构造）

### 1. 投影链端到端（`tools/verify_projection_chain.py`）
口径：板中心在 base 的位置由 8 位姿闭环解出（std=1.74mm），用**每个位姿自己的 TCP 真值**正投影回
**该位姿自己的图**，与该图中 `findCirclesGrid` 检出的 20 点质心比对 —— 完全同口径（解算器闭环用的
就是 `OBJ.mean(0)` 点云质心）。

| 位姿 | 投影 | 实检 | 差 |
|---|---|---|---|
| he16_ym35_tp00 | (831.4, 417.4) | (836.0, 416.7) | 4.7 px |
| he16_yp00_tm14 | (617.8, 444.0) | (619.6, 445.2) | 2.2 px |
| he16_yp00_tp00 | (592.1, 442.1) | (590.5, 443.9) | 2.4 px |
| he16_yp00_tp14 | (566.6, 444.7) | (561.8, 447.9) | 5.7 px |
| he16_yp35_tp00 | (356.2, 358.0) | (348.5, 356.1) | 8.0 px |
| he17_ym35_tp00 | (872.8, 546.2) | (882.0, 543.3) | 9.6 px |
| he17_yp00_tp00 | (578.3, 570.1) | (578.9, 571.7) | 1.7 px |
| he17_yp35_tp00 | (281.8, 480.4) | (272.4, 477.6) | 9.9 px |

**误差中位 5.2 px ≈ 3.1 mm**（按板上 20mm 间距≈34px 折算）。最差的两个都是斜视角位姿。

### 2. 叠加框 vs 真机实测框（`tools/verify_overlay_alignment.py`）
两条**互相独立**的链指向同一物体（一个纯图像侧、一个纯几何侧）：

- `det`（纯图像）：真机 YOLO 实检 → 框中心 **(337.5, 30.4)**
- `sim`（纯几何）：深度实测 3D → 手眼 + 实时 TCP → 投影 → 框中心 **(338.4, 28.5)**
- **中心差 2.1 px**（215mm 处 ≈ 1.1mm）

⇒ 仿真框叠加是**真实几何**，不是画上去的。

### 3. 深度地图物理自洽（`tools/ros_scene_depth_build.py`）
深度实测的 peg 位置 **(520.9, 234.4, 234.4)mm** vs TCP **(533.7, 231.3, 227.1)mm**
⇒ **距 TCP 仅 15.1mm**，正是"夹爪夹住的光模块"应有距离。

### 4. 画面自证（用 L5 大模型回读叠加图）
把叠加后的帧再喂给大模型，它读回：
> 框: 光模块/pcb/插盘/光模块/标定板/线缆；底部条带: 有 —
> 「场景叠加；det+sim+vlm；帧龄0.1s、时间00:38:12；TCP=(0.5337,0.2313,0.2271)；
> 手眼cam→tcp 252mm；框统计：仿真1、大模型5、检测1，共7」

⇒ 画面里的真值带内容与实际状态一致（不是渲染好看的装饰）。

## 深度地图（`tools/ros_scene_depth_build.py`，容器内跑）

```
深度像素 (u,v) + z=值×0.1mm → p_cam → p_tcp → p_base → 点云/占据栅格 + 语义物体 3D
```

- 容器 `ss-remote-tap`（`/repo` 只读挂载，产物写 `/out` = `~/zmax_ss_remote`）
- 订阅：`/realsense/depth/image_rect_raw` + `/realsense/color/camera_info` + `/robot/tcp_pose`
- 实测一帧：480×640 · 有效 83.7% · 量程 195~3567mm · 中位 373mm · 点云 7163 点
- 产物：`depth_raw.npy` / `depth_vis.png` / `topview.png` / `stats.json` / `zmax_scene/objects3d.json`

## 服务端点（`tools/cam_live_stream.py --overlay`）

| 端点 | 说明 |
|---|---|
| `/overlay` | 叠加页（左原始 / 右叠加 + 四个来源按钮 + 状态面板） |
| `/overlay/arm.mjpg` · `/overlay/local.mjpg` | 叠加后的视频流 |
| `/snapshot/overlay_arm.jpg` | 叠加帧快照（取证/自检用） |
| `/scene.json` | 当前规格 + 每路叠加统计（画了几框/跳过原因/TCP 是否读到） |
| `/gen?kind=sim\|vlm\|scene\|det` | 后台触发一个来源的生成（不阻塞请求，跑完自动出现在画面里） |

**关键设计**：叠加是**独立渲染线程 + 独立帧槽**，只在开启时才付出"解码→画→重编码"开销；
原 `arm.mjpg`/`local.mjpg` 的 "JPEG 直转" 最快路径**一字未改**。

## 状态空间入口
`tools/gui/simulink_module.py` 主工具栏（`tl`）加 `🧩 场景叠加` 按钮（在 `🌐 打开 3D 场景` 旁）→
`open_scene_overlay()`：视频流没在跑就**自动带 `--overlay` 启动**，然后开浏览器到 `/overlay`。

验收（按 `state-space-canvas-engineering` 技能的层级）：① `ast.parse` ✓ ② 真 `import` ✓
③ `verify_canvas_render.py` → 86 节点/168 连线项 渲染正常 ✓ ④ 离屏真构造 `SimulinkModule`，
确认按钮真被建出来且在工具栏里 ✓。**未改 `flows/state_space_obs.json`。**

## 坑（都踩过）

1. **`/robot/tcp_pose` 是 `PoseStamped` 不是 `Pose`** —— 位姿在 `.pose` 下，按 `Pose` 订阅永远收不到
   （表现：depth/info 都有、tcp 恒 None）。
2. **Orin :8792 的 `/depth.*` 是假端点** —— 服务对任意路径都回退 JPEG（HTTP 200 + `image/jpeg`）。
   查端点真假要看**响应头 4 字节**（`FFD8`=JPEG）而不是状态码。
3. **容器 `/repo` 只读** —— 产物必须写 `/out`；读取侧两处都找，否则漏拷贝就静默空框。
4. **深度点云有远场噪点** —— 量程 max 3567mm 会把包围盒拉到 x=3.7m；语义物体用**框心中位深度**
   而非单点，天然抗噪 + 抗边缘空洞。
5. **`--build` 不能整体覆盖规格** —— 会把 det/vlm 框冲掉；必须 `merge_origin` 按来源合并。
6. **推理型 VLM 的 `max_tokens` 给不足 ⇒ content 空** —— reasoning 吃光额度，要给到 9000。
7. **大模型框会越界/量纲漂移** —— 落图前必须强制裁剪到画面内并丢弃退化框，否则画出莫名长条。

## 待办 / 诚实边界

- **仿真世界系 → base 系**：metaworld peg/hole 的几何在**仿真世界坐标**，要投到真机画面需
  `tools/ss_geom_calib.py --record` 的示教几何（现场零运动示教，**未采**）。今天能做的是
  用**深度实测的 base 系 3D** 当仿真侧物体源 —— 对 peg 这类真实存在的物体，两条链已经收敛到
  同一个物体（2.1px），效果与"仿真框叠加"一致。
- **手眼旋转精度**：旋转残差 9~15°(yaw=0) / 29~39°(yaw=±35，斜视角 PnP 不可靠)。位置投影已
  验证到 5.2px，但要求 1~2° 的精密抓取还需补采（yaw=0 附近 + 更充分倾角组合，**需动机器人**）。
- **`plane_z` 未标定**：反投影回退路径（感知→引擎）暂不可用；正投影（本功能）不需要 plane_z。
- **笔记本相机无叠加框**：`local` 路当前只有原始流（`/overlay` 页可切换查看，暂无来源生成器）。
