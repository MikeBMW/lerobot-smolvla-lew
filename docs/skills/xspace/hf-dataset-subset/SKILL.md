---
name: hf-dataset-subset
description: "Use when 只要一小部分数据/磁盘不够 — download a small HF dataset subset."
trigger: "Use when preparing training data from a large HF dataset repo (e.g. lerobot/metaworld_mt50, lerobot/pusht) and the user wants only a small portion (disk-constrained laptop), or when a full download would be tens of GB."
---

# HF 数据集子集下载 (磁盘受限)

用户环境: RTX 4060 笔记本, 用户明确要求 **"不要准备所有数据，你没有那么多磁盘，只要一小部分即可"**。全量下载大数据集 (如 metaworld_mt50 全 498 文件 ~40GB+) 是错误做法。

## 核心方法: 先探结构, 再按需取子集

LeRobot v3 数据集 (如 `lerobot/metaworld_mt50`) 是分片 parquet 仓库:

```
data/chunk-000/file-000.parquet  (~100MB each, 几十个分片)
meta/info.json                    # 数据集规格: features/total_episodes/fps/data_path 模板
meta/stats.json
meta/tasks.parquet
meta/episodes/chunk-000/file-000.parquet  (episode 索引)
```

最小可训练子集 = `meta/*` (全部, 很小) + `meta/episodes/...` + **2-3 个 data 分片** (~200-300MB)。

## 步骤

### 1. 探结构 (HF tree API, 无需登录)

```bash
# 顶层
curl -s "https://huggingface.co/api/datasets/<repo>/tree/main"
# 子目录
curl -s "https://huggingface.co/api/datasets/<repo>/tree/main/data"
# 递归分片列表 (含 size)
curl -s "https://huggingface.co/api/datasets/lerobot/metaworld_mt50/tree/main/data/chunk-000" \
  | python3 -c "import json,sys; [print(x['path'], x.get('size','')) for x in json.load(sys.stdin)[:5]]"
```

注意: tree API 返回 JSON 数组 (不是 dict), 用 `json.load(sys.stdin)[:N]` 切片会 KeyError。子目录不存在时返回 `{"error":"..."}` dict — 先 `head -c 400` 看形状再解析。

### 2. 下载 meta + 子集分片 (resolve URL, curl 直连)

```bash
curl -sL -o meta/info.json "https://huggingface.co/datasets/<repo>/resolve/main/meta/info.json"
# data 分片: 大文件 (~100MB) 前台 curl 易超时 → 后台跑, notify_on_complete
curl -sL -o data/chunk-000/file-000.parquet "https://huggingface.co/datasets/<repo>/resolve/main/data/chunk-000/file-000.parquet"
```

### 3. 核对 info.json 规格

`info.json` 里有 `total_episodes / total_frames / fps / features / data_path 模板 (chunk-{i:03d}/file-{j:03d}.parquet)`。features 决定 npz 转换时的键名 (metaworld: observation.state[4] + action[4] + observation.image 480x480)。

## 陷阱

- **前台 curl 大分片超时**: 100MB 文件走默认超时易死, 用 `terminal(background=true, notify_on_complete=true)` 下载, 完成会通知。
- **tree API 响应形状**: 目录返回数组, 错误返回 dict — 解析前先 head 确认。
- **磁盘预算**: 告诉用户实际占用量 (如 "194M: meta + 2分片"), 让用户确认是否够。
- **不装 huggingface_hub 也能下**: 纯 curl + resolve URL 即可, 不需要 hf CLI / snapshot_download (那个会拉全量)。
- **训练环境**: `python3 -m venv --clear .venv && .venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ ...` (国内镜像)。**清华 pypi 镜像 (pypi.tuna.tsinghua.edu.cn) 会返回 403** (2026-08-01 实测, 阿里云 200) — 换镜像前先 `timeout 15 curl -sI <mirror>/simple/huggingface-hub/` 看 HTTP 码再选。装 torch 大包时 **TMPDIR 必须指向磁盘** (WSL 的 /tmp 是 tmpfs 内存盘 ~8G, pip 解包会撑爆它报 `No space left on device`): `export TMPDIR=$HOME/pip-tmp && mkdir -p $HOME/pip-tmp` 再跑 pip。PEP 668 环境给系统 python 装包用 `--break-system-packages`。
- **官方 PyPI 是兜底, 别判死**: 镜像源都失败时 (阿里云也网络错误), 官方源 `pip install --resume-retries 5 torch torchvision datasets` **能成功** — 2026-08-01 实测 torch 2.11.0+cu128 装通且 CUDA 可用 (下载慢, 断点续传可靠)。pip 报 network error 时加 `--resume-retries 5` 重试, 不要立刻放弃。
- **venv 重建陷阱**: `python3 -m venv --clear .venv` 安装中断后可能留下损坏 venv — 症状: `.venv/bin/pip` 消失 (No such file) 或 pip 报 `certifi/cacert.pem` 路径无效 / site-packages 空。修: `rm -rf .venv && python3 -m venv .venv` 完全重建再装 (别用 --clear)。注意 venv 里 python 版本可能与你预期不同 (系统 python3.14 建的 venv 实际是 3.12) — 以 `.venv/bin/python --version` 为准。

## 参考实例

2026-08-01 metaworld_mt50: 全量 498 文件 (data ~100MB×30+/chunk), 只取 meta(全) + file-000 + file-001 = 194M, 满足 ACT 训练最小子集。转换脚本见 lerobot-smolvla-lew/tools/relay_train.py (pull→JSON→npz→train 一条龙)。
