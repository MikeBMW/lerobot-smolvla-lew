# SmolVLM2 批量编码 + 特征实验口径 (2026-09-11 实测)

## 1. 批量编码 API 形态（踩坑 → 正解）

失败写法（整批报错）:
```python
proc(images=[img1, img2, ...], text=["<image>"] * N, return_tensors="pt", padding=True)
# ValueError: The number of images in the text [1,1,...] and images [N] should be the same
```

正解（images 传**嵌套列表**，每样本一个图列表）:
```python
o = proc(images=[[p] for p in pils], text=["<image>"] * len(pils),
         return_tensors="pt", padding=True)
r = model(pixel_values=o["pixel_values"].to(dev, dtype=torch.float16),
          input_ids=o["input_ids"].to(dev),
          attention_mask=o["attention_mask"].to(dev),
          output_hidden_states=True)
h = r.hidden_states[-1].float()                      # [B, seq, 960]
m = o["attention_mask"].to(dev).unsqueeze(-1).float()
z = (h * m).sum(1) / m.sum(1).clamp(min=1)           # 按 mask 加权 mean-pool
```

- 128×128 输入的 `pixel_values` 会被 processor 上采样到 **[B, 17, 3, 512, 512]**（Video-Instruct 帧结构）
- 单帧调用 (`images=[pil]`) 一直是 OK 的；只有批量才踩这个坑

## 2. ⚠️ 静默兜底 → 全零特征 → 假结论（本次最贵教训）

批处理包 try/except 时，若 except 分支写 `Z.append(np.zeros(960, np.float32))`：
- 全部批次失败 → 特征矩阵**全零**
- 下游训练症状：**train MSE ≈ 1.0**（归一化空间）＝网络退化成输出常数
- 极易被误读为「VLM 特征没信息 / 这个架构不行 / 视觉版不如几何版」

**本次实况**：连续 3 轮"视觉版 vs 几何版"对比（650 帧 / 7877 帧 / 中间正则配置）全部报
"视觉版未更优"，实际是编码全零，**三轮结论全部作废**。

铁律:
1. 编码落盘后**立刻断言 `z.std() > 0`**（全零 = 编码失败，不是模型结论）
2. except 分支要么抛（best），要么显式打日志 + 计数，禁止静默补零
3. 判据先看"输入是否退化"，再看"模型是否学到"

## 3. 显存约束（共享 8GB 卡）

- 与其它训练共享 4060 时：bs=1~4 + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
- bs=16 × 512×512 在剩余 ~2.7GB 下必 OOM
- **CUDA OOM 会落进上面的静默兜底，双坑叠加** → 表现同样是"全零特征"
- 大数据集先 SUB 抽样（每 N 帧取 1）出结论，有增益再全量编码

## 4. 特征实验 vs 几何量基线的公平口径

- 任务标签若是**几何的确定性函数**（如流形 progress/rem/dperp 由手-销-孔几何算出），
  "图像→VLM→标签" 相对 "几何量→标签" 天然吃亏（多一道几何重建损失）— 信息论必然。
  **这不等于"VLM 底座没用"**；视觉路线的价值在真机（拿不到几何真值，只有图像）。
- 公平对比三件套：同网络容量 + 同正则（PCA 降到与样本量同量级，如 960→64 + dropout + weight_decay）
  + **held-out 布局**（metaworld 每进程布局漂移 → 必须留训练没见过的 seed 做 test）。
- 正则两个极端都错：无正则 → train 0.11 / test 1.11（记住训练集）；强正则 → train 1.00 / test 1.04（学不动）。
  出结论前先确认训练配置落在中间地带，否则别下架构结论。
