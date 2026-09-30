# 模型节点 ↔ 加载代码 ↔ 权重 对照 (2026-09-22, 老倪要「能从 VSCode 打开」)

老倪原话: 「我要看到在状态空间里的所有模型相关节点, **有模型加载 load 的实际代码, 我可以从 vscode 里打开**」。
本文是做法 + 踩坑 + 实测出的加载点清单; 产物在仓库:
`docs/design/space_model_nodes_load_map.md` (人看的表) + `reports/model_nodes_v2.json` (机器) + `tools/audit_model_nodes_v2.py` (生成器)。

## 🔴 最重要的一条: 必须分「定义处」和「实际加载点」两段, 否则假阴性一片

节点 `params.source` 指向的多半是**模型定义**文件 —— 例如
`smolvla_lew/action_head.py` (`class SmolVLALewActionHead`)、`smolvla_lew/vlm_encoder.py` (`class SmolVLMEncoder`)、
`manifold/predictor_layer.py` (`class WorldModelPredictor`)。
这些文件里**通常没有** `torch.load` / `from_pretrained` —— 权重是在**调用方**加载的。

第一版审计器把判据写成"文件内必须出现加载调用" ⇒ 12 个 NN 节点只判过 3 个, 全是假阴性(浪费一轮)。
正确判据:
```
定义处   = source + source_symbol 能解析到真实行号            (保证 VSCode 打开看到的是那个类/函数)
加载点   = 全仓搜「权重文件名 / 模型名 + 加载 API」的**命中行** (可能在 policy / 桥 / worker / infer_service)
权重在盘 = glob 该模型权重路径存在
三条都过才算 OK; 缺哪条就在报告里点出来, 不粉饰
```
搜加载点最可靠的信号是**权重文件名**(不是类名): `yolo_peg_live.pt` / `ss_left_brain.npz` /
`l4_mani_predictor_v5.pt` / `intact_l4_current` / `SmolVLM2-500M` / `Qwen2.5-VL`。

## 实测加载点清单 (可直接 `code -g <路径>:<行>`)

| 模型 | 画布节点 | 定义/入口 | **实际加载点** | 权重 (在盘) |
|---|---|---|---|---|
| YOLO 检测器 | `ssyolo` | `policies/yolo_3d/yolo_state_aligner.py:57` (`class YoloStateAligner`) · `:93` `detect_3d` | `docker/z700_infer/infer_service.py:42` `self.yolo = YOLO(yolo_path)` · `tools/real_yolo_perceive.py` · `tools/ss_yolo_on_real.py` | `models/yolo_peg_live.pt`(软链) ✅ |
| 前馈加速器 MLP | `ssff` | `state_space/parallel.py` (`class FeedforwardAccelerator`) | `parallel.py:33` `NPZ_DEFAULT=.../models/ss_left_brain.npz` + `:34` 实例化缓存(避免每 tick np.load 2.1MB) | `models/ss_left_brain.npz` ✅ |
| 流形专家预测器 (JEPA) | `ssmani_exp` | `manifold/predictor_layer.py:112` (`class WorldModelPredictor`) | 调用方加载: `tools/ss_local_infer_server.py` (11D→6D 本地推理) · `tools/ab_mani_yaw.py:87` | `models/l4_mani_predictor_v4/v5.pt` ✅ |
| INTACT L4 (在役) | `ssintact` | `policies/intact/service.py:235` (`def run_once`) | `tools/intact_sw_bridge.py:138` `model = swm.wm.utils.load_pretrained(T["ckpt"])` | `stable-wm-cache/checkpoints/intact_l4_current/weights.pt` ✅ |
| INTACT 插拔(本域微调) | `swintact` | `policies/intact/runtime/node.py` (`class IntactNode`) | 同上 (桥 + `tools/intact_worker.py` 跨 venv) | `checkpoints/intact_goal_optical_insert_v6d5_s3072/weights_epoch_1.pt` ✅ |
| SmolVLM 视觉编码器 | `ssvlm` | `smolvla_lew/vlm_encoder.py:24` `MODEL_ID="HuggingFaceTB/SmolVLM2-500M-Video-Instruct"` | 同文件单例懒加载 · `modeling_smolvla_lew.py:88` `model_id=config.smolvlm_name` | HF 缓存 ✅ |
| Flow-Matching Action Head (DiT) | `ssdec` | `smolvla_lew/action_head.py:205` (`class SmolVLALewActionHead`) | 随策略整体加载 (`SmolVLALewPolicy.from_pretrained`) | 随策略 ckpt |
| SmolVLA 策略 (L3 主控) | L3 档执行链 | `smolvla_lew/modeling_smolvla_lew.py` | `SmolVLALewPolicy.from_pretrained(..., local_files_only=True)` — `tools/eval_insert.py:33` · `tools/rollout_smolvla_lew.py:28` · `tools/eval_policy_corr.py:55` | `outputs/train/smolvla_lew_sim/checkpoints/000300/pretrained_model/model.safetensors` ✅ |
| Qwen2.5-VL (本地 VLM) | `n_vlm_llm` | `tools/vlm_worker.py:17` `--model Qwen/Qwen2.5-VL-3B-Instruct --device cuda:0` | worker 内 `from_pretrained`; lerobot eo1 路径 `modeling_eo1.Qwen2_5_VLForConditionalGeneration.from_pretrained` | `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-VL-3B-Instruct` ✅ (另有 `~/zmax_data/hf_home/hub/`) |
| DeepSeek-VL (远端) | `n_dsvl` | `state_space/scene_vlm.py` (`class SceneVLM`) | 远端 API — **无本地权重**, 不参与"本机推理" | — |
| 先验动力学预测器 | `sspred` | `state_space/dynamics.py` | 同文件解析式(无外部权重) | — |

计算/技能类节点(流形 `manifold_layer.py:65/:154` · 标定 `calibration_layer.py:58/:73` · 原子技能
`state_space/skills/atomic.py` · 编排/推理 `state_space/planner.py` · 校正 `cognition.py` ·
可视化 `tools/gui/ss_bypass_view.py:220/:489`) **无权重可言**, 只要求可打开。

## 复用要点

1. 画布节点已有 **`params.source_symbol`**(符号级) — 比行号抗漂移; 解析行号用
   `^(class|def)\s+<name>` 匹配, 别存死行号。
2. 交表时给**两列**: "定义/入口" 与 "实际加载点", 并标注权重在盘与否 — 老倪要的是"点得开、看得到、跑得起来"三件套。
3. `~/.cache/huggingface/hub/models--*` 是本地权重落盘最常见的家; 查权重先 glob 这里, 再 glob `models/` 与 `outputs/train/`。
4. 本机 **没有 `gh`**; 查 CI/Release 走 GitHub API + `~/.git-credentials`(见技能 zmax-console 的 references/release-and-versioning.md)。
