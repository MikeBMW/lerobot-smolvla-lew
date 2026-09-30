---
name: zmax-aoi-service
description: Use when 调用产线 AOI 检测服务(10082 金手指/10083 表面).
---

# 产线 AOI 检测服务 (Z-MAX, 工控机 192.168.23.23)

与 Orin 同网段(192.168.23.x)。跑两份 Flask 程序「Z-MAX 表面检测 AOI 程序 · 优化版 v3」,
**端口→模型映射**决定检测类型。

## 端点（唯一路由, 无需参数/鉴权）

| 端口 | 模型 | 相机 SN / 型号 |
|---|---|---|
| **10082** | `gf` = 金手指 | D265250070 「金手指检测相机 OPT-CC1-GG50」 |
| **10083** | `housing` = 表面 | D265250099 「表面检测相机 OPT-CC1-C050-GG3-00」 |

```bash
curl -s -X POST http://192.168.23.23:10082/capture_detect   # 实测 0.53s
# {"code":200,"msg":"success"}
```

## 语义（关键）: 纯异步, 秒回

1. 相机**常驻**(首次请求初始化, 之后只 Grab)
2. 拍照 → 存到工控机的 `./goldfinger_images/`(10082) 或 `./surface_images/`(10083)
3. **立即返回** `{"code":200,"msg":"success"}`（不阻塞产线节拍）
4. YOLO 推理在后台线程跑, **检测结果只打印在工控机终端** ✗ API 不返回结果

## 所以: 要拿到"检测结果"必须补一条通道

- 现状: 结果(缺陷数/OK-NG/类别/conf/bbox)只出现在 .23 的终端 stdout ✗
- 可选: ①请 web 侧在同一个 Flask 里加结果端点(如 `GET /last_result`, 把 worker 的最近结果存全局) ②或读 `./goldfinger_images/` 里的原图自行推理
- 本机(4060)与 Orin 都只能**触发**拍照检测, 拿不到判决 —— 这点要在对外表述里说清, 不能假报 OK/NG。

## 10082 金手指"规整截取" (v4 模板法, 2026-09-20 实测)

### 老版(v2/v3)截取为什么"歪歪扭扭" —— 三个叠在一起的原因
1. **固定透视窗** `src=[[400,1000],[2000,1000],[2000,1250],[400,1250]]` 与实际金手指条对不上:
   条中心 y 在 **1008~1450** 之间漂移(≈400px),条本身还带 **+0.6~1.0° 倾角** → 窗子时上时下地切过条。
2. **输出尺寸被静默拉成原图尺寸**: `warp_goldfinger_topview()` 里 `out_w=None → out_w=img_w`,
   调用处没传 out 尺寸 → 物理上是 1600x250 的窗被拉到 **2448x2048**(横向1.53x/纵向8.2x拉伸)。
   文件名却一直写 `W1600_H220`(**名字在撒谎**, 内容从来不是 1600x220)。
3. 真值口径: 金手指条实测 **1441x59 px @(1200,1222)**, 倾角 +0.60°(质心线残差 0.11px)。

### v4 做法 (模板法)
- 模板 = 参考真图去倾斜后的**条 ROI**(居中存放): `templates/gf_strip_template.png` + 同名 `.json`(条几何 sidecar)。
  相机/产品换了就重做: `python gf_template.py <新参考图>`
- 运行期三段: ① 1/4 尺度多角度粗搜(±3°, 步0.5°) → ② 1/1 尺度局部窗精修(角度±1°步0.1° / 尺度 0.97~1.03)
  → ③ **角度扫描精修**: 直接以"裁剪图里条质心线斜率"为目标度量扫 ±1°(热启动 ±0.25°), 把斜率压到 ≈0
  → ④ 单次仿射映射到规范化画布(保比例: 1600xauto, 条固定落在 x[48,1552] / 行[43,127])
- 交付物: `cam_finger_10082_work_v4.py` + `gf_crop.py` + `gf_metric.py` + `templates/`
- 新端点 `GET /crop_info` = 最近一次裁剪的 score/残余倾角/线残差/金覆盖率/角度扫描曲线; 终端每个周期打印同一组指标

### 实测(5 张真图, 同一批 goldfinger_images)
| 方案 | 条质心线斜率 px/1000 | 残差px | 备注 |
|---|---|---|---|
| v3 现状(拉 2448x2048) | 18.6 ~ 37.0 | 122 ~ 152 | 歪 + 8.2x 纵向拉伸 |
| v3 按设计(1600x220) | 2.4 ~ 7.2 | 10.8 ~ 17.6 | 只是不拉伸了, 仍是固定窗 |
| **v4 模板法(保比例)** | **0.09 ~ 0.89** | **5.0 ~ 5.4** | score 0.954~0.990, 冷启~500ms/热启 130~143ms |

### 踩过的坑 (再做同类截取直接抄)
- **HSV 金色掩膜在本机台上不可靠**: 宽阈值 `(8,60,50)-(45,255,255)` 把无关黄色区域也选进来(全图 1.4~2.4% "金"像素里约一半是杂的),
  严格阈值 `(15,120,120)` 只剩 **10 个像素** → **别把 minAreaRect/颜色掩膜当定位主手段**, 只能当兜底。
- 用"最大轮廓"量条会随闭合核大小跳变(核(61,5)→1559x164 / 核(41,5)→1455x98); 改用**逐行/逐列剖面 + 分位数**定边界稳得多。
- "顶边"当规整度判据太脆(顶边残差 ~11px, 含焊盘本身的台阶); 改用**质心线**(每列金像素质心行)残差 ~5px, 斜率也亚像素级。
- `cv2.getAffineTransform(dst, src)` 再 `warpAffine`(不带 `WARP_INVERSE_MAP`) = **双重反变换**, 结果裁到空图/黑图。
  标准写法是 `getAffineTransform(src, dst)` → `warpAffine`。
- **平纹理会给假高分**: 模板若大部分是平坦背景, NCC 处处 ≈0.99 → 出现 "score 0.988 但裁剪里一个金像素都没有" 的假成功。
  终判据必须是**裁剪内的实质指标**(金覆盖/质心线有效性), 不能只看 score。
- 首次别把"角度闭环"做成符号猜测试探(会发散: 角度从 0.6° 跑到 -2.6°, 斜率反而变差); 改成**扫描目标度量取最小**是确定性的。

### ⚠️ 风险 + 上线方式(必须与现场确认)
检测模型 `gf: bestgf05088.pt.enc, imgsz=960, conf=0.30`(config.yaml) 的**训练输入几何未知**;
v4 输出 1600x172 与 v3 的 2448x2048 分布差异很大(焊盘在 960 输入里约 56px vs 原 273px)。
⇒ 若召回下降, 用 v4 口径的图重训/微调该模型(数据闭环有这条路)。

