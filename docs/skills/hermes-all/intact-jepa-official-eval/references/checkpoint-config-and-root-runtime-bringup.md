# 官方 E1 权重 bring-up（config.json 合成 · 根运行时 · swm.World 出视频）

场景: 拿 HF `INTACT-JEPA/INTACT` 的官方权重在本机真实跑起来（eval 出分 / 出视频证据），
**不是**我们微调过的 `recovery_delta_full_<task>_s3072` 那条链路（那条见 SKILL.md 正文 + paper-runtime-eval-runbook）。
本文件全部为 2026-09 实测，含 6 处「照着报错走会走进沟里」的坑。

## 0. 两套权重 / 两套运行时（先分清，别混）
| HF 内容 | 是什么 | 用哪个运行时 |
|---|---|---|
| `INTACT-no-previous-action/*` | **E1**（current clean runtime）| 仓库根的 `scripts/eval_official.sh` |
| `INTACT-unified/*` | **paper checkpoints**（README 原文: 需 frozen paper runtime + **legacy Actor checkpoint grammar**）| `paper_runtime/` |
| `checkpoints_hf/expanded/checkpoints/intact_goal_history_free_<task>_s42_p77_v1/` | 我们展开后的 4 域 E1 | 同上（E1）|

- 权重 revision 用 `--revision paper-e5-goal-v1` 拉 paper 那套；E1 那套在默认 revision 的 `INTACT-no-previous-action/`。
- **不要**为了让权重 load 上去就随手改 `module.py` —— 官方数字要匹配的运行时+权重组合。
  改代码只用于"先跑通看画面"，并且必须 `INTACT_SKIP_PREFLIGHT=1`（否则 code-integrity 检查 FAIL）。

## 1. 坑①：checkpoint 目录缺 `config.json`（E1 tar 包只含 .pt）
```
FileNotFoundError: config.json not found in <checkpoint folder>
```
`load_pretrained` → `instantiate(config)`，所以 **config.json 顶层必须就是模型配置**
（`_target_: jepa.JEPA` + `encoder/predictor/intent_actor`），**不是**整个训练配置。
存整个 train config 会得到
`omegaconf.errors.ConfigAttributeError: Missing key load_state_dict`（instantiate 返回 dict 而非 nn.Module）。

**合成配方**（`config/train/` 下 hydra compose，再取 `["model"]`）:
```python
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
with initialize_config_dir(config_dir="<repo>/config/train", version_base=None):
    cfg = compose(config_name="intact_goal", overrides=[
        "img_size=224", "embed_dim=192", "history_size=3", "num_preds=1",
        "model.action_encoder.input_dim=<A>",     # ← 见第 2 节，从权重形状读
        "model.intent_actor.action_dim=<A>",
        "model.intent_actor.action_emb_dim=0",
        "model.intent_actor.feature_layout=three_slot",
    ])
json.dump(OmegaConf.to_container(cfg, resolve=True)["model"], open(dst, "w"), indent=2)
```
`config/train/model/intact.yaml` 里有且仅有 **两个 `???`**（OmegaConf 强制缺失值），必须显式给:
`action_encoder.input_dim` 与 `intent_actor.action_dim`。别猜 —— 见下。

## 2. 坑②：架构参数**从权重张量形状反推**，不要猜
`MissingMandatoryValue` / `size mismatch` 会一个个吐出来，但一轮一轮试很慢。一次性反推:
```python
sd = torch.load("<...>/weights_epoch_1.pt", map_location="cpu"); sd = sd.get("state_dict", sd)
sd["action_encoder.patch_embed.weight"].shape      # (A, A, 1)  → action_dim = A
sd["intent_actor.net.11.weight"].shape             # (2A, 1024)  → 输出 mean+log_std
sd["intent_actor.net.0.weight"].shape              # (1024, slots*192 + action_emb_dim)
```
实测:
- `action_dim`（= action chunk 维度 = **action_block × DOF**，不是 env 的 DOF!）:
  **pusht 10**（5×2）· **reacher 10**（5×2）· **cube 25**（5×5）。
- `intent_actor.net.0` 输入 **576** ⇒ `slots×192 + action_emb_dim = 576`，实测 **`action_emb_dim=0`**（默认 192，写错就 `[256,384] vs [256,768]` 之类）。
- `module.py`: `latent_slots = 4 if feature_layout == "five_slot" else 3`，且 `actor_features` 是
  `cat([z, intent, z*intent, prev_act_emb])` ⇒ `four_slot`=768、`five_slot`=960。**576 不属于现有任何布局** ⇒
  E1 权重是 **3 槽（legacy grammar）**；要跑就得给 `module.py` 加 `three_slot` 分支（配套 `VALID_FEATURE_LAYOUTS` 加名）。
  这是"跑通优先"的权宜；要官方数字请用匹配的运行时/权重。

## 3. 坑③：`eval_official.sh` 的 policy 参数 = **绝对路径** 指向**目录**
```
[FAIL] checkpoint: cannot resolve one .pt file from policy=<相对路径>
```
`preflight_check.py: resolve_checkpoint` 对非绝对路径会拼到 `$STABLEWM_HOME/checkpoints/` 下 ⇒ 永远找不到。
传**目录的绝对路径**（脚本自己找 `.pt` + `config.json`）。用法:
```bash
bash scripts/eval_official.sh <solver=direct> <task=cube> \
  /abs/path/to/checkpoints_hf/expanded/checkpoints/intact_goal_history_free_<task>_s42_p77_v1 <seed=42> <n>
```

