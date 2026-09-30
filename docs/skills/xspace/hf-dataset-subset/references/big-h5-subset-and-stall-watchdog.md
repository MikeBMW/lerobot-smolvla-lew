# 超大 h5 数据集: 完整性判定 / 子集落位 / 下载卡死看门狗 (2026-09-12 实测)

场景: 官方数据集 = 单个超大的 `.h5` 打在 `.tar.zst` 里 (INTACT 官方: pusht 13.14GB 包、
reacher 23.75GB 包 → 解压出的 `dmc/reacher_random.h5` **98.9GB**)。磁盘只有 ~140GB 可用。

## 1. 先判"这个 h5 到底能不能用" (别拿截断文件跑评测)

```bash
# ① 大小是否等于头里声明的长度
python - <<'PY'
import h5py, hdf5plugin
p = "/path/dmc/reacher_random.h5"
try:
    f = h5py.File(p, "r"); print("OK 顶层:", list(f.keys())[:6]); f.close()
except Exception as e:
    print("BAD", type(e).__name__, e)
PY
```

两种典型报错与根因:

| 报错 | 根因 | 处置 |
|---|---|---|
| `OSError: Unable to synchronously open file (truncated file: eof = 2030042624, sblock->base_addr = 0, stored_eof = 98905882624)` | 归档**没下完就被解压**过 → 文件只有 2.03GB, 头里声明 98.9GB | 等归档完整后重新解压; `stored_eof` 就是该文件应有的字节数, 用它当完整性判据 |
| `OSError: Can't synchronously read data (filter returned failure during read)` | h5 用了 blosc 过滤 (id 32001) 但没注册插件, **或**文件本身截断 | 先 `import hdf5plugin` + `export HDF5_PLUGIN_PATH=<插件目录>` 再开; 仍失败基本就是截断 |

要点: **解压与下载必须串行**。并行去做 (下载未完成就解压) 会产出"看起来存在、实际读不出"的假数据,
后面每一步都会失败并以看似无关的报错呈现 (评测报 filter 失败 / 加载器报 No such file)。

## 2. 子集落位 (99GB → 25GB, 够用又不撞磁盘红线)

流程 (每步都有守卫, 失败就停, 不做"半成品落位"):

```bash
FREE=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "$FREE" -lt 105 ] && { echo "❌ 可用 ${FREE}G < 105G, 不冒险解压"; exit 2; }   # 峰值 = 完整 h5 大小 + 余量
# ① 解压 (峰值 99GB)
tar --use-compress-program=unzstd -xf reacher.tar.zst
# ② 切子集 (流式, 峰值内存有界) —— scripts/h5_subset.py
python scripts/h5_subset.py --src <解压出的完整 h5> --out /tmp/sub.h5 --episodes 100
# ③ 读回校验 (回合数 + 抽样 std) → 通过才落位
cp /tmp/sub.h5 $STABLEWM_HOME/datasets/dmc/reacher_random.h5
# ④ 删掉完整 h5 + 归档 (只留子集), 报可用空间
```

选项对比 (与用户/干系人确认口径再动):

| 方案 | 占盘 | 适用 |
|---|---|---|
| ① 子集落位 (推荐) | 完整 h5 峰值 + 子集, 最终只留子集 | 只需要评测/实况, 磁盘紧 |
| ② 完整落位 | 98.9GB | 需要全量 epoch 训练 |
| ③ 不落位 | 0 | 该任务先不做; 面板/日志要明说"数据集未就位", 不许假装能跑 |

## 3. 下载为什么慢/卡死, 以及怎么自愈

- 实测 `hf_hub_download` 单连接: pusht 前段 ~2MB/s, 之后**卡死** (7.5/13.1GB, 31 分钟零增长)。
- 换 `aria2c` 多连接: `aria2c -x 8 -s 8 -k 4M -c --file-allocation=none --auto-file-renaming=false
  -d <dir> -o <name> "<resolve url>"` (镜像 URL: `https://hf-mirror.com/datasets/<repo>/resolve/main/<file>`)。
- **看门狗 (自愈, 过夜必备)**: 每 5 分钟取一次文件大小; 若没增长 **且** 没有 aria2 在写这个文件
  (避免双写损坏) → `nohup aria2c ... -c` 续传; 全部达到目标大小就退出。
- **不要两个写者写同一文件** (多会话/多进程): 聚合速率会暴跌且可能写坏分片; 只有在确认无进程在写时才重启。

## 4. 给 ETA 前先取"目标大小", 别用感觉

```bash
# API 必须 curl -sL (Python 3.10 urllib 遇 308 直接抛 HTTPError)
curl -sL --max-time 60 "https://hf-mirror.com/api/datasets/quentinll/lewm-reacher?blobs=true" \
  | python3 -c "import json,sys; [print(x['rfilename'], x.get('size')) for x in json.load(sys.stdin)['siblings']]"
# 速率: 取两次大小差 / 间隔
S1=$(stat -c%s f); sleep 60; S2=$(stat -c%s f); echo "$(( (S2-S1)/1024 )) KB/min"
```

实测口径: reacher 包 23.75GB (卡在 22.69GB, ~19KB/s), pusht 包 13.14GB (11.5GB, ~45KB/s)。
⇒ 汇报时给"剩余量 ÷ 实测速率 = 时间点", 并且**明说瓶颈在网络**而不是代码; 大文件直连 (huggingface.co)
与镜像在本机都测过: 30 秒 0 字节, 只有常驻 aria2 能吃到几十~几百 KB/s。

## 5. 与其它会话共享目录

同一台机器可能**多个会话**同时在拉同一份大数据集。动别人的文件前先 `pgrep -af aria2c` 看谁在写,
必要时用 `README_COORD.md` 协商归属; 自己下载换个文件名/目录, 不要接手别人的半成品。