**通道必须保持 10082**(产线 HMI/PLC 打的就是它), 且 **相机是独占设备 —— v3 与 v4 不能同时跑**
(同一台相机 SN,D265250070,第二个打开会失败)。所以是"切换"不是"并行":
1. 在 v3 的终端 Ctrl+C 停掉(或 `netstat -ano | findstr :10082` + `taskkill /PID <pid> /F`)
2. `python .\cam_finger_10082_work_v4.py`(默认就是 10082; 程序启动会做端口占用自检, 被占直接报错退出)
3. `curl -X POST http://127.0.0.1:10082/capture_detect` → `{"code":200,"msg":"success"}`;
   `curl http://127.0.0.1:10082/crop_info` → 本次裁剪的 score/残余倾角/线残差/金覆盖
4. 同一批料比 v3/v4 的检测判决与图; 不行就 Ctrl+C 回滚启动 v3(文件都在, 零改动)
- v4 已把"通道→模型"映射按**实际运行端口**注册, 所以换端口自测也不会再报 400(但产线仍用 10082)
- 换产品/换相机后重做模板: `python gf_template.py <新参考图>`

## 区域检测 → 机械臂视觉伺服对准 + 自动对焦 (2026-09-20 交付)

### 接口语义 (现场要求, 别记错)
| 接口 | 语义 |
|---|---|
| `GET /picture` | **原始图** 2448x2048 (默认; `?kind=crop` 才是规整裁剪图) |
| `GET /crop_info` | 裁剪结果指标 (score/残余倾角/线残差/金覆盖/高亮占比) |
| `GET /region?grab=1` | **原始图坐标系的金手指区域**(定向框/四边形/外接框) + 对焦清晰度 `focus` |
| `POST /capture_detect` | 拍照 + 异步检测 (判决仍只打工控机终端) |

### 裁剪边界 v4.2 (现场两轮目检后的口径, 以这版为准)
参考图纵向成分 (No_8, 源像素): 焊盘排 y[1097,1162] (66行, 金覆盖 29.8%, |gx|=28.6 边缘密集=**金手指本身**)
· 缝 y[1163,1179] · **实心金带** y[1180,1265] (86行, 覆盖 64.3%, |gx|=8.3) · 塑料本体亮边沿 y≥1258 (亮度冲到 255)
- 现场口径: **只保留金手指本身** → 取"最上面那片 边缘密集(|gx|≥18) 且 高≥20" 的 run (行密度分 run, 空隙≤6行合并);
  下方实心金带与塑料亮边沿**都不进画布** (第一版把它们裁进来, 现场说"下面多了厚厚的边沿")
- 左右端用**最大金连通域**的 x 范围 (焊盘两端在部分帧里金像素稀疏, 用 run 自己的列剖面会抖 ±90px) → 1455 稳定
- 实测 5 张真图: **1454~1462 x 70~72**, 倾角 0.8~1.0°, 跨帧一致
- ⚠️ 金手指只占 21:1 太扁, YOLO 会压成一条细线 → 规范化画布默认 **960x960 方图**
  (与 `yolo_detector/config.yaml` 的 `imgsz=960` 对齐: 不做 letterbox 也不上采样), 金手指纵向**拉伸填满**;
  同时另存一份"原比例 1455x70"版供目检 —— 两版都落盘 (`Finger_TopView_W960_H960_*` / `Finger_CropNatural_*`)
- **规整度指标必须在"原比例版"上算**: 拉伸 13 倍的画布会把斜率也放大 13 倍, 口径失真

### 规整度判据 (口径统一, 别再用整幅)
只在**实心金带核心行**（行密度 ≥95% 峰值 ±3 行）上拟合金像素质心线 → 斜率 = 残余倾角。
用整块 ROI 会被上排离散焊盘带偏（实测 −5~+2 px/1000），用核心行则一致 ≈0（三套掩膜口径都验过）。
v4.2 实测（原比例版）：**−0.94 ~ 0.61 px/1000**；v3 现状 0.87~1.02（整幅残差 98px）。

### 伺服 (tools/aoi_gold_servo.py, 注册名 L2.aoi_gold_align)
- 控制律: 误差 `e=(cx-cx*, cy-cy*)`px → `Δarm = -M·e` (**符号必须为负**: M 是"臂动1mm图像动多少px"的逆,
  要消掉偏差得让图像反向移动 e; 离线测试①专门抓这个符号, 写成 +M·e 会越跑越偏)
- 对焦: 沿光轴 L2.lift/lower **退火爬坡** 0.8→0.4→0.2mm, 判据 = 区域内 Laplacian 方差, 变差则退回+反向, 峰值停
- 雅可比 M 由 `calibrate` 现场量 (沿臂 X/Y 各推 1mm 看区域中心移动多少 px)
- 四级闸: ①授权(默认 dry-run, 真动要 --authorize) ②检测可靠(score≥0.85 且 金覆盖≥0.45) ③限幅(单步2mm/单轴15mm/25次)
  ④跳变闸(实测位移 vs 雅可比预期 >3× 立即停) — 全在 L2 收口, 脚本自身无自研运动学
- 现场三步: `check`(只读) → `teach`(人工摆最佳视角记基准) → `calibrate --authorize` → `serve --authorize`
- 基准/雅可比: `data/skills/l2_atomic/aoi_gold_target.json` (data/ 被 gitignore, 属运行时状态)

### 第二阶段: 换成 YOLO 区域检测 (数据自动标)
`tools/aoi_gold_region_label.py` 用模板法几何当**真值框**自动标注 (低可信 score<0.90 或 覆盖<0.45 自动挑出人工复核),
产出标准 YOLO 检测集 (`0 cx cy w h` + data.yaml + manifest.jsonl); 实测 5 张真图 5 标好/5 张裁剪图正确判低可信。
训练: `yolo detect train data=data/gf_region_ds/data.yaml model=yolo11n.pt epochs=100 imgsz=960`。
注意: 模板法给的是定向框, 现落成轴对齐框(含 ±1° 旋转外扩~21px); 要更紧改 OBB 旋转框数据集。

## 状态空间侧接线（2026-09-20, 老倪问「状态空间的 AOI 技能同步了吗」→ 已对齐）
- **L2 注册表** `data/skills/l2_atomic/registry.json`（技能清单对话框读它）当前 9 条 AOI 技能：
  金手指拉长图(喂YOLO) `?kind=crop` · 金手指原比例图 `?kind=natural` · 金手指区域检测 `/region?grab=1` ·
  裁剪质量指标 `/crop_info` · **金手指对准+自动对焦 `L2.aoi_gold_align`(ros=script, dry_default)** ·
  金手指AOI检测 `POST /capture_detect` · 表面AOI · 图片 · 实拍
