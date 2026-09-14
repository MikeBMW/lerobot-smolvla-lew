# 从大归档物化到消费路径 + 官方预检闸 (2026-09-13 实测)

配套: `references/hdf5-blosc-verification.md` (真解码验证) · `scripts/verify_h5_dataset.py`
交叉: `unattended-pipeline-supervision` → `references/stage-handoff-and-materialization.md` (为什么会出现"归档在但没人解压")

## 1. 原子落位配方 (绝不要直接写目标路径)

```bash
# ① 完整性 + 容量预算一步拿到: zstd -t 通过时打印解压后字节数, rc=0 才算完整
zstd -t /home/ubuntu/dl_intact/pusht_expert_train.h5.zst
#   → "/home/ubuntu/dl_intact/pusht_expert_train.h5.zst: 46300921856 bytes"   (43.1 GiB)
df -BG --output=avail / | tail -1        # 104G 可用 > 43.1GiB → 够 (峰值 = 解压体积, 不是压缩体积)
# ② 先写 .partial, 完整后才 mv
zstd -d -T0 -c <归档> > <目标>.partial && mv <目标>.partial <目标>
```

必须 `.partial` 的理由: 直接 `zstd -d -o <目标>` 中途被打断/关机, 目标路径上会留下**截断的 h5** ——
下游报 `truncated file` / `filter returned failure` 这类看似无关的错 (见 blosc 那份 reference 的对照表)。
`mv` 原子 ⇒ "路径存在"才等价于"内容完整"。

实测吞吐 (NVMe): 13.14GB 压缩 → 43.1GiB 解压, 约 45~60s (`zstd -d -T0`)。

## 2. 落位后的四条验证 (全过才算可用)

```python
import hdf5plugin, h5py, numpy as np          # ← 必须在 h5py.File 之前 import
f = h5py.File(path, "r")
keys = list(f.keys())                          # pusht: action/ep_len/ep_offset/episode_idx/pixels/proprio/state/step_idx
assert f['ep_offset'][-1] + f['ep_len'][-1] == f['pixels'].shape[0]   # 2336623+113 = 2336736 ✓
last = f['pixels'][-1]; assert last.std() > 5   # 真图 (全黑/全白=假数据)
```

只读 keys/shape 时**不报错**, 一读 `pixels` 数据才炸
`OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin))`
⇒ "我读了几项都没事"是假阳性, 必须真解码抽帧。

## 3. 官方预检闸 (让仓库自己回答"能不能跑")

INTACT-JEPA 的入口 (官方脚本, 不是我们写的):

```bash
cd /home/ubuntu/INTACT-JEPA && \
STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl \
  ./.venv/bin/python scripts/preflight_check.py eval-official \
    --task pusht --cache-dir /home/ubuntu/stable-wm-cache \
    --policy recovery_delta_full_pusht_s3072
```

修好数据集后的实测输出 (尾部):

```
[PASS] cache root: /home/ubuntu/stable-wm-cache
[PASS] dataset/pusht: .../datasets/pusht_expert_train.h5 (HDF5 keys=8)      ← 原来这条是 FAIL
[PASS] checkpoint: .../checkpoints/recovery_delta_full_pusht_s3072/weights_epoch_5.pt
       (317 tensors, sha256=24a598acac5f)
[WARN] git branch: expected junhan, found main @ 235b6a3a92db
[WARN] git worktree: tracked files have local modifications
[FAIL] code integrity: modified:module.py, modified:train.py
[WARN] checkpoint config: verify JEPA/four-slot fields manually: .../config.yaml
[PASS] unit tests: 27 passed in 5.18s
FINAL: FAIL (11 pass, 3 warn, 1 fail)
```

判读 (两个假 FAIL, 不要去"修"):

| 行 | 含义 | 处置 |
|---|---|---|
| `[FAIL] code integrity: modified:module.py, train.py` | **本工程自己的 INTACT 域内微调改动**, 合法 | 只有加 `--strict-git-clean` 才升级成硬闸; 平时不是环境坏 |
| `[FAIL] checkpoint: evaluation requires --policy` | 自己忘了传 `--policy` (第一次跑预检就踩了) | 补参数重跑, 不要去找 checkpoint |
| `[WARN] git branch: expected junhan` | 官方期望的分支 | 非阻塞 |
| `[WARN] checkpoint config: verify JEPA/four-slot fields` | 建议人工核 config.yaml | 按需核 |

预检 PASS 之后 eval 仍要按 §8.6/§9 口径核: `solver_timing.get_cost_calls_mean / candidate_action_steps_mean /
configured_rollout_budget_mean == 0` (零搜索), `actor_warmstart_enabled_mean == 1`, 且逐 seed 结果文件落盘。

## 4. 本次现场的数字 (供下次对照)

- 数据集缓存 `$STABLEWM_HOME` = `/home/ubuntu/stable-wm-cache`, 评测期望 `datasets/<task>_expert_train.h5`
- pusht h5: 18685 回合 / 2336736 帧 / pixels (2336736,224,224,3) / 末帧 mean 248.30 std 22.81
- 已出的四任务表 (09-12, 训练 seed 3072 分片口径): pusht 79.33±4.93 (官方 79.67) ·
  reacher 97.00±2.00 (官方 97.0) · tworoom 78.67±4.04 (官方 78.67) · **cube 未评测**
- 磁盘: 物化后 316G/396G used (85%), 61G free —— 越过 `disk_redline.sh` 的 200G 告警线;
  可回收 ≈37G (已解压的 pusht `.zst` 13G + reacher `.tar.zst` 23.7G 残留, 后者 .h5 早已解压并评测)
- debugpy 启动配置里的关键 env: `STABLEWM_HOME` / `LOCAL_DATASET_DIR` (= cache) · `MUJOCO_GL=egl` ·
  `PYOPENGL_PLATFORM=egl` · `CUBLAS_WORKSPACE_CONFIG=:4096:8` · `HF_ENDPOINT=https://hf-mirror.com` ·
  `PYTHONPATH=<repo>/paper_runtime:<repo>` · `cwd=<repo>/paper_runtime`
