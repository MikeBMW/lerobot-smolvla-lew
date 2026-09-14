# INTACT-JEPA 端到端实录 (2026-09-13, 本机 Linux/RTX4060)

从零到"官方评测出分 + 录到视频 + 接进画布节点"的完整命令与踩坑链。

## 0. 环境

```bash
# 独立 venv (py3.10), 与 GUI venv (py3.11) 隔离
export PATH="$HOME/.hermes/bin:$PATH"          # uv 在这里
bash scripts/install.sh cu124                  # 或按 docs/INSTALL.md
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache
export LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
```

预检时 **必须** `export PATH="<repo>/.venv/bin:$HOME/.hermes/bin:$PATH"` (repo venv 在最前)。
踩过的坑: 把 `.hermes/bin` 放前面 → 预检选到 hermes 的 python → 一次报 5 个 FAIL
(`missing: torch, stable-worldmodel, ...` + `No module named 'h5py'`), 误导性极强。

## 1. 数据布局探测 (10 行, 先探再写读法)

官方 h5 有两种布局, 读错就是静默错字段:

```python
import h5py
f = h5py.File(path, "r")
def show(g, pre="", d=0):
    if d > 2: return
    for k in list(g.keys())[:8]:
        o = g[k]
        if hasattr(o, "shape") and o.shape: print(f"  {pre}{k}: {o.shape} {o.dtype}")
        elif hasattr(o, "keys"): print(f"  {pre}{k}/"); show(o, pre+"  ", d+1)
show(f)
```

实测结果 (cube, 扁平布局):
```
action:      (2010000, 5)    float32
observation: (2010000, 28)   float64
pixels:      (2010000, 224, 224, 3) uint8
ep_len:      (10000,)  int32          ← episode 数 = 10000, 不是 2010000!
ep_offset:   (10000,)  int64
```
读法: `ds[off : off+len]` (off/len 取自 ep_offset/ep_len)。

另一种布局是 Group (每 episode 一个 dataset) → `list(grp.keys())` 后取键。

**5 个坑**:
1. `str(ep) in grp` → `ValueError: The truth value of an array with more than one element is ambiguous`
   (h5py `__contains__` 不可靠) → 一律 `list(grp.keys())` 再判。
2. `"ep_offset" in f.keys()` 静默 False → 用 `{"ep_offset","ep_len"} <= set(f.keys())`。
3. 键选择器 `"obs" in k or "pixels" in k` 先命中 `observation` → 取到 28 维状态当图像 →
   ViT `expected 4, got 1`。**先精确找 `pixel*`**, 找不到再退 `obs*`。
4. 插件压缩未注册 → `OSError: Can't synchronously read data
   (can't open directory (/usr/local/lib/plugin))` →
   `import hdf5plugin` + `HDF5_PLUGIN_PATH=hdf5plugin.PLUGIN_PATH`。**两个 venv 都要装**。
5. 不存在的数据要诚实报错, 不要 fallback 到"猜一个形状"。

## 2. checkpoint config.json 复现

`load_pretrained(policy)` → `_resolve` → `_resolve_folder` → `instantiate(config)`。
所以 config.json **顶层必须是模型配置**。

顺序 (每步都被 `size mismatch` 驳回一次, 属正常):
```python
# 1) hydra compose 取 model 段
with initialize_config_dir(config_dir=f"{REPO}/config/train", version_base=None):
    cfg = compose("intact_goal", overrides=[
        "history_size=3",
        "model.action_encoder.input_dim=<动作块维>",
        "model.intent_actor.action_dim=<动作块维>",
        "model.intent_actor.action_emb_dim=0",
        "model.intent_actor.feature_layout=four_slot",   # → latent_slots=3 (576)
    ])
json.dump(OmegaConf.to_container(cfg, resolve=True)["model"],
          open(f"{CKPT}/config.json", "w"), indent=2)
```

形状反推记录 (四个域**共享**同一动作律结构):

| 张量 | pusht / reacher | cube | 推断 |
|---|---|---|---|
| `action_encoder.patch_embed.weight` | `[10,10,1]` | `[25,25,1]` | 动作块维 = 5步 × DOF |
| `action_encoder.embed.0.weight` | `[768,10]` | `[768,25]` | 同上 |
| `intent_actor.net.0.weight` | `[1024,576]` | `[1024,576]` | 576 = 3槽×192 → `feature_layout=four_slot` (代码: `latent_slots = 4 if five_slot else 3`), 且 **`action_emb_dim=0`** (无额外嵌入) |
| `intent_actor.net.11.weight` | `[20,1024]` | `[50,1024]` | 输出 = 2×action_dim (mean+log_std) |