- **画布 `ssaoi` 节点**: desc 写 v4.2 口径 + `crop_geometry_v4_2`(焊盘排 1455x70 → 960x960, 明确排除下方金带/亮边沿) + `aoi_interfaces`(5 个 URL + 伺服技能); 改前先备份, 校验**节点 83 / 连线数零变化**
- **技能清单图片预览**: `tools/gui/l2_skill_dialog.py` 的预览原来写死 `/picture` —— 而那个口按现场要求已改成**原始图**,
  所以老倪会问「技能清单里怎么看不到拉长后的金手指」。已加「来源」下拉(拉长960 默认 / 原图 / 原比例), 双击任意 `L2.aoi*` 都会刷新。
  ⚠️ **GUI 改码必须重启 studio 才生效**(无 autosave); 重启后 `ps` 查双开。
- 相关: `tools/l2_daemon.py` 执行器对注册表 mtime 热加载(改技能不用重启), 但 **GUI 的 .py 改了必须重启**

## ⚠️ 诊断: "AOI 图片没传过来" = 服务端本轮无拍照记录 (2026-09-23 实测)

现场症状: 画布/技能清单的 AOI 图片预览空白, 像是"图没传到本机"。**不是网络问题** ——
`.23.23` ping 0.3ms, 10082/10083 端口都开, 服务进程在跑。逐接口探 (只读 GET, 不打 capture):

| 接口 | 无拍照记录时的返回 |
|---|---|
| `GET /picture` | **404** `{"code":404,"msg":"尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}` |
| `GET /picture?kind=crop` | **404** (同上; crop 依赖最近照片) |
| `GET /crop_info` | **404** `尚无裁剪记录` |
| `GET /region` | **404** (尚无照片) |
| `GET /picture?kind=natural` | **200 image/png** ✅ (命中落盘的历史原比例图, 135KB 级) |
| `GET http://…:10083/picture` | 404 Flask 默认 HTML 页 → 10083 那套**没有 /picture 路由** |

⇒ 根因: **Flask 进程内存里的 "最近照片/裁剪" 为空** (刚重启过 / 本轮没触发过拍照)。
GUI 技能清单预览默认取 `?kind=crop` → 默认必 404 → 看起来"图没传过来"。

**⚠️ + 该记录会过期 (2026-09-23 实测)**: 19:04 触发拍照后全接口 200; **55 分钟后** (无新拍照)
`/picture` `?kind=crop` `/crop_info` `/region` 全部回到 404, 只有 `?kind=natural` (落盘图) 仍 200。
⇒ 任何"看图/检测"前都必须**先触发一次拍照** (`POST /capture_detect` 或 `?grab=1`), 不能复用上次。

**⚠️ 技能清单点 L2.aoi* 不会下发 (2026-09-23 修)**: `tools/gui/l2_skill_dialog.py::_go()` 原来
开头就把 `id.startswith("L2.aoi")` 全部 `return`(只刷新预览) → 点「金手指AOI检测」永远不 POST,
表现就是"点了没反馈"。已改为 **双击=预览 / 「开始」按钮=真下发到常驻执行器** (http → POST),
并回显执行器返回 + 自动刷新这次的图。GUI 改码需重启 studio 生效。
验证通道 (不下发运动、只读): 往 FIFO 写 `{"skill": "L2.aoi_crop_info"}` → 4s 内 `~/zmax_data/l2_daemon.log`
出现 `HTTP ... → 200/404 ...` 回显 —— 这条就是 GUI 会显示的"反馈"。

处置: ① 触发一次拍照 (需用户同意, 真拍产线台): `curl -X POST http://192.168.23.23:10082/capture_detect`
或 `GET /picture?grab=1`; 之后 `/picture` `?kind=crop` `/region` `/crop_info` 全部有内容。
② 只想看历史图不拍照 → 预览源切 `金手指原比例(?kind=natural)` (落盘图, 不受内存状态影响)。

## 🆕 路由真相 (2026-09-23 用 OPTIONS 探明, 不用拍照)

`curl -X OPTIONS -D - http://192.168.23.23:<port><path>` 只看 `Allow:` 就能判定路由存在与否 (零副作用):

| 端口 | 存在并可用的路由 |
|---|---|
| **10082** 金手指 | `POST /capture_detect` · `GET/HEAD/POST /picture` · `GET /crop_info` · `GET /region` · **`GET /last_result`** ✅ |
| **10083** 表面 | 只有 `POST /capture_detect` (无 /picture /crop_info /region /last_result);
  55 条候选路径已穷举确认(2026-09-27) |
| **10081** | **与 AOI 无关** (上述路由全 404 → 不是相机程序, 不构成对金手指相机的抢占嫌疑) |

**`/last_result` = 判决通道其实存在** (旧记录"判决只打工控机终端、API 不返回"已过时)。无成功检测时回
`{"code":404,"msg":"尚无检测结果"}`; 相机恢复+拍照成功后应能取到 OK/NG/缺陷数 → GUI 可直接显示, 不必再靠终端。

**故障归因排除表 (2026-09-23 20:45~20:55 实测)**: 网络✅(ping 0.3ms/端口开) · 10082 进程路由✅ ·
10081 抢占❌(路由无关) · 表面相机✅(10083 POST 200) → 只剩**金手指相机 D265250070 本身**:
被另一程序独占(常见: v3 与 v4 同开, 同一 SN 第二个打开必失败) / USB 掉线 / 未上电。

## 🔎 一键体检工具 `tools/aoi_health.py` (2026-09-23 落地)

