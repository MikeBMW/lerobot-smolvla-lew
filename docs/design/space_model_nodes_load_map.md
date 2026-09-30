# 状态空间 · 模型节点 ↔ 加载代码 ↔ 权重 (v5.11.4)

老倪要求: 「我要看到在状态空间里的所有模型相关节点, **有模型加载 load 的实际代码, 我可以从 vscode 里打开**」。

打开方式: VSCode `Ctrl+P` 输入 `相对路径:行号` 直达; 或终端 `code -g <相对路径>:<行号>`。
自动审计器: `tools/audit_model_nodes_v2.py` (输出 `reports/model_nodes_v2.json`)。

## A. 真·神经网络模型 (有权重, 有加载代码)

| 模型 | 画布节点 | ① 定义/入口 (VSCode 可开) | ② **实际加载点** | 权重文件 (在盘) |
|---|---|---|---|---|
| YOLO 目标检测 | `ssyolo` 🎯 YOLO 目标检测 | `src/lerobot/policies/yolo_3d/yolo_state_aligner.py:57` (`class YoloStateAligner`) · `:93` (`def detect_3d`) | `docker/z700_infer/infer_service.py:42` `self.yolo = YOLO(yolo_path)` · `tools/real_yolo_perceive.py` · `tools/ss_yolo_on_real.py` | `models/yolo_peg_live.pt` (软链→在役权重) ✅ |
| 前馈加速器 MLP (L2 肌肉) | `ssff` ⚡ 前馈加速器 | `src/lerobot/policies/left_right/state_space/parallel.py` (`class FeedforwardAccelerator`) | `parallel.py:33` `NPZ_DEFAULT = .../models/ss_left_brain.npz` + `:34` 实例化缓存(避免每 tick np.load 2.1MB) | `models/ss_left_brain.npz` ✅ (2.1MB, 由 `tools/export_ss_left_brain.py` 导出) |
| 流形专家预测器 (JEPA) | `ssmani_exp` 🧠 流形专家预测器 | `src/lerobot/manifold/predictor_layer.py:112` (`class WorldModelPredictor`) | 调用方加载: `tools/ss_local_infer_server.py` (11D→6D 本地推理服务) · `tools/ab_mani_yaw.py:87` | `models/l4_mani_predictor_v4.pt` · `v5.pt` ✅ |
| INTACT L4 策略 (在役) | `ssintact` 🎯 INTACT (L4) | `src/lerobot/policies/intact/service.py:235` (`def run_once`) | `tools/intact_sw_bridge.py:138` `model = swm.wm.utils.load_pretrained(T["ckpt"])` · `src/lerobot/policies/intact/runtime/model_adapter.py` | `stable-wm-cache/checkpoints/intact_l4_current/weights.pt` ✅ |
| INTACT 插拔策略 (本域微调) | `swintact` 🎯 INTACT 插拔策略 | `src/lerobot/policies/intact/runtime/node.py` (`class IntactNode`) | 同上 (桥 + `tools/intact_worker.py` 跨 venv) | `checkpoints/intact_goal_optical_insert_v6d5_s3072/weights_epoch_1.pt` ✅ (本轮新训) |
| SmolVLM 视觉编码器 | `ssvlm` 🧠 VLM 通用视觉编码器 | `src/lerobot/policies/smolvla_lew/vlm_encoder.py:24` `MODEL_ID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"` | 单例懒加载 (同文件) · `modeling_smolvla_lew.py:88` `model_id=config.smolvlm_name` | `~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct` ✅ |
| Flow-Matching Action Head (DiT) | `ssdec` 🎯 Flow-Matching Action Head | `src/lerobot/policies/smolvla_lew/action_head.py:205` (`class SmolVLALewActionHead`) | 随策略整体加载: `SmolVLALewPolicy.from_pretrained(...)` (见下行) | 同下 (随策略 ckpt) |
| SmolVLA 策略 (L3 主控) | (L3 档执行链) | `src/lerobot/policies/smolvla_lew/modeling_smolvla_lew.py` | `SmolVLALewPolicy.from_pretrained(rel, local_files_only=True)` — `tools/eval_insert.py:33` · `tools/rollout_smolvla_lew.py:28` · `tools/eval_policy_corr.py:55` | `outputs/train/smolvla_lew_sim/checkpoints/000300/pretrained_model/model.safetensors` ✅ (本轮新训, 1.29GB) |
| Qwen2.5-VL (本地 VLM 场景理解) | `n_vlm_llm` 👁 视觉语言大模型 · 场景理解 | `tools/vlm_worker.py:17` `--model Qwen/Qwen2.5-VL-3B-Instruct --device cuda:0` | worker 内 `from_pretrained` (vlm_worker.py) · lerobot eo1 路径: `modeling_eo1.py` `Qwen2_5_VLForConditionalGeneration.from_pretrained` | `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct` ✅ (另存 `~/zmax_data/hf_home/hub/`) |
| DeepSeek-VL (远端 API 场景理解) | `n_dsvl` 🧿 DeepSeek-VL · 场景理解 | `src/lerobot/policies/left_right/state_space/scene_vlm.py` (`class SceneVLM`) | 远端 API 调用 (**无本地权重**) | — (走 key) |
| 先验动力学预测器 | `sspred` 📈 先验动力学预测器 | `src/lerobot/policies/left_right/state_space/dynamics.py` | 同文件内解析模型 (无外部权重) | — (解析/真值驱动) |

