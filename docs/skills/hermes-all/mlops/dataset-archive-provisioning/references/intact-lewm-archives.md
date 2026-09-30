# INTACT / lewm 归档实测案例 (2026-09-13)

## 现场
- 工程: `/home/ubuntu/INTACT-JEPA` (INTACT-JEPA 官方项目 + `paper_runtime/` 评测入口)
- 数据缓存: `STABLEWM_HOME=/home/ubuntu/stable-wm-cache`, 数据集目录 `datasets/`
- 下载暂存: `/home/ubuntu/dl_intact/` (aria2 落盘处)
- 证据目录: `/home/ubuntu/l4_ab/intact_results/` (autopilot.log / aria2_*.log / 逐 seed json / SUMMARY.md)

## 报错原文
```
FileNotFoundError: [Errno 2] Unable to synchronously open file
 (unable to open file: name = '/home/ubuntu/stable-wm-cache/datasets/pusht_expert_train.h5',
  errno = 2, error message = 'No such file or directory', flags = 40, o_flags = 0)
```
VSCode debugpy 配置 "② 论文权重 · Direct 官方协议评测 (需数据集)" 起 `paper_runtime/eval.py` + `solver=prior_only`。

## 根因
`/home/ubuntu/dl_intact/pusht_expert_train.h5.zst` (13,136,247,974 B, 09-13 03:51 下完, `zstd -t` 通过, 头部声明
解压后 **46,300,921,856 B**) 从未解压。解压那一步在 `intact_autopilot` 流水线上, 而 `autopilot.log` 显示整条
流水线 **09-12 15:30 就已「流水线结束」** → 03:51 才下完的归档没人接管；之后 07:42 关机重启也无从补。

## 修复与验证 (实际命令)
```bash
zstd -t /home/ubuntu/dl_intact/pusht_expert_train.h5.zst          # → 46300921856 bytes
zstd -d -T0 -c /home/ubuntu/dl_intact/pusht_expert_train.h5.zst \
  > /home/ubuntu/stable-wm-cache/datasets/pusht_expert_train.h5.partial \
  && mv .../pusht_expert_train.h5.partial .../pusht_expert_train.h5
```
验证 (INTACT venv `./.venv/bin/python`):
```
keys = action / ep_len / ep_offset / episode_idx / pixels / proprio / state / step_idx
episodes = 18685 · pixels = (2336736, 224, 224, 3)
ep_offset[-1] 2336623 + ep_len[-1] 113 = 2336736 = pixels 首维   ← 索引自洽
末帧 224x224x3 mean 248.30 std 22.81 (>5 = 真图)
```
下游复跑 (rc=0, 与历史记录一致):
```bash
bash ~/l4_ab/run_paper_direct.sh pusht recovery_delta_full_pusht_s3072 42 100
# success_rate 77.0 ; get_cost_calls_mean 0.0 / candidate_action_steps_mean 0.0 / actor_warmstart_enabled_mean 1.0
```
预检: `scripts/preflight_check.py eval-official --task pusht --cache-dir ... --policy recovery_delta_full_pusht_s3072`
→ 11 pass / 3 warn / 1 fail (唯一 FAIL = code integrity: module.py, train.py 本地改动 = 自己的 INTACT 微调, 非异常)

## 坑 (本案例踩到的)
- **hdf5plugin**: 只 `import h5py` 打开不报错、读 keys/形状也不报错, 一读 `pixels` 就
  `OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin))`。
  必须 `import hdf5plugin, h5py`。极易被误判成"数据坏了一半"。
- **reacher 大 tar 与评测无关**: `datasets/reacher.tar.zst` (23,750,614,946 B, 内含 **98,905,882,624 B** 的
  reacher.h5) 从未解压; 已出的 reacher 官方评测 (97.00±2.00, 官方 97.0) 用的是
  `datasets/dmc/reacher_random.h5` (stats 来源)。看 `autopilot.log` 里
  `Cached 'action' from '.../dmc/reacher_random.h5'` 才确认的, 不能凭名字推断。
- **稀疏半成品副本**: `dl_intact/reacher.tar.zst` apparent 23G / **实占 9.0G** + `.aria2` 残留 =
  同一文件的半成品；`datasets/reacher.tar.zst` 才是完整那份。看门狗因此每 6 分钟报
  「卡住 (13136247974B) 重启续传」(实为 pusht 那份早已下完)。

## 回收记录 (本次)
| 删除 | 实占回收 | 依据 |
|---|---|---|
| dl_intact/pusht_expert_train.h5.zst | 12,528 M | h5 已解压并验证 == 46300921856 B |
| dl_intact/reacher.tar.zst + .aria2 | 9,177 M | 稀疏半成品副本 |
| datasets/reacher.tar.zst | 22,651 M | 评测未使用 (用 dmc/reacher_random.h5) |

前: used 317G / 可用 60G → 后: used 273G / 可用 102G (红线 300G ✅)
留档: `/home/ubuntu/l4_ab/intact_results/released_archives.log` (sha256 + size + URL + 替代说明)

来源 URL (重下用):
- pusht: `https://hf-mirror.com/datasets/quentinll/lewm-pusht/resolve/main/pusht_expert_train.h5.zst`
  sha256 `7cfbd6d90fa2f27876379a5ff169715a36ed82edbda64f9e5b5bfa34d212f318`
- reacher: `https://hf-mirror.com/datasets/quentinll/lewm-reacher/resolve/main/reacher.tar.zst`
  sha256 `4ff2385e49712caa89f21b8e0a246e2614b621d3f22cf2d1224d845e879a1cc2`

## 相关既有产物 (别删)
`datasets/cube_single_expert.h5` (97.2G) · `tworoom.h5` (12.2G) · `zmax_insert*.h5` ·
`datasets/zmax_datasets.json` (数据集清单, 控制台数据集页只读它) · `l4_ab/intact_results/*.json|SUMMARY.md`
