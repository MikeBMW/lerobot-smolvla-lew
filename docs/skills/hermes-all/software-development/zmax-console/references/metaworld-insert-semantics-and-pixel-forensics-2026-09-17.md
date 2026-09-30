# 「光模块到底插没插进插槽」判定链 + 像素取证 + metaworld 官方语义 (2026-09-17)

> 同族提问第三次 (「插销没有插到插槽里, 横向有偏差, 必须改正确」) 时补齐的东西。
> 上游已有一篇 `sim-insert-result-vs-picture-triage-2026-09-17.md` (定界三连 / 真值口径 / 静止帧测量);
> **本篇 = 像素级取证 + 官方任务语义 + 资产几何**, 两边一起看。
> 定界顺序不变: 哪面窗 (`wmctrl -l`) → 引擎在不在跑 (`/tmp/ss_live_frame.json` 时间戳) → 哪一档
> (`flows/*.json` 的 `cap_level`, `_ss_vision_on` 定 R0/R1) → 才谈代码。

## 一、像素级取证: "用户窗口那幅图 = 哪个状态" 直接证明 (我看不了图, 就走这条路)

1. **抓窗口**: `tools/grab_window_png.py <wmctrl 第一列窗口 id> out.png`
   (Qt `QScreen.grabWindow(wid)`, 不依赖 ImageMagick/xwd/import)。
2. **造候选帧** (同一 `_make_env()` 机位 corner2, 480²): ①引擎初始态 ②`sim.run()` 终态
   ③idle 帧 = `node_logic._yolo_ensure_aligner(None).env.render()` (窗口 idle 时回退显示的就是它)。
3. **判定**: `tools/diag_compare_window_render.py <窗口png> <候选png...>`
   = 多尺度 `cv2.matchTemplate` + **绿色光模块像素质心/包围盒**当指纹 (整体相关只作辅助:
   静态背景占比高, 相关 0.85/0.96 这种差距不够判案)。
   实测: 用户窗口窗格 vs 引擎终局 = 相关 **0.9423**, 绿像素 323 vs 319, 包围盒 **逐像素一致**
   (x268~316, y206~246), 质心差 **0.2×0.6 px** ⇒ **他看的就是引擎终局帧** —— 一次排除
   "残留帧 / 另一路源 / 我没抓对窗口" 三种猜测, 不用再问用户。
4. **世界点 → 像素**: `tools/diag_pixel_align_peg_slot.py` 用 mujoco 相机
   (`cam_xpos/cam_xmat/cam_fovy`, 视轴 **−z**, `depth<0` 时 xc/yc/depth 整体取反) 投影
   光模块两端/孔口(mouth)/终点(goal)。**必须自检**: 投影的光模块中心要落在渲染图绿像素质心附近
   (本次 3~4px) —— 相机/投影没验过就不许下结论。
   终局实测: 孔口到光模块轴线 **0.3px** (图里也是同轴), 绿像素 x 258~304 / y 198~236。
5. **纯文本"看图"替代法** (场景很小: 24cm 的杆在 480² 里只占 ~35px, 只能定性):
   - `tools/ascii_render.py <png>` → 96×48 字符, 绿=P / 亮=# / 中灰=· / 暗=空格;
   - `tools/zoom_insert_region.py <png> x0 y0 x1 y1` → 逐像素色类 (G=绿体 R=红内层 W=亮木纹 B=蓝碰撞体 K=暗);
   - `tools/diag_ascii_geom_overlay.py` → 把 孔口/终点/光模块两端 **投影点当标记叠在字符画上**,
     直接读"光模块 vs 插槽"的像素关系。

## 二、metaworld 官方语义 (判"插进去没有"的权威口径, 别再自己定标准)

