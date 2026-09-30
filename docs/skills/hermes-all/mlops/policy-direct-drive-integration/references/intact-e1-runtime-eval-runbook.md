# INTACT-JEPA 根运行时 (E1) 官方 eval 跑通实录 — 环境/数据/config.json/预检

2026-09-12 本机实测。**与 `native-paper-weight-vs-domain-finetune-2026-09-12.md` 互补**:
那份讲 **paper_runtime + paper 权重** 的口径 (prior_only 求解器、env_*.mp4 产物、权重命名撞车);
这份讲 **根运行时 + `INTACT-no-previous-action` (E1) 权重 + `scripts/eval_official.sh`** 这条路 —— 它的
预检会给你 14 项体检, 但 checkpoint 必须先自造 `config.json`, 否则卡在 "起不来" 阶段。

> ⚠️ **SKILL.md 待并入 (§7/§8)**: 本次同时得到的类级结论 (接管式集成的一致性守卫、安全参与上限 ≈30%、
> 日志列当几何量的坑、done 判据阈值、跨进程漂移) 因 SKILL.md 本轮写入被 read-before-write 守卫拦截,
> 暂存在本文件 §7/§8, 下次补进 SKILL.md 正文。

## 1. 环境 (必须 python 3.10)
```bash
export PATH="$HOME/.hermes/bin:$PATH"            # install.sh 要求 uv 在 PATH
cd INTACT-JEPA && bash scripts/install.sh cu124 # uv venv --python 3.10 + torch 2.6.0+cu124 + requirements-dev
```
- 报 `Python 3.10 or uv is required.` = uv 不在 PATH (不是没装)。
- 中途被杀也能续: `uv pip install --python .venv/bin/python -r requirements-dev.txt -i <mirror>`。
- 镜像: 清华 `pypi.tuna.tsinghua.edu.cn` 实测 **403** → 换 `mirrors.aliyun.com/pypi/simple/`。
- 系统库 `libegl1 libgl1 libglfw3 libglew2.2 libosmesa6`; 运行需 `MUJOCO_GL=egl PYOPENGL_PLATFORM=egl`。
- 自检 8 个包: torch / stable_worldmodel / lightning / hydra / ogbench / mujoco / h5py / timm。

## 2. 数据下载 (HF 国内极慢 → aria2 多线程 + 断点续传)
| 域 | repo (HF) | 文件 | 体积 |
|---|---|---|---|
| pusht | `quentinll/lewm-pusht` | `pusht_expert_train.h5.zst` | 12.23 GiB → 解压 **43.12 GiB** |
| reacher | `quentinll/lewm-reacher` | `reacher.tar.zst` | 22.12 GB |
| cube / tworoom | `quentinll/lewm-cube` / `quentinll/lewm-tworooms` | `.h5` | — |

```bash
aria2c -x 16 -s 16 -k 1M -c --file-allocation=none --max-tries=0 --retry-wait=10 \
  -d <dir> -o <file> "https://hf-mirror.com/datasets/<repo>/resolve/main/<file>"
```
**完成判据 = 侧车 `<file>.aria2` 消失**。用 `ps | grep aria2c` 判完成会**提前**开解压 →
`zstd: Data corruption detected (36)` 是**假损坏** (文件其实还差几百 MB)。解压前先 `zstd -t` 校验。
`hf_transfer` 已弃用 (新版提示用 `HF_XET_HIGH_PERFORMANCE`); 无 HF token 时 CDN 会限速到 ~0.1MB/s。
数据集放 `$STABLEWM_HOME/datasets/`, 且 `STABLEWM_HOME` = `LOCAL_DATASET_DIR` = 缓存根。

## 3. 权重的两套运行时 (选错就起不来)
- `INTACT-no-previous-action/*` (E1) → 配根 `scripts/eval_official.sh`。
- `INTACT-unified/*` → HF revision `paper-e5-goal-v1`, **必须配仓库自带 `paper_runtime/`** (README 称之为
  "isolated compatibility runtime for the published paper checkpoints"; 仓库故意不含 legacy launcher)。
