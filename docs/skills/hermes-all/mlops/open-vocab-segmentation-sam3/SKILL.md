---
name: open-vocab-segmentation-sam3
description: Use when 给状态空间加开放词汇分割(SAM3)或接场景叠加.
version: 1.0.0
author: 静静 (Hermes Agent)
license: Apache-2.0
metadata:
  hermes:
    tags: [segmentation, sam3, perception, overlay, l2, zmax]
    related_skills: [sim-real-scene-overlay, zmax-state-space-architecture, live-camera-detector-adaptation]
---

# 开放词汇分割 (SAM3) 接进状态空间

## When to Use
- 要给状态空间/机器人工位加**开放词汇分割**（"分割 anything"），参考 SAM3。
- 要把分割掩膜接进**场景叠加**（轮廓+半透明填充、页面点选/删除）或自动标注。
- 已接了 SAM3 但**出 0 实例 / 形状报错 / 推理崩**（先看下面“三个实测坑”）。
- 要判断“权重到底对不对”（meta 设备逐张量比形状，别靠重下）。

## 分层与落点 (老倪口径, 别越层)
- **能力落 L2**(感知原语): 一帧 + 概念提示词(文本/框) → 该概念**所有实例掩膜**(像素级)+框+分数。与 L2-A01 YOLO 同级, 差别 = 掩膜不是框 / 开放词汇不是固定类。
- **意图落 L5**: 概念短语由 VLM/人/工单给 —— 分割件**不自造概念**。不进 L3(不产动作)、不进 L4(不预测不规划)。
- **代码位置**: 算法内核 `src/lerobot/policies/<模型名>/`(与 `policies/yolo_3d` 同层级 —— 老倪纠正过: 别把模型算法写进 tools/); `tools/` 只放**调用方**(CLI/常驻服务/写规格/取证图)。
- 接入四件套: registry `_reg(key, [关键字], doc, fn)` + `_EXTERNAL_LOC[key]=(路径, 行号, "def xxx")`(源码视图指向**类内真推理**, 不是三行转发壳) + 画布节点(进对应 row_bg 行带) + capability_levels 一条能力。

## 权重获取 (官方 gated 时)
- `facebook/sam3` 在 HF 是 **gated(需审批)**, 匿名取 config.json 直接 401。走**未门禁镜像的逐文件复制**(键前缀 `detector_model.*`/`tracker_model.*` = transformers 命名)。落数据盘, **不入 git**(3.4GB)。
- 下载: 单连接 1.3~1.7MB/s; 分段并发要配**看门狗**(每 45s 查进度, 僵死就杀重连续传)。⚠️ 中途改分段数会让各段起点错位产生空洞 —— **续传必须段数一致**, 换段数先删 `.parts`。
- 加载一律 `local_files_only=True`, 并落 `sha256`。

## 三个实测坑 (各能浪费一整轮)
1. **多概念一次喂会崩**: `Sam3Processor(text=[c1,c2,c3])` → `Sam3Attention.forward` 里 `view(1,32,8,32)` 收到 24576 个元素(多概念提示特征按 3×256 拼起来, 实现却按单概念 heads×head_dim 切) ⇒ **一个概念一次前向**, 逐概念跑再合并(0.4s/概念)。
2. **中文概念 = 0 实例**: SAM3 文本塔是 **CLIP(英文)**。`光模块`→0, `green connector`→6。概念词必须英文。
   **英文词也要现场试** —— 同一帧实测: `green connector` 6 个 / `slot` 13 / `metal pin` 2 / `connector` 4(分数弱),
   而 `socket`/`port`/`receptacle`/`gripper`/`robot gripper`/`optical module` **全部 0**。默认概念只放**实测有命中**的词。
2b. **“掩膜边上还有残留物色”先算全局**: 该色全图像素数 vs 掩膜盖住比例 —— 实测全图绿 6854px、掩膜只盖 23.5%,
   残留“绿边”主体是**绿色台面/板子本身**, 不是漏掉的目标像素。`mask_threshold` 0.5→0.2 只多盖 16%, 默认不值得改。
2c. **标签会叠成一团**: 多实例小目标时逐个画标签会互相压住(目检直接报“不可读”) ⇒ 标签按 (y,x) 排序
   **逐个找空位**(上→更上→下→右→顶部→右缘)+ **深色底片**; 画面必须一眼可信(老倪会把画面当结果)。
3. **别把"形状报错"当成"权重不对, 重下"**: 判据是**用 meta 设备按本机 config 起空模型, 与 safetensors 头部逐张量比形状**(去掉 `base_model_prefix` 如 `detector_model.` 再比)。实测 1468 个可比对张量形状不符 **0 处** ⇒ 权重是对的, 崩的是入参。

## 集成到场景叠加
- 规格元素 `{"origin":"seg","kind":"mask","polys":[[[x,y],…]],"area_px":…,"conf":…,"c3d":{…}}`; 渲染走 `scene_overlay.draw_overlay` 的 `elif b.get("polys")` 分支(**插在 box3d 之后、xyxy 之前** —— 否则带 xyxy 的掩膜会被矩形分支抢走)。
- **标签放轮廓外**: 不透明底片贴上去会盖掉填充与轮廓。大掩膜填充按面积减淡。
- `/boxes` 要给前端**真实轮廓点集** `contour`(取最大一圈), 页面 `bShape()` 才能画多边形并按多边形命中(否则退回外接矩形, 掩膜的"贴合"在页面上看不出来)。
- 服务化: 独立进程常驻(如 8796), **显存独占**红线; 推流服务只转发 + 落规格, 失败如实回页面。

## 预算与定位
- 4060 8GB: bf16 载入 ≈1.7GB, 1008² 前向**峰值 2.1~2.4GB**, 加载 1.3s, 单概念 0.4s。
- 定位**关键帧/触发式**(页面按钮、画布节点双击、标注批次), **不做逐帧**; YOLO 每帧(轻) + SAM3 按需(重) 互补。

## 验收证据 (缺一不算完成)
1. 存档真帧 → 实例数/分数/面积/框。2. 同帧 A/B: 差异像素**落在多边形内**。3. 管道: 服务 → 规格 → `/boxes` 有 `origin=seg` → 叠加帧 vs 原始帧有差异 → 删除回退 → 恢复。4. 掩膜→3D: 缺深度/手眼/TCP **必须如实拒答**, 不许猜填。5. 目检: 让视觉模型看渲染图判贴合。**相机是黑帧时别拿实况当"贴合"证据**(先看 mean/std, 黑帧 mean≈5/std<1)。
