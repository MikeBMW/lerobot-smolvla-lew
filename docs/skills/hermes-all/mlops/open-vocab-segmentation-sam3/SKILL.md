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

## 微调通道 (框提示式) —— 4060 8GB 实测口径 (2026-10-01)
仓库**没有任何 SAM3 训练脚本**; 训练内核 = `policies/sam3_seg/finetune.py` + `lora_inject.py`, 调用方 = `tools/sam3_finetune.py` (子命令 `masks`/`train`/`verify`/`eval`)。

**显存账 (1008px, bf16, 单卡 4060 8GB)** —— 视觉塔是瓶颈, 先量再定:
- 冻结视觉塔+文本塔, 只训 4 个头(geometry/detr_encoder/detr_decoder/mask_decoder = 31.43M): fwd+bwd 峰值 **2.98GB**。
- LoRA 注**最后 N 个** ViT block (反向只留 LoRA block **之后**的激活): N=4→4.12GB, **N=8→4.91GB (推荐)**, N=16→6.51GB, N=32→**OOM**。
  `Sam3ViTModel.supports_gradient_checkpointing = False` (没有原生梯度检查点), 别指望它省显存。
- 训练时**必须先卸掉 8796 分割服务**: `sudo systemctl stop sam3-seg` (它常驻 2.3GB, 不卸就撞显存红线), 训完 `start` 回来 (服务是 `--lazy`, 起来不占显存, 健康检查 `loaded:false`)。

**四个必踩的坑** (每个都能静默毁掉一轮):
1. **注入前缀不能带前导点**: `named_modules()` 的名字是 `vision_encoder.backbone.layers.0.attention.q_proj`(无前导点),
   用 `.vision_encoder.backbone.layers.` 去 `in` 匹配 ⇒ **命中 0 个且不报错** ⇒ 一个适配器都没注入, 日志照常"训练"。
   判据: 注入后立刻断言 `n_inject > 0`, 并把数量打进日志。
2. **注入在 `.to('cuda')` 之后做 ⇒ 新参数默认落 CPU** ⇒ 前向抛 cuda/cpu 混算。新参数必须显式 `device=base.weight.device`。
3. **`input_boxes` 是 `[batch, n_box, 4]` 且归一化 `(cx,cy,w,h)`** (processor 自动做 xyxy→cxcywh): 自己拼张量少一个 batch 维 ⇒ `geometry_encoder` 里 `view(batch_size, num_boxes, hidden)` 报 `shape '[1, 4, 256]' invalid for input of size 256`。
4. **forward 不返回 `loss`** (只有 pred_masks/pred_boxes/pred_logits/presence_logits) ⇒ 损失得自己搭。训练可直接吃 `vision_embeds=` (可把视觉塔拆出去), 但**必须给 text 或 box 之一**(两者都缺会 `ValueError`)。

**输出口径**: `pred_masks` = `[B, 200, 288, 288]` (不是原图尺寸), `pred_boxes` = `[B,200,4]` 归一化 xyxy, `pred_logits`/`presence_logits` 走 text 点积 + presence token。

**监督从哪来 (数据只有检测框、没有掩膜时)**:
- **框提示能分出东西** —— 修正本文前面"概念常 0 实例"的印象: 那是**文本**概念的问题; **框提示**在真机帧上 58/58 全出掩膜
  (与 GT 框 IoU 中位 0.62 / 最大 0.91), 一条都不用回退。所以"框提示式微调"在这台机器上是可落地的路线。
- 掩膜目标 = 冻结基座 + **同一框提示**产出的掩膜 (教师伪标签, 落 PNG 288×288, 选与 GT 框 IoU 最高的那个 query,
  不是"分数最高"的)。**报告里必须写作"教师伪标签", 不许说成人工掩膜标注。**
- 真标注监督的那一路: 文本提示(类名英文) → 框, 用 Hungarian 匹配 200 个 query 到 GT 框, 监督 L1+GIoU+cls+presence。那一路是非退化的。
- ⚠️ **退化的陷阱**: 提示框=目标框、学生也是同一模型输出 ⇒ 首步 mask BCE 就 0.005 (几乎零损失)。
  要给出非退化信号, 训练时**扰动图像(光度)+ 抖动提示框**(目标仍是精确框下的教师掩膜) —— 就是"框不准也要分出来"。