- **grammar 不兼容实锤**: E1 权重 `intent_actor.net.0.weight = (1024, 576)` = 3 slot × 192,
  而当前 `module.py` 的 `actor_features` 是 `[z, intent, z*intent, prev_act_emb]` = 4 × 192 = **768** →
  报 `mat1 and mat2 shapes cannot be multiplied (Nx768 and 576x1024)`。
  ⇒ 要么用配套 runtime, 要么给 `VALID_FEATURE_LAYOUTS`/`actor_features` 补 3-slot 分支 (动了代码就
  `INTACT_SKIP_PREFLIGHT=1`)。

## 4. checkpoint 目录必须自造 config.json (最容易卡死的一步)
tar 包里**只有 `.pt`, 没有 `config.json`**。报错链会依次出现, 认出来就不用逐个猜:
```
config.json not found in <folder>
 → MissingMandatoryValue: model.action_encoder.input_dim      (还有 intent_actor.action_dim)
 → load_state_dict size mismatch ... (shape 从 checkpoint 反推)
 → Missing key load_state_dict                                 (顶层存了整个训练配置 → instantiate 返回 dict)
```
```python
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
import json
with initialize_config_dir(config_dir="<repo>/config/train", version_base=None):
    cfg = compose("intact_goal", overrides=[
        "img_size=224", "embed_dim=192", "history_size=3",
        "model.action_encoder.input_dim=10",          # 实测 PushT action chunk = 10 (别照数据集 action 列宽猜 2)
        "model.intent_actor.action_dim=10", "model.intent_actor.action_emb_dim=0",
        "model.intent_actor.feature_layout=four_slot",
    ])
json.dump(OmegaConf.to_container(cfg, resolve=True)["model"], open(ckpt_dir / "config.json", "w"), indent=2)
```
要点:
- **顶层必须是模型配置段** (含 `_target_: jepa.JEPA`、`intent_mode: goal_displacement`), 不是整个训练配置 ——
  `load_pretrained` 会直接 `instantiate(config)`。
- 缺的 `???` 字段**从 checkpoint 张量形状反推**:
  `action_encoder.patch_embed.weight (10,10,1)` ⇒ 动作维 10; `intent_actor.net.11.weight (20,1024)` ⇒ 输出 2×10;
  `net.0.weight (1024,576)` ⇒ 输入 576 = 3×192 ⇒ `action_emb_dim=0`。
- `latent_slots = 4 if feature_layout == "five_slot" else 3` —— 576 就说明是 3 slot。
- 有 `ViT-tiny ... image_size 224 / patch 14` 打印 = config 已被读到, 前进了一大步。

## 5. eval 命令 + 预检坑 (14 项体检)
```bash
cd INTACT-JEPA
export PATH="$PWD/.venv/bin:$HOME/.hermes/bin:$PATH"     # ★ INTACT venv 必须排最前
export STABLEWM_HOME=<cache> LOCAL_DATASET_DIR=<cache> MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
bash scripts/eval_official.sh direct pusht /abs/path/to/ckpt_dir 42 20   # ★ 绝对路径 + 传目录
```
- **checkpoint 要传目录且必须绝对路径**: 相对路径会被拼到 `$STABLEWM_HOME/checkpoints/<相对路径>` → 解析失败
  (`cannot resolve one .pt file from policy=...`)。
- PATH 顺序错 → 预检抓到别的 venv python → `dependencies: missing: torch, stable-worldmodel, ...` 全 FAIL。
- 预检含 **41 文件 SHA-256 代码完整性** + 27 单测 + HDF5 keys + 显存; 改过仓库代码 → `INTACT_SKIP_PREFLIGHT=1`。
- 模式: `direct | pure_cem | actor_cem | guarded_a` (对应 `config/solver/*`); Direct = 免搜索。
- 结果 json: `success_rate` / `episode_successes` / `solver_timing.forward_calls_mean`(≈5, 证明免搜索) /
  `solve_time_mean`(≈0.1 s/step)。
