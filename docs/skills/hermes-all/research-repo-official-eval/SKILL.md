---
name: research-repo-official-eval
description: "Use when 跑研究仓库官方评测或接其权重 (预检/ckpt config/数据布局)."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [eval-harness, preflight, checkpoint, hdf5, research-repo, research]
metadata:
  hermes:
    tags: [eval-harness, preflight, checkpoint, hdf5, research-repo]
    related_skills: [cross-venv-model-canvas-node, robot-policy-eval-pitfalls, huggingface-hub, hf-weight-download]
---

# 研究仓库官方评测跑通 (与接权重前的准备)

## When to Use

要"把某个研究项目跑起来/出分"或"把它的论文权重接进本工程"时 —— 例如
`zju3dv/INTACT-JEPA`、LeWM、robomimic 系。触发信号: 官方 `scripts/eval_*.sh` / `preflight`、
`load_pretrained`、`config.json not found`、`size mismatch for ...`、
`FileNotFoundError: .../datasets/<x>.h5`。

**顺序铁律**: 预检 → 数据 → config/权重 → 单次 eval 出分 → 才谈接进本工程。
跳过任何一步, 后面全是假结论。

## 1. venv 隔离与 PATH (第一个大坑)

- 研究项目**独立 venv** (常见 py3.10), 本工程 GUI venv (py3.11) 不混装。
- 跑官方脚本必须 `export PATH="<repo>/.venv/bin:$PATH"` —— **放在最前**。
  放后面 (或漏掉) → 脚本选到别的 venv 的 python → 预检一次报一串
  `[FAIL] dependencies: missing: torch, stable-worldmodel, ...` + `No module named 'h5py'`。
  **看到"依赖全缺"先看是不是 python 选错了**, 别急着 pip install。
- `STABLEWM_HOME` / `LOCAL_DATASET_DIR` 等要**显式 export** (官方脚本常不读 `.env`)。
- 需要 `uv` 的安装脚本: `export PATH="$HOME/.hermes/bin:$PATH"`。

## 2. 预检 (preflight) = 最快的诊断面

逐个 FAIL 修, 全部 PASS 再往下:

| 预检项 | 典型根因 | 修法 |
|---|---|---|
| dependencies 全 FAIL | python 选错 (§1) | PATH 把 repo venv 放最前 |
| `dataset/...: missing` | 数据没下 / 路径名不符 | 官方路径常是 `datasets/<子目录>/<name>.h5` (如 `datasets/dmc/reacher_random.h5`), 不是下载时的文件名 → **对齐路径或软链** |
| `checkpoint: cannot resolve one .pt file from policy=...` | 参数要**目录**不是 `.pt`; 且**相对路径会被拼到 `$CACHE/checkpoints/` 下** | 传**绝对路径**; 传目录让它自己找 `.pt` |
| `config.json not found in <folder>` | 资产包只给了 `.pt` | 见 §3 |
| unit tests FAIL | 同上 python 选错 | 同 §1 |
| 代码完整性/`RUNTIME_SHA256SUMS` FAIL | 你改了钉住的文件 | 红线上不许改; 要改就另建配置副本 |
| 分支/worktree WARN | 不在论文分支 | 只是 WARN, 可继续 |

紧急跳过: `INTACT_SKIP_PREFLIGHT=1` (只在已确认预检项都满足时用, 别拿来掩盖 FAIL)。

## 3. 从 checkpoint 形状反推 config.json

研究资产包常只有 `.pt` + 一个 manifest。要点:

1. **config.json 顶层必须是"模型配置"** —— `load_pretrained` 直接
   `instantiate(config)`, 喂训练全量配置会实例化成 dict → `Missing key load_state_dict`。
   做法: hydra compose 训练配置后取 `cfg["model"]` 段落盘。
   ```python
   with initialize_config_dir(config_dir=f"{REPO}/config/train", version_base=None):
       cfg = compose(config_name="<task>", overrides=[...])
   model_cfg = OmegaConf.to_container(cfg, resolve=True)["model"]
   json.dump(model_cfg, open(f"{CKPT_DIR}/config.json", "w"), indent=2)
   ```
2. **一次找齐所有必须项**: `grep -rn '???' config/` → 逐个在 overrides 里给值
   (典型: `model.action_encoder.input_dim`、`model.intent_actor.action_dim`)。
3. **剩余维度从 checkpoint 形状反推, 不要猜** —— 这是最快的"参数探测":
   | 从哪个张量读 | 推断出什么 |
   |---|---|
   | `action_encoder.patch_embed.weight.shape[0]` | **动作块维** (实测 pusht/reacher=10 = 5步×2DOF, **cube=25** = 5×5) |
   | `intent_actor.net.0.weight` 的第二维 | 特征槽数 × embed (576=3槽, 768=4槽) → 决定 `feature_layout` |
   | `intent_actor.net.11.weight.shape[0]` | 输出维 = 2 × action_dim (mean+log_std) |
   | `net.0` 输入 = 槽数×embed ⇒ 无额外嵌入 | `action_emb_dim=0` (否则默认值会多出 embed 维) |
