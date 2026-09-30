# VLM 感知真实接入 + 状态空间 ActionHead (2026-09-08)

老倪两条指令: ①"先接 SmolVLM 视觉编码(预训练权重直接下,感知侧先真实化)";
②"这个也应该在标准 smolvla 算法里,可以增加针对状态空间的 action head"。
落地 commit: 3482a9a7 (VLM 接入+肌肉记忆 R1 禁用) + 2e32aa30 (架构归位 src)。

## 真实算法归位 src 铁律 (第二次实锤, 同 09-02 数据源整改)
- 画布任何"教学占位"节点被老倪看到都会问"怎么在 GUI 里, 应该在 src/lerobot/policies 标准算法"
  → 提前归位: 真实实现文件入 src/lerobot/policies/<policy>/ + node exec(compile(真实路径)) +
  _EXTERNAL_LOC 映射 (三件套)。vlm_encoder 曾放 tools/gui/ 被当场纠正。
- **draccus 依赖陷阱**: smolvla_lew 官方文件 (action_head.py / modeling_*.py) 顶层
  `from lerobot.utils.import_utils import ...` → 链式 `draccus`, GUI venv (gui-venv311,
  无 lerobot 包) 单文件 exec 加载必 ModuleNotFoundError('draccus')。
  → **新算法类放同包纯 torch 独立文件** (顶部只 import torch/nn), node 才能 exec + 断点可进。
- exec 加载的 ns 必须**模块级缓存 + threading.Lock**: 每次 exec 重建 ns → get_encoder() 单例
  丢 → 模型重复加载 15s×N。缓存模式见 node_logic._vlm_encoder_ns/_ssah_ns。
- 教学占位保留"可修改区", 输出行如实指向真实类路径 (node_action_head 双真实实现展示)。

## SmolVLM2-500M-Video-Instruct 本地 GPU 推理 (4060 8GB 实测)
- 依赖装 gui-venv311 (venv 无 pip → `uv pip install -q --python gui-venv311/bin/python <pkg>`):
  transformers (实测 5.16.1) + num2words (processor 必需, 缺失 ImportError 明确报);
  清华源快。权重 ~1GB 已缓存 ~/.cache/huggingface/hub (快照含 4.7GB onnx 子目录, 用不上)。
- processor 缺 preprocessor_config 等文件时 AutoProcessor 自动补下 (HF_ENDPOINT=hf-mirror 兜底)。
- **processor 输出 5D**: pixel_values [1,17,3,512,512] (Video-Instruct 帧结构) — 直接喂
  vision_model 报 "too many values to unpack (expected 4)"。**正确通道 = 仿 smolvla_lew.
  _get_multimodal_embeds 全前向**: processor(images=[pil], text="<image>") → model(
  pixel_values, input_ids, output_hidden_states=True) → hidden_states[-1] [1, seq≈1127, 960]
  → mean-pool → z∈R⁹⁶⁰。加载 ~15s (fp16 .to('cuda'), 勿 device_map 需 accelerate),
  单帧 ~0.8s, 显存峰值 1.4GB。
- 5.x API: AutoModelForImageTextToText / AutoProcessor; torch_dtype 弃用告警改 dtype (无害)。
- CLI 自测勿打印 logits/tensor 全文 (183 万字符输出爆炸教训), 只打 shape/统计/topk。

## StateSpaceActionHead (状态空间动作头变体)
- src/lerobot/policies/smolvla_lew/state_space_action_head.py: 官方 SmolVLALewActionHead
  (action_head.py, DiT 流匹配 VLM 条件) 之外的 z→动作直接映射变体 — 官方 action_decoder
  同构 MLP: Linear→SiLU→...→Linear(action_dim×chunk); input_dim 参数化 (R⁷ 几何 / R⁹⁶⁰
  VLM / 融合 R⁹⁶⁷), action_dim 4 (真机 Orin 6D), chunk_size 7。75,036 参数 (R⁷ 实例)。
  随机初始化, 真实权重 = smolvla_lew 训练/蒸馏后 (诚实标注, 节点自检只验结构+前向维度)。

## 画布节点真实化验收路径
▶运行 (🎥真实化 R1 视觉) → sim_real 每阶段存 key_frames (tr["key_frames"], 阶段第 6 帧,
vision 模式才有; R0 无帧) → 双击 🧠 VLM 节点: 首次提示后台加载 ~15s → 再双击出
"✅ VLM 真实编码 [阶段=X]: SmolVLM2-500M · 1127 token → z∈R960 · |z|=25.4 · top活跃 …"
→ 双击 🔄 潜空间 Decoder: "✅ StateSpaceActionHead 真实类 75,036 参数 + 前向自检 (1,7,4)"。
播放动画 demo 不跑模型 (老倪红线): demo 路径读缓存/提示, 编码只在双击/单步触发。