```bash
cd /home/ubuntu/lerobot-smolvla-lew
./gui-venv311/bin/python tools/aoi_health.py          # 只读(不拍照)
./gui-venv311/bin/python tools/aoi_health.py --grab   # 含抓帧项(会真拍, 需现场同意)
```
逐项打印 ①触发拍照 ②实拍原图 ③拉长960 ④原比例 ⑤区域 ⑥指标 ⑦表面, 含 HTTP/msg/**图的尺寸+亮度**,
并把 500 的 `相机初始化失败` 直译成现场动作。**区分单台相机故障**: 若 ⑦表面(:10083) 200 而 ①金手指(:10082) 500
⇒ 工控机 Flask 与网络都好, **只有金手指那台相机 (SN D265250070) 坏/被独占**(两套程序抢同一台相机是常见诱因)。

**故障态实测对照 (2026-09-23 20:45)**: ①`500 相机初始化失败` · ②`500 相机初始化失败` · ③`404 尚无照片` ·
④`200 但 18x364 mean=39`(落盘旧残图, 不是金手指条) · ⑤`500` · ⑥`404 尚无裁剪记录` · ⑦`200 success`。
⇒ 「看图技能没图片」的三种不同表现 (500/404/旧残图) 其实同一个根: 金手指相机拍不了。

## 🔥 曝光: 工控机拉伸图 73% 死白 → 原始图自裁 (2026-09-24 老倪现场发现, 必读)

**症状 (真拍实测 10082)**: `?kind=topview` (工厂规整拉伸图) **73% 是死白** —— y≥255 起逐行亮度**恒在 238.5±0.5**、
饱和像素(≥250)占 **61.5%**、死白行 **532/960**、最差列饱和 **100%**、细节能量 Tenengrad 仅 **2300**;
底部出现不自然强光边缘 (Cliff edge, 原始图 y≈582 处 12.1/行跳变, sat 带 y 592~1184)。
老倪原话: 「灰度信息丢失(过曝), 底线到 255 纯白, 明暗细节/纹理/衬度完全消失」。

**修法 (4060 侧, 无需工控机改动, 已上线)**: **别用工控机的拉伸图, 改从 `?kind=origin` 原始图自裁**
(`tools/aoi_exposure_fix.py::clean_judge_frame`):
1. **行方向**: 切掉过曝带 (行 sat>40%, 实测 213 行) → 只留"边缘密集(P92) 且高≥20 行"的金手指条 (实测 y 948~1147)
2. **列方向也裁** (⚠️ 只做行裁会留 100% 饱和的边列, 实测最右 10 列饱和 100%) → 裁到条自身 x 范围 (实测 x[433,2056])
3. 归一化到 head 的 imgsz; 台账如实记录 (裁掉行数/保留区间/列裁/cliff/规则)
**实测效果**: 饱和 61.5%→**5.6%** · 死白行 532→**0** · 最差列 100%→31.2% · Tenengrad 2300→**29394 (×12.8)**
命令行诊断: `./gui-venv311/bin/python tools/aoi_exposure_fix.py <origin.png>` (打印逐行剖面/过曝带/cliff/条带候选)
窗口: 「过曝切除」勾选 (默认开, 可关掉对比工厂图)。
**根治仍建议工控机侧降曝光/增益** (`set_exposure/set_gain` 或 config.yaml): 验收 sat 条内 ≤5%、无列 >60%。

## 🆕 OPT 相机取图客户端 + 外观质量检测窗口接入 (2026-09-24 实测, 老倪需求)

**链路**: Orin `192.168.23.66`(tashan) / 本机 `192.168.23.50` ──HTTP──> 工控机 `192.168.23.23` ──> OPT 相机
（实测 Orin→工控机 **0.82ms**; 本机直连 **1.8ms**; 两条通道读到**同一条判决**, `t` 逐位一致 → 双通道等价）

**工具 (已交付, 直接复用)**:
```bash
cd ~/lerobot-smolvla-lew
./gui-venv311/bin/python tools/opt_camera_client.py --health            # 只读: 路由 + 判决 (零副作用, 不拍照)
./gui-venv311/bin/python tools/opt_camera_client.py --last-result       # 工控机自家判决
./gui-venv311/bin/python tools/opt_camera_client.py --cam 1 --grab --out /tmp/a.png   # ⚠️ 真拍 (--via orin 走 Orin)
./gui-venv311/bin/python tools/verify_opt_camera.py --authorize         # 全链取证 (11/11)
```
窗口入口: 画布右键「🔍 外观质量检测」→「打开质量检测终端」→ **源=🏭 OPT 相机** + 相机(金手指10082/表面10083)
+ 通道(本机直连/经 Orin) + `📸拍帧`(真拍) / `🖼最近图`(不拍) / `📋工控机判决`(同表对照, source=opt-工控机)。
**纪律**: OPT 源**绝不自动真拍**(需手动点), 不批量轮询; 每次真拍写审计 `reports/opt_capture_log.jsonl`。

**实测真图 (金手指 10082)**: `POST /capture_detect` 1109~1626ms → `GET /picture?kind=topview` =
**960x960, 灰度均值 204, std 72.5, Tenengrad 2304, 749KB, 15.3ms** (真实结构, 非空白帧)。
`/last_result` 实测有数据: `verdict=OK count=0 detect_type=gf`。

**⚠️ 判据坑 (会误报的两处)**:
1. `/last_result` 刚重启服务返回 **404 `尚无检测结果`**(内存空) → **不是故障**, 拍照后才变 200。
   断言必须容纳**两种合法形态**: `200 + verdict/count` ‖ `404 + msg`。
2. **ARP 抖动**: 邻居表 `STALE/DELAY→FAILED` 期间 curl 瞬时 `rc=7 / http=000 / t=0.0003s`, 而 ping 同时正常 →
   重试即可, 别急着归因"服务挂了"(本次实测就是这样: 1 分钟后自行恢复)。

**10083 表面相机缺口**: 只有 `/capture_detect`, **无 `/picture`** → 只能触发拍照拿不到图。
补丁已写好交工控机侧: `docs/patch/opt_surface_10083_add_picture_route.md` (粘 30 行 + 现场 4 步验证)。
补齐后 4060 侧**零改动**即可取表面图 (`CAMERAS[2]["has_picture"]` 自动为 True 的那天, 只需改这一处标记)。

## 🧪 判决语义 + 模型输入 + 飞书推图 (2026-09-24 全部实测, 必读)

**① `POST /capture_detect` 返回 `{"code":200,"msg":"success"}` ≠ 合格！**
程序流程: `ensure_camera()` → `GrabAndSaveImage()` → 写 `_LAST_PIC` → `_enqueue_detect(topview, origin, type)` → **立即 return 200**
（源码里那行打印就是「📸 已拍照, 投递检测队列 (不阻塞动作)」）。200 只表示"拍照成功 + 检测已进队列"。
**真判决在后台 worker 线程**（`_detect_worker_loop`）: `detector.detect()` → 缺陷数/OK-NG →
只打在**工控机终端** + 存进 `_LAST_RESULT` → **用 `GET /last_result` 读**（verdict/count/defects/ms/n + origin/topview 文件名）。
老倪问"为什么反馈成功/是不是调 yolo"时, 用这条回答: 200 是受理, 判决在 /last_result。

**② YOLO 检测的是"裁减图", 不是原图**（实测证据链）:
- `cam_finger_10082_work_v3.py:399 _enqueue_detect(img_topview_path, ...)` → `:318 result = detector.detect(topview_path, ...)`
- `/last_result.topview` == `/crop_info.crop_file` == `Finger_TopView_W960_H960_No_<n>.png`（同名）
- `/crop_info.canonical = [960,960]` 与模型 `imgsz=960` 1:1
- ⇒ **裁减/规整质量直接决定召回**: `crop_info.score` 实测 0.4378（v4 模板法验收口径 **≥0.95**, v3 固定窗约 0.29）
  ⇒ 裁减 score 低时"OK"不可信: 模型根本没看全焊盘。交叉验证要**同口径**（我们的启发式阈值不是方图口径, 直接跑会假阳性）

**③ 判据图口径 (4060 侧窗口)**: 手动框选(永远优先, 与"过曝切除"开关解耦) > 原始图自裁(切过曝带/死白列) > 工控机拉长图(显式告警)。
**拉长 = 短边×2, 长边不动**（原来的 2448x2048/960x960 方图 = 纵向 8~13 倍, 现场判"太长了"）。
圈选状态每次拖框自动落盘 `reports/aoi_console_state.json`（roi/k/来源/判据图尺寸/框内饱和·死白行·Tenengrad）——
  **Agent 看不到屏幕, 就靠这个文件核对"人圈的是哪一块"**；`🎯 识别金手指并框` 可一键用算法兜底。
⚠️ 两个已修真 bug（都属"看了不算数"类）: ① 手选框被"过曝切除"开关挡掉 → 掉回工厂图 ② 手选框只换显示、没换 `_last_rgb`
  → **任务头推理仍在旧帧上跑**; 另: 500ms 定时器曾把工厂图重新塞回判据图面板, 覆盖显式结果 → OPT 源画面只在显式取图时更新。

**④ 把裁减图实时推飞书**: `tools/aoi_feishu_push.py`（飞书原工具只有 text/media, 无图片）
```
POST /open-apis/im/v1/images (multipart: image_type=message + image) → image_key
→ POST /im/v1/messages  msg_type=image  {"image_key": ...}   (+ 说明文字另发一条)
--once [--grab] [--ours]      # 推最新裁减图; --grab 才真拍; --ours 连自裁判据图一起
--watch --interval 8          # 盯 /last_result 的 topview 文件名变化 → 新拍照自动推 (只读, 绝不触发拍照)
```
token **每次现取** → 不依赖 gateway 进程内缓存（gateway 报 99991663 时本通道照样能发）。
实测: 文本 code=0; 图 image_key=img_v3_... code=0 message_id=om_...; 监听实推 No_288 ✅

**⑤ 补丁交接单**: `docs/patch/opt_surface_10083_add_picture_route.md`（10083 无 /picture 取不到图）·
`docs/patch/opt_10082_gold_stretch_2x.md`（拉长短边×2 + 窗按原比例 + 文件名写真实尺寸）

## ❌ 10083 表面相机取图: 已穷举到底 (2026-09-27, 别再重复试)

老倪反复问「10083 还是没有信号」。三条路都试到底了(全部零副作用/只读):
1. **10083 上 55 条候选路径逐个 `OPTIONS`** (`/picture` `/image` `/snapshot` `/stream` `/static`
   `/surface_images` `/last_result` `/camera` `/get_picture` 拼音名…): **只有 `/capture_detect`**
   (`Allow: POST, OPTIONS`), 其余全 404。工具: `tools/probe_aoi_routes.py`、`tools/probe_10083_deep.py`。
2. **工控机全端口扫描**(`tools/sweep_opt_host_ports.py`): 没有第二个 HTTP 服务能取表面相机图;
   10081 的 `/picture` 也是 404。
3. **取它落盘的 `./surface_images/`**: 445/139 开着, 但 `smbclient -N` → `NT_STATUS_ACCESS_DENIED`
   (无匿名共享, 本机也没有那台机器的凭据; RDP/SSH 均闭)。
⇒ 结论: 那套 Flask **没实现取图口**。唯一修法 = 上补丁
`docs/patch/opt_surface_10083_add_picture_route.md`(30 行 + 4 步自测)。
**补丁一上, 4060 侧零改动就会出图** —— 面板一直按 0.25Hz 轮询 `GET /picture?kind=origin`,
一有 200 立刻显示。别用别的相机图/旧图冒充这一格。

### 10082 金手指 “没图” 的另一半(已修)
除了“内存里没照片”(404 尚无照片), 面板还要能看到**整板**: 除判据图外另存一张整板缩图
(长边≤1400)。另外加**自动取景**(发现 404 就替它现拍一张、最快 30s 一次、页面上可关)后,
拍后 90s 内即使它又没照片也按**在线**报 —— 否则面板一边显示新图一边写“取图失败”会被人当成坏的。

## v5 (两路) —— 不检测时不落盘 (2026-09-27 老倪「不检测的时候不用保存那么多图片」)

在 v4 基础上生成 (`make_v5.py` 机械变换 + `test_v5_offline.py` 离线契约), **端口/路由/回执语义一字不改**。

| 动作 | 落盘? | 说明 |
|---|---|---|
| `POST /capture_detect`(真检测) | **写盘** | 模型 `detect(path)` 必须读文件 ⇒ 不能省; 写完按上限清旧图 |
| `GET /picture?grab=1`(只看一眼/总览页「拍帧」) | **不写盘** | 图编码后只留内存 (`_MEM`), 磁盘文件数不变 |
| `GET /picture?kind=…`(取图) | 不写盘 | **内存优先**(`X-Frame-Source: memory`), 无内存帧才回落到文件 |
| `GET /picture?grab=1&save=1` | 写盘 | 显式要存才存 |
| 标注图/legacy 图 | 默认不写 | `AOI_SAVE_DEBUG=1` 才写 |

新增两个自查口: `GET /storage`(每类张数/占用MB/上限/内存帧大小) · `POST /prune`(立刻按上限清, GET 只预览)。
保留上限(张, 环境变量): `AOI_KEEP_CANON`=400 · `AOI_KEEP_ORIGIN`=120, 每次落盘后 `_prune_dir()` 删最旧。

**两个必须踩到的实现细节(改 v5 代码时别再犯)**:
- 落盘开关用 `threading.local()` 传(`_TL.save`), **不要用模块级全局** —— Flask threaded=True, 一边 grab(不存) 一边 detect(要存) 会互相翻开关, 后果是检测文件没写 → 模型读不到 → 检测失败。
- 内存帧分支必须放在 `/picture` 的 `if not os.path.exists(path): return 404` **之前**, 否则 grab(save=False, 没有文件) 会先 404 ⇒ 不落盘的图永远看不到(实测就是这个坑)。
- 金手指那路原图不是 `cv2.imwrite` 而是 SDK `SciCam_Payload_SaveImage` ⇒ 全局替换 `cv2.imwrite`→`_iw` 时**别把 `_iw` 自己的实体也替换掉**(会递归爆栈: `maximum recursion depth exceeded in comparison`); SDK 落盘要单独加 `if _tl.save` 判断。

上线包 `http://192.168.23.50:8794/v5/`(旧 v4 URL 仍可用): 两程序 + `upgrade_aoi_v5.ps1`(自检 / 试跑 10084·10085 / `-Apply` 正式升级) + README + sha256。
离线自测: `cd ~/aoi_v4 && .venv-test/bin/python test_v5_offline.py` → 两路各 5/5。

## 🆕 工控机重启后 10083 表面 AOI 不自己起来 = 计划任务被禁用 (2026-09-30)

症状: 10081/10082 在听、**10083 closed**(`/dev/tcp` 探测), 本机 8793 表面格 `online=false frames=0`;
`ZMAX_AOI_KeepAlive` 的日志 `zmax_keepalive.log` 停在某个历史时间点且**没有任何新行**。

根因: 计划任务被置为 **已禁用** ⇒ 工控机一重启, 10083 再没人拉(它不像 10082 那样被别的机制带起来)。
两条取证命令(中文 Windows 下 `schtasks /query /v` 的字段名是中文, 用 `Select-String '状态|上次'` 匹配英文会**空手而归**):
```powershell
(Get-ScheduledTask -TaskName ZMAX_AOI_KeepAlive).State                    # Ready=启用 / Disabled=被禁
(Get-ScheduledTaskInfo -TaskName ZMAX_AOI_KeepAlive) | Select LastRunTime,LastTaskResult
```

修法(从 4060 走反向通道, 一条命令):
```bash
./gui-venv311/bin/python tools/station_cmd.py "schtasks /change /tn ZMAX_AOI_KeepAlive /enable; schtasks /run /tn ZMAX_AOI_KeepAlive" 90
```
⚠️ **起服务慢: 实测从 run 到 10083 LISTEN 约 89s**(首抓失败要重连相机) —— 45s 就去看端口会误判成"没起来",
  然后手搓再起一份(相机独占 → 抢相机/端口占用)。**等 ≥90s 再验**。
- 验活: `(Get-NetTCPConnection -State Listen | ? {$_.LocalPort -in 10082,10083}).LocalPort` + `GET /storage`=200。
- keepalive 拉起的正常形态是**两个 python 进程**: venv 解释器(启动壳, 父=cmd) + 它换成的 Python310 实例(**端口属主**)。
  看见两个别当重复副本杀错 —— 端口属主那个才是活的。
- 该脚本本身只"动手时才写日志", 所以"日志没有新行"≠"任务没跑"; 判活要看任务 State/LastRunTime + 端口/`/storage`。

## ⚠️ 两个必踩的坑 (2026-09-27 现场踩过, 改 v5 代码/排障时先看)

**① 取图路由缺"重连再抓" ⇒ 冷启/空闲后稳定 500「抓帧失败」**
- 现象: `/storage` 200 · `POST /capture_detect` 200 且 `/last_result` 判决正常(n/ms 推进) · `/picture?kind=origin`(不带 grab) 200,
  但 **`GET /picture?kind=origin&grab=1` 稳定 500 `{"code":500,"msg":"抓帧失败"}`**(每次卡 ~5.0s) ⇒ 总览面板/技能预览没图。
- 根因: `GrabAndSaveImage` 里 `SciCam_Grab` **冷启或空闲一段后首抓就会失败**返回 (None,None);
  `/capture_detect` 一直有兜底("⚠️抓帧失败 → `Close_Device()` → `ensure_camera()` → 再抓一次"), 而
  **`/picture?grab=1` 与 `/region?grab=1` 没有** ⇒ 首抓失败就直接 500。
- 修法(v5.1, 两路四處): 那两个路由补上**与 /capture_detect 逐字相同**的重连+重试, 再失败才 500。
  实测修后: 10082 `grab=1` 200/520918B/0.73s · 10083 200/237123B/0.26s (真 JPEG)。
- 教训: **同一相机在同一个进程里有两条取帧路径时, 兜底必须两边一致**。

**② "端口在听" ≠ "我们的 v5 在听"** (老倪手动 `python cam_xxx_work_v5.py` 两次的教训)
- 第二个进程的症状: 10082 报 **`打开相机失败 100120003`**(相机独占, 后者打不开) · 10083 报 **`端口 10083 已被占用`**。
  ⇒ 告诉他: 服务由计划任务托管, **不要手动再起一份**。
- 对自动化的影响: 只按端口判活的保活会漏掉 v2/哑掉的进程 ⇒ `zmax_keepalive.ps1` 改成:
  ①没在听→起 v5 ②在听但 `GET /storage` 非 200→杀该 pid 再起 v5 ③**同程序名超额副本→只留端口属主(及其启动壳), 其余杀掉**
  (抢相机的残留会在活实例重启时把相机抢走 → 重启后它又报 100120003)。


老倪明令: 「你是主节点, 要完全控制工控机和 Orin; **不要用 10084 10085 通道**; 还得用 10082 10083;
以后你得自主更新工控机的程序」。⇒ 更新/重启/回滚**不再请示**, 但**只能在 10082/10083 上做**, 也不许用测试口“先试”。

**一、工控机已装两个 SYSTEM 计划任务 (不再需要老倪贴命令行)**:
- `ZMAX_Agent`(`/sc onstart`) → `zmax_agent_loop.ps1` → 反向通道轮询(崩了 10s 自拉起) ⇒ 我随时可驱动。
- `ZMAX_AOI_KeepAlive`(`/sc minute /mo 1`) → `zmax_keepalive.ps1`: 10082/10083 哪个没在听就拉起它(平时不打日志)。实测: kill 掉 10083 → 25s 内自行恢复。
- 脚本都在 `D:\xspace\ultralytics_AOI\{zmax_keepalive.ps1,zmax_agent_loop.ps1,zmax_agent.ps1}` (纯 ASCII); 源文件在 4060 `~/aoi_v4/deliver/v5/`。
- 改写/换新时: 改 4060 上的源 → 用反向通道重新 `iwr` 下来覆盖即可(任务指向文件名, 不需重建)。

**二、自主更新器 `tools/aoi_remote_deploy.py`(唯一该走的上线路径)**:
```bash
cd ~/zmax_rel && ./gui-venv311/bin/python tools/aoi_remote_deploy.py \
  --finger ~/aoi_v4/cam_finger_10082_work_v6.py --surface ~/aoi_v4/cam_surface_10083_work_v6.py
# 现役文件名(房内命名族 cam_*, 2026-09-27 起): D:\xspace\ultralytics_AOI\cam_finger_10082_work_v6.py · cam_surface_10083_work_v6.py
# (改名后务必同步改 zmax_keepalive.ps1 的 $prog 与 deployer 的 FILENAME_* + start_pair 启动行, 否则自愈会拉错文件)
# ①拷进 8794 静态目录 → ②工控机 iwr 下载 + Get-FileHash 逐位核对(不一致即中止, 产线一字未动)
# ③现役备份 .bak → ④停旧起新(**只 10082/10083**, 分离启动) → ⑤验收 → ⑥失败自动回滚+复验
```
验收项(缺一即失败): `/storage`200 · `POST /capture_detect` 回执 `code=200` · `/last_result` 判决通道 ·
`grab=1` 出图字节>0 · **`grab=1` 前后 `files_total` 不增**。实测幂等重发 v5: 两路 6/6 全过。
⚠️ 坑: `/last_result` 在刚拍完时会是 **404「尚无检测结果」**(后台推理未完成; 表面 housing 实测 ~8.9s)。
断言必须**轮询最多 45s** 并接受两种合法形态(`200+verdict/count` ‖ `404+尚无`) —— 固定等 6s 会假失败并触发回滚。

**三、上线后自查(从 4060, 只读)**:
```bash
curl -s http://192.168.23.23:10082/storage   # 200 + 张数/上限
curl -s http://192.168.23.23:10083/last_result
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' 'http://192.168.23.23:10082/picture?kind=origin&grab=1'
```
v6 已在 10082/10083 跑(2026-09-27, = v5 + 取图两路由的重连重试修复 + 版本号统一), 日志 `D:\xspace\ultralytics_AOI\v5f.log` / `v5s.log`。


## 升级到 v4 (表面 10083 / 金手指 10082) —— 历史/回滚参考 (已被 v5 取代)

> 现状(2026-09-27 09:5x): 工控机 `D:\xspace\ultralytics_AOI\` 跑的就是
> `cam_finger_10082_work_v5.py`(10082) 与 `surface_10083_work_v5.py`(10083), 分离启动, 日志 `v5f.log`/`v5s.log`;
> 验收: `/last_result` 两路 200 (gf ms≈1.6s / housing ms≈8.9s), `capture_detect` 回执 `{"code":200,"msg":"success"}` 逐字未变,
> `grab=1` 出图(385KB/261KB)且 `files_total` 不变。下面 v4 段落只作历史/回滚参考。


程序本体(**早就写好、离线验过, 别再重写**):
- 表面: `~/aoi_v4/surface_10083_work_v4.py` (488 行, 默认端口 10083)
- 金手指: `~/aoi_v4/cam_finger_10082_work_v4.py` (30137B, 同结构; 10082 尚未上线)
- 离线契约测试(不需相机/不需真权重):
  `cd ~/aoi_v4 && .venv-test/bin/python test_surface_v4_offline.py` —— `_stub/`+`_stubmods/` 假 SciCam/假检测器;
  实际输出必须 5/5: `capture_detect 200` · `picture?kind=crop 200 1280×1280` · `kind=origin 200 2048×2448` ·
  `last_result 200 verdict/count/ms` · `crop_info 200 canonical/mean`。

v4 相对 v2 = **只加不减**(升级不破坏产线口径): `POST /capture_detect` 回执逐字一致
`{"code":200,"msg":"success"}`; 新增 `GET /picture?kind=crop|origin[&meta=1][&grab=1]` · `/last_result` · `/crop_info`;
相机常驻 + 单 worker 异步队列; 表面规范图 = `config.yaml` housing 的 `imgsz=1280` 保比例 letterbox。

上线包(4060 上现成): `~/aoi_v4/deliver_10083_v4/` = 程序 + `upgrade_10083_v4.ps1` + README + sha256;
仓库副本 `docs/deliver/10083_v4/`。ps1 三段式: `-CheckOnly` 只自检 / 不带参 = 起在 **10084** 试跑路由(不碰 v2) /
`-Apply` = 停 v2 → 起 v4 → 真拍一张 → 存 `v4_check_crop.png`+`v4_check_origin.png`。

## 怎么给工控机送文件 + 怎么"驱动"它 (无 SSH/RDP/WinRM 时) —— 2026-09-27 已跑通并上线 v5
工控机`192.168.23.23`只开 10081/10082/10083 + 135/139/445(无匿名共享, 本机无凭据)。

**① 送文件(单向)**: 4060 起静态服务 `python3 -m http.server 8794 --bind 0.0.0.0 --directory <目录>`,
老倪在那边的 PowerShell 里 `iwr http://192.168.23.50:8794/<文件> -OutFile <文件>`。
**② 驱动它(双向, 反向通道)** —— 没有登录口时唯一可靠做法: `tools/agent_hub.py`(4060:8794) 出命令队列,
Windows 端一行 `agent_start_ascii.ps1` 每 3s 来 `GET /agent/cmd` 取一条、跑完把输出 `POST /agent/out` 回来。
- 纪律: **命令队列只有 4060 本机可写**(网络侧只能取不能投)、带 token、关窗即断、无凭据无自启。
- ⚠️ 脚本要**纯 ASCII**(PS 5.1 读无 BOM 的 UTF-8 会把中文变乱码, 极端情况破坏解析)。
- ⚠️ 老倪第一遍会"卡住": PS 5.1 的 `irm` 不带 `-UseBasicParsing` 卡在代理/IE 初始化 ⇒ 下载/轮询一律加
  `-UseBasicParsing -TimeoutSec 20`; 卡住时先让他跑 `Test-NetConnection 192.168.23.50 -Port 8794 -InformationLevel Quiet`。
- ⚠️ 回传命令里**别用 `Write-Host`**(它写 information 流, `2>&1|Out-String` 抓不到 ⇒ 我这边只看到空); 要用管道输出(字符串表达式/cmdlet)。
- ⚠️ 长命令分小步; 我 hub 的回执文件名按 `int(time.time())`, 同一秒两条会互相覆盖。

**③ v5 上线做法(已验证, 通道不变)**: 送两文件→`Get-FileHash` 核对→本机 `venv\Scripts\python.exe -m py_compile`→
试跑测试口(金手指 `--port 10084`; 表面**位置参数** `10085`)→真拍+`grab=1` 验收→停试跑→启正式口。
- **务必分离启动**(否则关窗会把服务带走): `$sh=New-Object -ComObject WScript.Shell; $sh.Run("cmd /c <venv python> <脚本> > <日志> 2>&1",0,$false)`。
- 表面那套 `POST /capture_detect` 在**非 10083 端口**会回 400「未配置检测模型, 可选端口 ['10083']」= **端口绑定的模型映射, 属设计**, 所以表面真检测只能在正式口验。
- 起完自查: `Get-NetTCPConnection -LocalPort 10082,10083 -State Listen` + 从 4060 `curl /storage` `/last_result` `/picture?kind=origin&grab=1`。


## 上线纪律 (相机独占)
- v2 与 v4 **不能同时开拍**: 同一通道(10083)只能一个进程, 相机(D265250099)也是独占。
  v4 起不来并打印"端口已被占用" = v2 还在跑。
- **不改 v2 的文件**(老倪明确要求): v4 是独立文件名, 回滚 = 停 v4 再按原方式启 v2。
- 上完后验收看 4060 侧那一格: 4s 内出图 + 标题栏带「上轮判定 OK/NG (n 缺陷 · 推理 xxms)」,
  或直接 `curl http://192.168.23.23:10083/picture?meta=1` / `/last_result`。

## 🆕 v10: 模型吃 960 同帧派生图(不落盘), 只落判据图一张 (2026-09-30)
老倪: 「Finger_ModelIn_* 不要了; 保留 Finger_TopView_W900_H332_*; 确认模型吃的是哪张」⇒ 实测改前吃的是 ModelIn(960)。
四条硬教训(别让模型直接吃判据图 / 临时图别写在高频路径 / 通道命令必须有界 / 部署器状态码与判据口径)
见 `references/aoi-v7-judge-and-channel-20260929.md` 的 v10 段。在役 v10; 回滚 `cam_finger_10082_work_v6.py.bak`。

## 🆕 v7: 落盘/展示的 topview = 「判据图」口径 (2026-09-29)

改前 topview = **960x960 方图**(1455x70 条带纵向拉 13.7 倍), 网页判据图 = **900x332** ⇒ 肉眼两张图。
修法: 口径从 `tools/aoi_exposure_fix.py` **逐条移植**进工控机(`render_judge`: 过曝带切除+只留金手指条+列裁死白列+
短边×2+按实测倾角反旋+定尺 900x332), `?kind=crop|topview` 与落盘都给判据图; **模型输入逐位不变**
(仍 960x960 送检, 另存 `Finger_ModelIn_*`), `/last_result` 同时报 `topview`/`model_input`。
改动前必读: `references/aoi-v7-judge-and-channel-20260929.md`(口径细节/离线契约测试的坑/验收 r≥0.98/交付与回滚)。

## 🆕 反向通道"死了"≠ agent 死了 (2026-09-29)

三根因(**按此序查, 别先怀疑 agent**): ①hub 没托管(`ss -ltnp | grep 8794` 没人听 ⇒ `zmax-agent-hub.service`)
②队列在 `/tmp` 被内核 `fs.protected_regular` 拒写 ⇒ 运行态搬 `~/zmax_data/agent_hub/`
③两端 token 不一致(客户端带的是 `ZMAX_AOI_KeepAlive`) ⇒ hub 多 token。
判活手段: `tcpdump -A ... 'host 192.168.23.23 and port 8794'` 看**它发的请求**(403=我们拒它, 不是它死);
取回执 `tools/station_cmd.py "<PowerShell>"`。细节见 `references/aoi-v7-judge-and-channel-20260929.md`。

## 调用纪律

- 它是**产线设备**的检测服务

**差在哪(实测量)**: 改前 topview = **960x960 方图**(1455x70 条带纵向拉 ~13.7 倍填满方框), 网页判据图 = **900x332**
(原比例条带 + 纵向×2 + 反倾角 + 定尺) ⇒ 同一张原图两种口径, 肉眼完全不同。

**修法(工控机程序 v7, 只改 10082)**: 把 4060 侧 `tools/aoi_exposure_fix.py` 的口径**逐条移植**进工控机
(`render_judge`: 过曝带切除 → 只留金手指条 → 列裁死白列 → 短边×2 → 按实测倾角反旋(白底) → 定尺 **900x332**),
落盘/`?kind=crop|topview` 都给判据图; `/crop_info.judge` 出台账; 渲染失败**回退+警告**, 不硬裁一张错的。
- ⚠️ 灰度加权必须 `0.299R+0.587G+0.114B`(进出各转一次颜色); 喂 BGR 会**裁错行**。
- ✅ **模型输入逐位不变**: YOLO 仍吃 960x960 模板法规整图(`imgsz=960` ⇒ 召回不受影响), 另存
  `Finger_ModelIn_W960_H960_No_*.png` 并送检; `/last_result` 同时给 `topview`(人看的=判据图) 与 `model_input`(模型吃的)。
  ⇒ **改"人看的图"时绝不动"模型吃的图"**; 两者都落盘+都进台账, 追溯不断。
- 验收口径(可复现): 工控机 `?kind=crop`(900x332) vs 4060 网页判据图帧 → **r≥0.98**(实测 0.9847, 行剖面 0.9971);
  离线对同源原图 → r≥0.99(实测 0.9973)。**别只看尺寸对**。
- 离线契约测试: `cd ~/aoi_v4 && ~/zmax_rel/gui-venv311/bin/python test_v7_judge_offline.py`
  (桩相机喂**真实原图** + 桩 detector **记录它被喂了哪张文件** ⇒ 能硬证"模型输入没变")。
  坑: 桩路比真相机多一道去马赛克(桩喂的是已处理好的 PNG) ⇒ 它自测的倾角会偏(-1.5° vs 真值 -0.75°),
  直调对比要用**真相机 /region 的实测倾角**, 且桩会**原地改**你传进去的像素数组(直调要重新 imread 一份)。
- 交付件 `docs/deliver/v7/`(程序 + `judge_render.py` + 离线测试 + SHA256; 场侧 SHA256 与仓库逐位一致)。

## 🆕 反向通道"死了"≠ agent 死了 (2026-09-29 三故障, 排障顺序照抄)

症状: `aoi_remote_deploy.py` 卡「通道没回执」; `aoi_watch.sh` 报「工控机 agent 已 N 分钟没轮询」;
而 AOI 产线本身正常(10082/10083 由工控机自己的分钟任务托管)。**先别信"agent 死了"**, 三步查:
1. `sudo ss -ltnp | grep 8794` → hub 在不在(**必须在**, 手工起的断一次就没了) ⇒ 已建 `zmax-agent-hub.service`(enabled)。
2. `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host 192.168.23.23 and port 8794' | grep -aE 'GET|HTTP/|403'`
   —— **看它到底发了什么**: 实测客户端每 5s 都在 `GET /agent/cmd?t=ZMAX_AOI_KeepAlive`, 我们回 **403 token 不对**
   ⇒ "客户端活着, 是主节点这头拒它"。**两端 token 可能不一致** ⇒ hub 支持多 token(`--token a,b`), 两个都认。
3. 队列文件若还在 `/tmp`: 服务以 root 跑、文件属主是 ubuntu ⇒ root 重写 sticky 目录下他人文件被内核
   `fs.protected_regular` 拒(`PermissionError: /tmp/zmax_agent_cmd.jsonl`) ⇒ 队列**取不走**(表象=通道断)。
   运行态统一搬 `~/zmax_data/agent_hub/`(`cmd.jsonl`/`out/`/`hub.log`/`beat`; 旧 `/tmp/zmax_agent_beat` 仍写, 兼容看门狗)。
   同一坑: 工具里的 `OUT_DIR` 必须与 hub 一致, 否则"命令跑了但收不到回执"(假超时)。
- 取回执一行命令: `./gui-venv311/bin/python tools/station_cmd.py "<PowerShell>"`(缺 `tools/station_cmd.py` 时,
  `agent_hub.py --enqueue` + 读 `~/zmax_data/agent_hub/out/` 最新文件同样可)。回执里 `whoami` = `nt authority\system` ⇒ 计划任务跑起来了。
- 教训: **通道健康要用"它发来的请求"判, 不能用日志行数/本机自检判**(本机 curl 会把 beat 探活, 看门狗脚本已特意排除本机来源)。

## 调用纪律

- 它是**产线设备**的检测服务: 调用=真拍一张真机台照片 → **先问用户再打**, 不批量轮询
- 想连这台工控机做别的(SSH/RDP/VNC)都是**关的** ✗; 只有 10081/10082/10083 三个 HTTP 口开着
- 10081 是同族的第三个 Flask 服务(端口映射未在其中写明), 需要时用 `POST /capture_detect` 试