4. **形状不匹配报错本身就是证据**, 直接读出来改:
   `size mismatch for action_encoder.patch_embed.weight: [10,10,1] vs [25,25,1]`
   → 真实动作维 25。一次只差一处的报错链是正常的, 顺着改。
5. 槽数/`feature_layout` 对不上往往意味着**旧 grammar / 论文运行时**:
   仓库若有 `paper_runtime/`、`compat_runtime/`、`RUNTIME_SHA256SUMS`, 读它的 README
   —— 研究 checkpoint 常**不能**用根运行时加载 (布局已变), 且根仓库会**故意省略 paper launcher**。
   那类运行时: 置 `PYTHONPATH` 最前 + `chdir` 到它 + 显式 `import sitecustomize`。

## 4. 官方数据的下载与"完成"判据

- **多连接下载的"文件大小"不可信**, 按大小判完成会解压出**截断的假数据**。
  完成判据 = 下载器的自有账本/退出码 + `.aria2` 控制文件**消失** + `zstd -t` / `sha256sum -c`。
  实测教训: 差 0.7GiB 就解压 → `zstd: Decoding error (36) Data corruption`;
  tar 报 `Unexpected EOF in archive` → 解压出的 h5 只有 1.9GB (完整 98.9GB)。
- **先看远端仓库树再下** (`https://hf-mirror.com/api/datasets/<repo>/tree/main`):
  实际常是 `*.tar.zst` 单个大包; 包内路径用仓库里的 MANIFEST 确认, 别猜文件名 (猜=404)。
- 压缩比要留够: 22GB 的 `.tar.zst` 实测解出 **98.9GB** (≈4.5×) → 解压前算磁盘, 解完删 tar。
- 只差几百 MB 却极慢 = 本机国际带宽/镜像瓶颈, **换源无用**; 先测国内源确认是全局慢。
- 单写者纪律: `pgrep -x aria2c` 只留一个 (两个进程抢同一文件 → 速率暴跌 + 写坏分片)。

## 5. 渲染后端 (无头评测)

- 默认 `MUJOCO_GL=egl` + `PYOPENGL_PLATFORM=egl`。
- **OGBench 系 (如 `swm/OGBCube-v0`) 上 EGL 会失败** (`GLContext ... NoneType is not callable`)
  → 换 `MUJOCO_GL=osmesa PYOPENGL_PLATFORM=osmesa` (软件渲染, 慢但稳)。DMControl 系 EGL 正常。
- 用官方 `swm.World(env_id, num_envs, image_shape=(224,224))` 起环境 (自动加 `pixels`);
  裸 `gym.make` 只给 state 向量、没有像素。`world.envs` 是 batch `EnvPool`,
  **`reset()` 返回 `(None, info)` —— 观测在 info 里**。

## 6. 录视频取证 (sitecustomize 注入)

不改官方代码, 用 `PYTHONPATH=<patch_dir>` + `sitecustomize.py` hook:
```python
_orig = WorldModelPolicy.get_action
def _patched(self, info, **kw):
    _rec.append(np.asarray(info["pixels"])...)   # 记录策略看到/输出的东西
    return _orig(self, info, **kw)
WorldModelPolicy.get_action = _patched
```
- **补丁的 print 必须走 `stderr`**: stdout 会被第三方库当协议解析 (glfw 载入时对子进程输出
  做 `eval()` → 你的 print 直接变成 `SyntaxError: invalid syntax`)。
- **失败 episode 不得覆盖成功帧**: 只在 `done=True` 时落盘, 否则最后一条失败轨迹把证据覆盖掉。
- 合成视频: 帧 > 1 时用 ffmpeg (`-vf scale=...:force_original_aspect_ratio=decrease,pad=...`
  统一尺寸; `-pix_fmt yuv420p`); Python `imageio` 常缺编码器。
- 采帧前先看统计 (`mean` / 帧间差 / unique 颜色数) 判是否黑帧空帧; **不看图也要有数值证据**。

## 7. 诚实纪律 (不可妥协)

- 没跑通就说没跑通, 不许把"管线通了"写成"功能对齐了"。
- 模型未就绪 → `trained=False` + `reason`, **返回零动作也不返回假动作**。
- 引用官方数字 (如官方 SR 80.22%) 必须标来源文件 (manifest/README)。
- 只跑通一个域 ≠ 项目跑通; 报清楚跑了哪几域、几 episodes、成功率多少。

## 支持文件

- `references/intact-jepa-e2e.md` — INTACT-JEPA 从零到出分的完整命令与踩坑链 (含 h5 布局探测脚本、
  checkpoint 形状反推记录、四域实测数字)。
