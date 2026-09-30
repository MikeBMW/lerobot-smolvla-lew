# 表面「判据图」v12.1 —— 算法 / 参数 / 验收口径 (2026-09-30)

需求: 把光模块**整体切出来 + 调平 + 去背景**, 像金手指判据图那样只留模块; 另给「整板原图」一个按钮。
实现位置: `~/aoi_v4/cam_surface_10083_work_v12.py`(部署后落到工控机 `cam_surface_10083_work_v6.py`,
内容即 v12.1) + 4060 侧 `tools/cam_live_stream.py` / `tools/web/station.html`。

## 场景实测(2448x2048 原图)

- 背景是**暗机台**(灰度 21~63); 光模块 = 横向长条, **顶面过曝到 250~255**(无内部纹理)。
- 模块直段约厚 165~180px; 右侧 x≳1820 起并入**同为 255 的亮白台面/夹具** ⇒ **亮度分不开**, 只能靠固定 ROI 右界拦住。
- 左端 x 380~545 是连接器头(青蓝金属, 灰度 ~187) ⇒ 阈值 200 切不出来, 要放宽到 170 才并得进来。
- 倾角: 上边缘**中段**(x 1050~1450) 是干净直线, 残差 <1px; 整条拟合残差 ±100px 是脏的(左端被雾带/爪子污染,
  右端与台面同亮度) ⇒ **只信干净的直线段**, 不要全段拟合。

## 算法(定案)

1. 固定 ROI `x[330,1815] y[960,1440]`(站位固定; 右界 1815 就是用来排除亮白台面的)。
2. **估倾角双法互校**:
   - A = 上边缘**滑窗找最直 400px 段**的直线斜率(要求残差 ≤3px)
   - B = ROI 内 `g>200` 掩膜最大轮廓的 `minAreaRect` 角度
   - `|A-B| ≤ 1.5°` 才用, 取均值; 否则判失败(实测本机 A=-3.893° / B=-3.995° ⇒ 用 -3.944°)。
3. 反旋(`getRotationMatrix2D(ROI 中心, ang)`, 边界填背景灰) → 旋后 `g>170` 连通域并集(≥1500px, 含左端连接器头)
   → 外接框 → 留 12px 边 → **定尺 letterbox 到 1600x300**(比例保持, 模块水平居中)。
4. 交付 meta: `judge_ok` / `why` / `rot_deg` / `angA_deg` / `angB_deg` / `module_bbox_rot` / `module_aspect` /
   `cover_frac` / `border_med`(四边留边亮度) / `bg_median` / `ms`。

**失败闸门(绝不硬裁)**: 亮条点太少 / 最直段残差>3px / 两法差>1.5° / 模块 <400x60 / 画布边缘发亮(>max(120,bg+60))
⇒ `judge_ok=False` + `why`, 调用方**回退全幅规范图**并在日志告警。

## 验收证据(本机实测)

离线(`~/aoi_v4/test_v12_1_judge.py`, 桩相机喂真原图, **21/21 通过**):

- 真图: 1600x300 · 留边 24~35 · 覆盖率 0.54 · 判据图上边缘**最直段残倾 0.03°**(残差 0.60px) · rot -3.945°。
- 合成已知倾角 ±3°/±6°: 报出的斜角幅度误差 ≤0.005°, **调平后残倾 0.0°**。
- 失败闸门: 纯背景 / 小亮块 → 不出图且 `why` 非空。
- 模型输入老口径仍在(`Surface_Letterbox_W1280_H1280_*`, kind=crop 仍 1280x1280)。

真机(工控机实拍):

- `POST /capture_detect` → 200; `GET /picture?kind=judge` → 200 / ~37KB JPEG / `X-Frame-Age-S` ~0.02s。
- `/crop_info`: `judge_ok=true` · `judge_rot_deg=-3.874` · `judge_bbox=[362,1083,1453,279]` · `judge_cover=0.5398` ·
  `judge_ms=121.5` · `judge_mode=crop_module_deskew 1600x300` · `model_input_mode=letterbox_keep_aspect 1280x1280`。
- 判据图复验: 1600x300 · 留边 24~33(背景灰) · 覆盖率 0.540 · **上边缘最直段残倾 -0.03°(残差 0.69px)**。
- 4060 两条流: `/aoi_surface.mjpg` → 首帧 1600x300 · `/aoi_surface_raw.mjpg` → 1400x1171; 金手指 900x332 未受影响。

## 坑

- `minAreaRect` / `connectedComponentsWithStats` 返回的是 numpy 标量 ⇒ meta 里必须 `int()`/`round(float())`,
  否则 `/crop_info` 的 `jsonify` 报 `Object of type int32 is not JSON serializable` (实测踩过)。
- 内存帧是 JPEG(92) 编码、落盘是 PNG ⇒ 别断言"逐字节一致"; 正确口径是"尺寸一致 + 逐像素平均差 ≤4"。
- 判据图渲染只加 ~120ms, 可以放在 `GrabAndSaveImage` 里同步做。