- **光模块站点/偏置** (`metaworld/assets/objects/assets/peg_insert.xml`):
  `pegHead (-0.1,0,0)` · `pegEnd (0.1,0,0)` · `pegGrasp (0.03,0,0.01)`
  ⇒ `head_off = pegHead − pegGrasp = (-0.13,0,-0.01)` —— **正好是 DreamView3D 里写死的默认值**,
  说明那个常量来自老资产口径, 不是拍脑袋; `_PEG_CENTER_OFF=[-0.03,0,-0.01]` 同理 (中心相对 pegGrasp)。
  光模块 = box half-size `0.015/0.015/0.12` + euler 转 90° (长轴=世界 x) ⇒ **3×3×24cm**。
- **官方成功判据** (`metaworld/envs/sawyer_peg_insertion_side_v3.py:115`):
  `success = obj_to_target <= 0.07`; `obj_to_target = ||(pegHead − target)·(1,2,2)||`;
  `target = _target_pos = pos_box + [0.03,0,0.13]`; 且 `model.site("goal").pos = _target_pos`。
  ⇒ **引擎"光模块头 → goal"这个插入终点与官方语义一致** (实测头到终点 0.8mm = 官方口径达标),
  不是"插得不够"的 bug。
- **盒/槽几何** (`peg_block.xml`): 插槽 = 两块 6cm 立柱 (local x=∓0.06, size `0.03/0.096/0.03`) 之间的
  通道 (世界 y 净宽 6cm × 高 6cm × 沿 x 19.2cm 贯通); 洞口 site `hole` 在 local `(0,-0.096,0.13)`
  = 盒体 90° 旋转后的 **世界 +x 面** (唯一开口); 碰撞体材质**半透明蓝** (0.3,0.3,1,0.5),
  可见外壳 = 木纹 mesh + 红内层 mesh。
  ⇒ corner2 视角下 24cm 的杆只有 ~6.6cm 进洞、剩 ~17cm 横在盒外 —— **这在官方任务定义里就是"已插入"**,
  人眼极易读成"没插进去 / 横向差一段"。
  **动代码前先问清用户指哪一种**: ①"只进去一小截"(= 终点定义/期望更深的语义分歧, 改终点要重标+同口径对照)
  ②"杆与孔中心线错开"(= 真偏差, 用第一节的像素法定位到 mm/px)。
- **盒子几何在子 body 上**: 该 env 的 `body("box")` **geoms=0**, 9 个 geom 全在同名 **unnamed 子 body** (#35)
  ⇒ 按 `body("box")` 找盒体/立柱会一无所获 (本次白跑两轮); 要全模型扫 `m.ngeom` 或遍历 children。
- ⚠️ **布局每进程漂移 (用数字再确认)**: 同 seed 104 — 进程 A 立柱 y=0.5696/0.6896,
  进程 B y=0.3644/0.4844 (盒体 y 0.6296 vs 0.4244)。⇒ **跨进程的几何/像素数字不可比**;
  要复现"用户看到的现象"就在**同一进程**里同时量窗口与真值, 或落 1Hz 取证文件
  (`/tmp/ss_live_frame.json`: `step/stage/depth_mm/lateral_mm/grasped/peg/hole/goal/viewer_consumed`)。
- 判别"这轮到底插没插"的三级口径 (打印时全给): 站点真值 (引擎以为) → **几何体真值** (用户眼睛看的)
  → **像素** (图里关系)。本次终局三级全一致: 深度 65.7/66.0mm · 相对插槽中心线横向 0.2mm ·
  图里孔口到轴线 0.3px。

## 三、本次留下的诚实缺口 (下次接着做)

- 用户坚持"横向有偏差", 而三级口径都指向对齐 ⇒ 剩下唯一未验证的假设是**语义分歧 (只进了一小截)**。
  已请求用户二选一确认; 若确认是"没插到槽里"的期望差异, 改法 = 插入终点按**杆体/夹持点**重标
  (同时改完成判据) + 跑同口径 A/B 对照, 并注意 L3/L4 full 链收尾本来就是"拔出→AOI→放回台面"。
- 复查提示: 改终点前先确认 `_stage_target()` 里 `插入` 段② (`self._goal_p() - off`) 与
  `_insert_depth()` 判据 (≤2mm 算完成) 是同一套语义, 别只改一个。