## B. 计算 / 技能 / 其他模型节点 (无权重, 只要求代码可打开)

| 节点 | 代码入口 (VSCode 可开) |
|---|---|
| `ssmani_c` 🧮 接触流形 · 导航地图 | `src/lerobot/manifold/manifold_layer.py:65` (`class ContactManifold`) |
| `ssmani_p` 🧮 性能流形 · 耦合代价 | `src/lerobot/manifold/manifold_layer.py:154` (`class PerformanceManifold`) |
| `sslat` 🧮 潜空-流形 | `src/lerobot/calibration/calibration_layer.py:58` |
| `sscalib` 🧮 标定层 · 引力-斥力-动作 | `src/lerobot/calibration/calibration_layer.py:73` |
| `sssk1..sssk8` ①~⑧ 原子技能 | `src/lerobot/policies/left_right/state_space/skills/atomic.py` |
| `ssskill` 🛠 L3 技能序列编排 | `src/lerobot/policies/left_right/state_space/planner.py` |
| `ssllm` 🧠 L3 长程序列规划器 | `src/lerobot/policies/left_right/state_space/planner.py` |
| `ssreason` 🔍 异常推理器 (LLM) | `src/lerobot/policies/left_right/state_space/planner.py` |
| `ssinnov` 🧪 状态校正器 | `src/lerobot/policies/left_right/state_space/cognition.py` |
| `ssintact_dec` 🎯 INTACT 意图解码器 | `src/lerobot/policies/intact/service.py:235` |
| `ssbypv` 📈 旁路实时可视化 | `tools/gui/ss_bypass_view.py:220` |
| `ssz700` 🖥 Z700 真机信号 | `tools/gui/ss_bypass_view.py:489` |
| `ssff_hist` 🧠 前馈激活直方图 | `tools/gui/node_logic.py` (`node_ss_ff_hist`) |
| `ssc` 🅾️ 通用算子 C · 参数校验 | `tools/gui/node_logic.py` (`node_ss_abc`) |

## C. 待补 / 诚实说明

1. `sspred` 先验动力学预测器 与 `sslat`/`sscalib` 属**解析/查表类**, 无外部权重文件 — 不需要 load。
2. JEPA 预测器 (`l4_mani_predictor_*.pt`) 的 `torch.load` 在**调用方**(本地推理服务/引擎), 不在 `predictor_layer.py` 内 — 表里已按"实际加载点"列。
3. `n_dsvl` 走远端 API, **无本地权重**, 不参与"本机推理"; `n_vlm_llm` 已有本地 Qwen2.5-VL-3B 权重 (可本机推理)。
4. 下一版将补: **L4 端到端运行证据** (点 L4 → 上述模型逐帧真前向计数 → 3D 视图产物) 与 **节点→原子技能调用链** 证据。
