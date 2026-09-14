---
name: smolvlm-perception-integration
description: 'Use when 把真实 SmolVLM/VLM 视觉编码接入画布感知节点, 或本地单帧编码。含回归红线。'
---

# SmolVLM 真实视觉编码接入 (Z-MAX 感知侧真实化)

把画布教学演示节点 (node_ss_vlm) 升级为**真实 SmolVLM2 权重前向**, 以及任何"预训练 VLM 视觉编码本地推理"任务的配方。
红线 (老倪): **接入后插拔任务成功率/性能不许回退 — 先回归再交付** (回归基线见下)。

## 环境 (4060 本地, venv=gui-venv311, 2026-09-08 实测)
- venv 无 pip → `uv pip install --python gui-venv311/bin/python <pkg>` (uv 在 ~/.hermes/bin/uv)
- 缺包: transformers (5.16.1), **num2words** (SmolVLM processor 硬依赖, 缺了 AutoProcessor 直接 ImportError)
- 权重: HuggingFaceTB/SmolVLM2-500M-Video-Instruct 已缓存 ~/.cache/huggingface/hub (~1GB model.safetensors + ~4.7GB onnx 目录无用可删; 缺 processor 文件时 AutoProcessor.from_pretrained 经 HF_ENDPOINT=hf-mirror 自动补下)
- GPU 4060 8GB: fp16 加载 ~13-16s / 显存峰值 ~1.4GB / 单帧编码 ~0.8s

## 编码通道 (正确做法 — 勿绕 vision tower)
- ❌ processor.image_processor 输出 pixel_values **[B,17,3,512,512] 5D** (Video-Instruct 帧结构) — 直接喂 `model.model.vision_model` 报 "too many values to unpack (expected 4)"
- ✅ 仿 `src/lerobot/policies/smolvla_lew/modeling_smolvla_lew.py::_get_multimodal_embeds`:
  `proc(images=[pil], text="<image>")` → `model(pixel_values, input_ids, output_hidden_states=True, return_dict=True)` → `hidden_states[-1]` [1, ~1127, **960**] → mean-pool → z∈R⁹⁶⁰ (SmolVLM2-500M hidden=960, 非 1152)
- transformers 5.x: `AutoModelForImageTextToText`; `device_map` 需 accelerate → 500M 直接 `from_pretrained(torch_dtype=fp16).to("cuda")`
- 特征展示: mean/std/|z|/top 活跃通道/token 数/时延 (自解释); 与几何降维 (R⁷) 并存作对照, 不冒充语义

## 接入件 (commit 3482a9a7, tools/gui/)
- `vlm_encoder.py`: SmolVLMEncoder 进程级单例 (get_encoder), **后台线程加载** (ensure_loaded_async; status idle/loading/ready/error), encode() 永不抛异常 (GUI 铁律), _lock 串行推理
- `state_space_sim_real.py`: `_vis_refresh` 每阶段第 6 帧存 `_key_frames[stage]` (仅 vision=True 有帧); run 尾部 `tr["key_frames"]` 随轨迹走
- `node_logic.py node_ss_vlm`: 真实执行 (双击/单步, **播放 demo 不跑模型**铁律) → 当前 stage → key_frames 帧 → encode → `module._vlm_cache[stage|seed]` 缓存; 首次触发后台加载并提示 ~15s

## 坑
- 探针/验证脚本**禁止打印 logits 或大数组** (曾打印 logits 输出 183 万字符炸屏 + 磁盘写爆缓存)
- 回归基线 (seed104, 红线): R1(视觉) insert 352 步 done / full 876 步 done + AOI PASS / R0 insert 344 步 — R1 失败先查肌肉记忆是否误开 (见下)

## 相关根因速查 (同一会话实锤, 详见 zmax-real-closed-loop 技能)
- **R1 视觉 "夹不起" 先查肌肉记忆快通道**: 历史标杆 u_exec 开环重放与视觉/接触随机失配 → 空夹循环 (SS_MUSCLE=0 即 352 步成功)。现代码 vision=True 自动禁小脑; 若看到 R1 又 9/9 失败, 查 `sim._mm_on` 是否误 True
- **夹持锚定**已是抬升试探版 (夹爪动 + peg 真值跟随即锚定), 视觉残差不参与夹持后判定 — 勿改回 "偏差<8mm 才锚定" 旧逻辑 (8mm 边界会把真夹住误判滑脱)
- sim_real.run(max_steps=None): insert 默认 500 / full 默认 2000 (full 13 段需 850+ 步)