- **本机基线 (回归对照)**: pusht direct 20 episodes **70.0%** (两次独立跑同值), 论文同类口径 80.22%。

## 6. 录"模型真实运行"视频
- 走 **paper_runtime** 那条路时, 评测本身就会落**每 episode 一段 `env_*.mp4`** (见互补 reference: 跑前
  `rm env_*.mp4`, 跑完立刻复制走, 否则被覆盖)。
- 走根 `eval_official.sh` 时无渲染开关 → 用 `PYTHONPATH` 挂 `sitecustomize.py` **patch 库内
  `swm.policy.WorldModelPolicy.get_action`**, 拦 `info_dict["pixels"]` 存帧, 合成:
  `PIL` 导 PNG 序列 + `ffmpeg -framerate 8 -i f%04d.png -c:v libx264 -pix_fmt yuv420p`
  (imageio 可能缺编码器 → 别依赖它)。
- hook 只在部分调用路径触发 (实测 20 episodes 只抓到 50 帧) → 视频当**代表性片段**, 成功率以 json 为准,
  并且在回复里写清"视频多少帧 / 代表多少 episode", 别让人以为视频=全部。

## 7. (待并入 SKILL.md) 接管式集成: 一致性守卫 + 不替换控制器本体

在**已有闭环控制器** (解析链 / 蒸馏 MLP 状态机) 的机器人上接模型时, **不要整体替换控制器对象**:
这类控制器通常**自带域外兜底** (实测注释 `状态出训练域 → 解析守卫兜底`, 判据 d_guard / DOMAIN_SIGMA)。
换掉对象 = 兜底一起丢 → 域外模型输出坏动作无人拦 → 闭环必崩 (实测 0/10)。

```python
u_eng = self.inner.forward(obs)          # ① 原控制器永远先算 = 安全基线 (含其域判定+兜底)
u_act = actor(z, intent, prev)           # ② 模型建议
if np.abs(u_act - u_eng).max() <= TOL:   # ③ 一致才采纳
    return u_act
return u_eng
```
- 报告必须同时给 **actor 采纳次数 / 引擎兜底次数** — 采纳 0 次 = 模型是摆设, 不算接管。
- 控制器常是调度器**融合** `u = w_ff·u_ff + (1−w_ff)·u_fb`; 学"建议 u_ff"而执行融合值 = 标签错配,
  训练标签应取**真正下发的动作** (实测引擎落 `u_fuse_vec`)。

TOL 扫描 (10 seed, 同一模型): 0.05 → 100% / 9%参与 · **0.08~0.15 → 100% / 24~27%** · 0.3 → 0% / 86% ·
0.6~1.0 → 0% / 100%。⇒ **安全参与上限 ≈30%, 模型主导 (>50%) 必崩**; 硬 CAP 限流过刚 (实测压到 7%)。
**观测完备化不抬高上限**: 46D vs 53D (+u_fb+w_ff+u_ff) 在 100% 成功率下参与率 27% vs 24% → 上限来自任务/控制器结构。

## 8. (待并入 SKILL.md) 追加 Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把日志列当几何量 | `tr["peg"]` 是 **obs[4:7]=速度** (cur=[x3,grip1,**v3**,_pc3,goal_p3,…]) → "离孔 135mm" 假结论 (一轮踩两次) | 复核用引擎自己的量 `peg_head()` / `_goal_p()` |
| 在 wrapper 内渲染/记录 | 同脚本 actor 采纳率 27%→77% 且整轮失败 | 录制走引擎 `_frame_sink` 钩子; wrapper 与评估脚本逐行一致 |
| 信 `done=True` 不验物理 | `insert_depth` 阈值过松 (6mm) → `done=True` 但目检"没插进去" (残余 4.5~5mm) | 收紧到 2mm 才视觉真插入 (代价成功率 ~100%→73%); 验收用引擎判据量 |
| 单进程 100% 当泛化 | metaworld 布局**每进程漂移** | 守卫/成功率结论必须跨进程多次重复 |