`grep -rn '???' config/train/` → 只有 `input_dim` 和 `action_dim` 两个必须项。

## 3. 官方 eval

```bash
cd $REPO
export PATH="$REPO/.venv/bin:$HOME/.hermes/bin:$PATH"
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl          # OGBench 换 osmesa
bash scripts/eval_official.sh direct <task> "$REPO/checkpoints_hf/expanded/checkpoints/<ckpt_dir>" 42 5
```
- checkpoint 传**绝对目录** (相对路径会被拼到 `$CACHE/checkpoints/` 下 → 解析失败)。
- 数据路径要对齐官方期望: 官方读 `datasets/dmc/reacher_random.h5`, 而下载解出来是
  `datasets/reacher/reacher.h5` → `cp`/软链到期望路径。
- 实测成绩 (官方直连口径, 非我手写):
  - **cube: 100% (5/5)**, `solve_time 0.135s/step`, `intent_norm 11.85`,
    `forward_calls 5`, `candidate_sequences 0` (零搜索 ✓)
  - **pusht: 70% (14/20)**, 官方报告 80.22% (差在数据/配置口径, 记清楚别混)
  - reacher: 需完整数据 (压缩包 22GB → 解出 **98.9GB**, 只解到 1.9GB 时为截断假数据)

## 4. 录视频 (不依赖数据集的手写 rollout)

```python
import stable_worldmodel as swm          # 先 import, 它注册 swm/* gym id
world = swm.World("swm/OGBCube-v0", num_envs=1, image_shape=(224, 224))
_, obs = world.envs.reset(seed=42)       # ★ 观测在 info 里, 返回值是 None
for t in range(N):
    od = {k: torch.as_tensor(np.asarray(v))
          for k, v in obs.items() if np.asarray(v).dtype.kind in "fiub"}   # 只转数值键
    px = od["pixels"]
    if px.shape[-1] == 3: od["pixels"] = px.permute(0, 1, 4, 2, 3)         # NHWC → NCHW
    od.setdefault("goal", od["pixels"])   # 占位 goal (真 goal 要数据集采样)
    act = model.get_action(od, horizon=8) # 需 torch.Tensor, numpy 会 `.size(0)` 报错
    a = act.detach().cpu().numpy().reshape(1, -1, act.shape[-1])[:, 0, :env.action_space.shape[0]]
    obs, *_ = world.envs.step(a)
```
坑: numpy 传进模型 → `'int' object is not callable` (`.size(0)` 是方法);
str 字段不能转 tensor; `JEPA` 不是 solver (`AttributeError: 'JEPA' object has no attribute
'configure'`) → 走官方 `eval_official.sh` 的 DirectSolver, 别自己组 `WorldModelPolicy`。

录帧 hook 见 SKILL.md §6 (**print 必须走 stderr**, 帧只在 done=True 时落盘)。

## 5. 官方 4 域视觉对照 (给"这是机械臂吗"类反馈用)

| 域 | env | 画面 | 像机械臂? |
|---|---|---|---|
| pusht | `swm/PushT-v1` | 2D 俯视推块 | ✗ |
| reacher | `swm/ReacherDMControl-v0` | 2-DOF 简笔连杆 + 目标球 | 半 |
| **cube** | `swm/OGBCube-v0` | **Fetch 臂 + 平行夹爪 + 方块** | ✓ |
| tworoom | — | 2D 迷宫网格 | ✗ |

用户说"视频里不是机械臂"时, 先查是哪个域 —— reacher/pusht 本来就长得不像工业机械臂,
不是你录错了。**换 cube 域是最快的回应**。

## 6. 权重解析顺序 (跨会话共用, 禁止重复下 GB 级数据)

1. `--ckpt` / `$NAME_WEIGHTS` 显式路径
2. `$STABLEWM_HOME/checkpoints/<policy>/weights_epoch_*.pt` (别的会话已解包的)
3. HF 资产包 (`INTACT-JEPA/INTACT` 等) 下载 + 解包; `--revision` 指定发布线
   (如 `paper-e5-goal-v1`); 默认 `HF_ENDPOINT=https://hf-mirror.com`