## 4. 坑④：PATH 顺序 → 预检选错 python，报"依赖全缺"的假 FAIL
预检 shell 出去调 `python`。把 `/home/ubuntu/.hermes/bin` 放 PATH 最前会让它选中 hermes 自己的 venv:
```
[FAIL] dependencies: missing torch, stable-worldmodel, ...     ← 假 FAIL，别去装依赖
[FAIL] unit tests: /home/.../.hermes/hermes-agent/venv/bin/python: No module named pytest
```
**修复**: 目标 venv 放最前 `PATH="$ROOT/.venv/bin:/home/ubuntu/.hermes/bin:$PATH"`（uv 仍需在 PATH 才有）。

## 5. 坑⑤：官方 HDF5 是**扁平存储** + 键名优先级会喂错输入
- 结构实测（cube）: 顶层 `pixels (2010000,224,224,3)` · `action (N,d)` · `observation (N,28)` · `ep_idx/ep_len/ep_offset`。
  **按 episode 取帧必须走 `ep_offset/ep_len` 切片**，没有 per-episode group。
- 判断键存在不要用 h5py 的 `in`:
  `"ep_offset" in f.keys()` 不可靠 → 用 `{"ep_offset","ep_len"} <= set(f.keys())`；
  `str(ep) in grp` 会得到 `ValueError: truth value of an array ... is ambiguous`。
- **键名优先级坑（静默喂错数据）**: 通用选择器
  `next(k for k in f.keys() if "obs" in k.lower() or "pixel" in k.lower())` 命中 **`observation`** →
  把 `(9,28)` 的**状态向量**当像素喂给 ViT → `ValueError: not enough values to unpack (expected 4, got 1)`。
  **必须显式优先 `"pixel"`**。
- 官方数据用 HDF5 **插件压缩** → 读之前 `import hdf5plugin`（否则
  `OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin))`）。

## 6. swm.World 路径：**不依赖数据集**也能出真视频（smoke 用）
裸 `gym.make("swm/<Env>-v0")` 的 obs 是 ndarray（无 pixels）；官方封装才给标准 obs dict:
```python
import stable_worldmodel as swm               # 先 import 才注册 gym 环境名
world = swm.World("swm/<Env>-v0", num_envs=1, image_shape=(224,224))   # 自动加 pixels
pool  = world.envs                                         # EnvPool，batch API，不可下标
_, obs = pool.reset(seed=42)                               # ★ 返回 (None, info)：观测在 info 里
obs = {k: torch.as_tensor(np.asarray(v)) for k, v in obs.items()
       if np.asarray(v).dtype.kind in "fiub"}              # 模型要 torch.Tensor（numpy 会 .size(0) 崩）
px = obs["pixels"];  obs["pixels"] = px.permute(0,1,4,2,3)  # NHWC → NCHW（否则 通道数=224）
act = model.get_action(obs, horizon=5)                      # 直接调，无需 solver
pool.step(act[..., :DOF])                                   # chunk 是 5×DOF，env 只要 DOF
```
- `model.get_action(info_dict, horizon=N)` 是直路。**别手搓 `WorldModelPolicy`** —— 它会去调 solver:
  `AttributeError: 'JEPA' object has no attribute 'configure'` ⇒ 用官方 `direct_solver.DirectSolver` / 官方脚本。
- 模型推理**需要 `goal`**（契约里是 **5 维 `[B,T,C,H,W]`**）→ 数据集采样；没有数据集时可给占位（能出画面，
  但动作精度不算数，汇报时必须说明是占位）。
- `nan_to_num` 清洗 obs：env 的 `action` 字段首帧常是 NaN（`_coerce_action_history` 会抛 non-finite）。
- 字符串字段（`id` 之类）不能进 tensor → 只转 `dtype.kind in "fiub"`。

## 7. 渲染后端按环境分家
| 环境 | `MUJOCO_GL` | 现象 |
|---|---|---|
| dmcontrol（reacher） | `egl` | 正常 |
| OGBench / cube | **`osmesa`** | egl 下 `TypeError: 'NoneType' object is not callable`（来自 `mujoco/egl/__init__.py` 析构）|

osmesa 慢一些，但能出帧。析构阶段那两条 TypeError 是**无害噪声**，不影响已保存的帧。

## 8. 坑⑥：注入补丁**绝不能 print 到 stdout**
`sitecustomize.py` 里 `print("[patch] hooked")` 会让 glfw 的版本探测炸:
```
File "<string>", line 1
    [patch] WorldModelPolicy.get_action hooked
SyntaxError: invalid syntax
```
原因: glfw 的 `_glfw_get_version` 对子进程输出做 `eval(out)`。**补丁一律打到 stderr**（或彻底静音）。

## 9. 出视频的最小验证（看不到画面时的自检）
```bash
ffprobe -v error -show_entries stream=width,height,nb_frames,duration -of csv=p=0 <mp4>
python3 -c "import numpy as np;f=np.load('frames.npy');print(f.shape, f.mean(), np.abs(np.diff(f.astype(float),0)).mean())"
```
判据: `mean` 不是 0/255 且**帧间差 > 0**（真在动）· 分辨率符合预期。
**`done=True` 不等于任务真完成** —— 我们踩过 done 早判（阈值太松）:
"完成"要用引擎自己的判据量复核（如 `peg_head()` 到孔底距离，**别用 `tr["peg"]`，那是 obs[4:7]=速度**）。

## 10. 相关
- 主链路（我们微调权重 · 官方 100 局口径 · 视频归档）: `SKILL.md` 正文 + `references/paper-runtime-eval-runbook.md`
- 数据集缺失/解压/回收: `dataset-archive-provisioning`
- 把模型接进画布节点（跨 venv 桥 / 三处注册 / 孤岛检查）: `integration-level-audit`、`cross-venv-model-canvas-node`