**评估口径的铁律**: 掩膜 IoU 若以**教师伪标签**为对照方, 那**基座自己是上界**(它=教师), 蒸馏只能逼近、不可能超过。
只看这一个数会把"正常的逼近"误读成"LoRA 无效/变差"。要看真收益: ①抖动静默扫描 (抖动加大时谁衰减更慢) ②单看**用真标注监督的**那一路(框 IoU)。
且 val 只有 5 帧/5 query 时, 同一配置换一个抖动种子, 基座 IoU 就在 0.696~0.762 之间跳 ⇒ 单格 Δ±0.05~0.09 全是噪声, 不许当结论。

**已知死区 (登记, 别当故障)**: `mask_decoder` 有 6 个参数 `grad is None` —— `pixel_decoder.conv_layers.2.*` / `norms.2.*` (最深一级上采样被 instance_projection 绕过) 与 `semantic_projection.*` (semantic_seg 不进损失)。其余 4 个头逐模块都有非零梯度。

## 集成到场景叠加
- 规格元素 `{"origin":"seg","kind":"mask","polys":[[[x,y],…]],"area_px":…,"conf":…,"c3d":{…}}`; 渲染走 `scene_overlay.draw_overlay` 的 `elif b.get("polys")` 分支(**插在 box3d 之后、xyxy 之前** —— 否则带 xyxy 的掩膜会被矩形分支抢走)。
- **标签放轮廓外**: 不透明底片贴上去会盖掉填充与轮廓。大掩膜填充按面积减淡。
- `/boxes` 要给前端**真实轮廓点集** `contour`(取最大一圈), 页面 `bShape()` 才能画多边形并按多边形命中(否则退回外接矩形, 掩膜的"贴合"在页面上看不出来)。
- 服务化: 独立进程常驻(如 8796), **显存独占**红线; 推流服务只转发 + 落规格, 失败如实回页面。

## 残留: 按需分割写进规格后**不会自己消失** (2026-09-30 老倪问 "怎么残留历史的分割图")

分割是**一次性/按需**跑的, 结果以 `origin="seg"` 落进 `data/scene/overlay_spec.json` 后**没有任何过期机制**;
而推流服务 `cam_live_stream.py` **每帧热读**这份规格照画 ⇒ 只要规格里还留着掩膜, 页面就一直在画**那一刻的**掩膜,
相机/机械臂已经动了也不管 —— 看上去就是"残留的历史分割图"(实测: 06:52 一次补写留下的 6 条掩膜,
到了 20:5x 还在画, 坐标还是当时那帧的 640x480)。

**清层要这样清**(只动自己 origin, 不碰 meas/plan/trace/l5live/det/vlm):
```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python -c "import sys;sys.path.insert(0,'tools');\
import scene_overlay as SO;s=SO.load_spec();s=SO.merge_origin(s,'arm','seg',[]);SO.save_spec(s)"   # 先备份 spec
```
清完复核 `GET /boxes?cam=arm` 的 drawn 里没有 `origin=seg`, 且 `meas` 条数不变。

⚠️ **别用页面上的 🗑 去删分割框**: `_boxes_edit(mode='delete')` 会把 id(`origin|label`, 如 `seg|metal`)写进
`spec.deleted`, 而 `draw_overlay` 对 deleted 里的 id **一律跳过** ⇒ 之后再跑分割拿到同名实例会被**静默吞掉**
(表现又是"分割没出图")。deleted 语义是给 VLM 的"不要再给", 不是清层工具; 要清就清层或用 "恢复全部" 清空清单。

**治本方向**(未做): 掩膜绑帧 —— 写规格时存一个帧签名(如 32x32 灰度 dHash), 渲染时帧差超阈就不画。
注意**不能拿 JPEG 字节 md5 当判据**(同一静止场景每帧字节都不同, 会立刻全灭), 要用感知级阈值。

## 预算与定位
- 4060 8GB: bf16 载入 ≈1.7GB, 1008² 前向**峰值 2.1~2.4GB**, 加载 1.3s, 单概念 0.4s。
- 定位**关键帧/触发式**(页面按钮、画布节点双击、标注批次), **不做逐帧**; YOLO 每帧(轻) + SAM3 按需(重) 互补。

## 验收证据 (缺一不算完成)
1. 存档真帧 → 实例数/分数/面积/框。2. 同帧 A/B: 差异像素**落在多边形内**。3. 管道: 服务 → 规格 → `/boxes` 有 `origin=seg` → 叠加帧 vs 原始帧有差异 → 删除回退 → 恢复。4. 掩膜→3D: 缺深度/手眼/TCP **必须如实拒答**, 不许猜填。5. 目检: 让视觉模型看渲染图判贴合。**相机是黑帧时别拿实况当"贴合"证据**(先看 mean/std, 黑帧 mean≈5/std<1)。
