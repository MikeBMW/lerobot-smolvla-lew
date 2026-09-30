# 远程 GPU 容器化训练配方 (模型引擎 Model Engine, 2026-08-08 实测)

GPU 服务器: `root@223.109.239.36` 端口 **24424** (2026-08-08 从 24212 改) — sshpass 实测。
完整链路: 模型引擎 UI (本地 4060 或远程 V100 选择) → SSH 提交 → 远程 Docker 容器训练。

## 服务器 bootstrap (全新 Ubuntu 22.04 顺序)

```bash
# 1. sshpass 连接铁律: -p 端口会被 sshpass 吞掉 → 必须 -o Port=
sshpass -p '<pwd>' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o Port=24424 root@223.109.239.36 "cmd"

# 2. pip: 系统 python3 无 pip/ensurepip → apt 装
apt-get update -qq && apt-get install -y -qq python3-pip

# 3. Python 3.12: lerobot pyproject requires-python >= 3.12 (Ubuntu 22.04 默认 3.10)
add-apt-repository -y ppa:deadsnakes/ppa && apt-get update -qq && apt-get install -y -qq python3.12 python3.12-venv

# 4. Docker (2026-08-08 服务器已重启过, 端口 24212→24424)
apt-get install -y -qq docker.io
systemctl enable docker && systemctl restart docker
```

## Docker Hub 国内加速 (必须! 直连 registry-1.docker.io 拉层失败)

```bash
cat > /etc/docker/daemon.json <<'EOF'
{"registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io", "https://dockerproxy.com"]}
EOF
systemctl restart docker
```

## nvidia-container-toolkit 装不上 → 手动 GPU 设备透传 (免 toolkit 铁律)

toolkit 三连败: ① 服务器没 curl (nvidia 官方源脚本全废) ② apt 源路径 404 ③ GitHub release CDN 403/下载失败。
**根本不需要 toolkit** — `docker run --device` 手动透传已验证 torch.cuda 可用:

```bash
docker run --rm \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  zmax-train:latest python -c 'import torch; print(torch.cuda.is_available())'  # → True
```
V100 需要: nvidia0 + nvidiactl + nvidia-uvm (torch 初始化要 UVMM) + libcuda.so.1。

## Dockerfile (仓库根, .dockerignore 排除 data/outputs/reports)

```dockerfile
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime   # V100 sm_70 OK; 注意镜像 Python 3.10!
WORKDIR /app
COPY . /app
# pyproject requires-python >=3.12 vs 镜像 3.10 → --ignore-requires-python
# 必须全依赖安装 (--no-deps 会漏 termcolor/tensorboard → 训练秒崩 ModuleNotFoundError)
RUN pip install --no-cache-dir --ignore-requires-python -e . 2>/dev/null; \
    pip install --no-cache-dir --ignore-requires-python termcolor tensorboard 2>/dev/null; true
CMD ["python", "-m", "lerobot.scripts.lerobot_train", "--help"]
```

## 构建/提交命令 (studio.py _start_remote_training + simulink on_train 同款)

> 🐛 2026-08-08 实测: **参数是 `--config_path` 下划线** (fork 的 parser.py 自定义), 用 `--config-path` 短横线报 `unrecognized arguments`! 下面命令已修正。

```bash
# 镜像未构建 → 自动 build; 已构建 → docker run (镜像名 zmax-train:latest)
cd ~/lerobot-smolvla-lew && git pull -q 2>/dev/null; \
sed -i 's|^  root: .*|  root: data/metaworld_peg|' <cfg>.yaml 2>/dev/null; \
if ! docker images -q zmax-train:latest >/dev/null 2>&1; then \
  nohup docker build -t zmax-train:latest . > /tmp/docker_build.log 2>&1 & echo BUILDING; \
else \
  docker run -d --rm --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
    -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
    -v ~/lerobot-smolvla-lew:/app -w /app --name zmax_train \
    zmax-train:latest python -m lerobot.scripts.lerobot_train --config_path <cfg> \
    > /tmp/remote_train.log 2>&1; echo RUNNING; fi
```

关键点:
- **训练命令必须 `python -m lerobot.scripts.lerobot_train`** — lerobot 是 pip 包 (site-packages), 仓库里没有 lerobot/ 目录; `lerobot/scripts/lerobot_train.py` 路径必错。
- **服务器只有 python3 没有 python** — 用 `/root/lerobot-venv/bin/python3` (venv 方案) 或容器内 python。
- config 的 root 是相对路径 (data/metaworld_peg) — 远程 sed 改 root 指向已上传数据。

## 🚨 PEP695 泛型 (容器 3.10 跑不了 lerobot — 2026-08-08 容器秒退全记录)

lerobot 用 Python 3.12 泛型语法, 镜像 Python 3.10 解析崩 SyntaxError, 逐个暴露:
1. `src/lerobot/utils/io_utils.py:93` — `def deserialize_json_into_object[T: JsonLike](...)` → 去泛型
2. `src/lerobot/processor/pipeline.py:254` — `class DataProcessorPipeline[TInput, TOutput](HubMixin)` → 去泛型 + **所有 `DataProcessorPipeline[...]` 调用处去下标**
3. `src/lerobot/datasets/streaming_dataset.py:58` — `class Backtrackable[T]` → 去泛型 + **补 `T = TypeVar("T")`** (类内 `Iterable[T]`/`deque[T]`/`-> T` 全引用)

泛型调用去下标正则: `\[[^\]]*\]` 不跨行; `\[[\s\S]*?\]` 非贪婪会吃嵌套 `]` 留残留 (`tuple[RobotAction, RobotObservation], RobotAction]`) — 修完必须全仓库 ast.parse 校验 (改坏的恢复 `git checkout` 重来)。

**结论: 别在容器 3.10 死磕** — 泛型散落多处, 修完这个冒出下一个 (factory.py RobotProcessorPipeline[...] → context.py ...)。**终极方案 = venv Python 3.12 快路径** (deadsnakes 3.12 原生支持 PEP695, 零改码):

```bash
# venv 3.12 快路径 (服务器已配 deadsnakes + python3.12)
/root/lerobot-venv/bin/python3 --version          # 3.12.13
/root/lerobot-venv/bin/pip install --no-deps -e .  # 必须 --no-deps! 带依赖会解析拉 torch 2.11 覆盖
/root/lerobot-venv/bin/pip install torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cu118  # 3.12+V100 确定支持
# --no-deps 漏的包逐个补 (报错迭代): datasets av accelerate termcolor tensorboard
/root/lerobot-venv/bin/python3 -u -m lerobot.scripts.lerobot_train --config_path config_act_peg_novae.yaml  # -u 无缓冲实时日志
```

## 训练输出实时 (GUI 日志卡住的根因 — 2026-08-08)

1. **python 非 tty 块缓冲** — 输出攒 4K 才 flush → 命令加 `-u`
2. **tqdm 用 `\r` 刷新不换行** — `for line in p.stdout` 永远等不到 `\n` → 进度条卡住不显示
   → 修: `_run_cmd` 块读 `p.stdout.read(4096)` 按 `\r`/`\n` 分行, 每行 emit (老倪铁律: 终端信息不简化, 截 600)

```python
# _run_cmd 核心 (simulink_module.py):
buf = b""
while True:
    chunk = p.stdout.read(4096)
    if not chunk: break
    buf += chunk
    while b"\n" in buf or b"\r" in buf:
        line, buf = (buf.split(b"\n", 1) if b"\n" in buf else buf.split(b"\r", 1))
        txt = line.decode("utf-8", "replace").rstrip("\r").strip()
        if txt: self.log_signal.emit(txt[:600])
```

## 训练队列轮询防误判 (2026-08-08)

pgrep 检查训练进程时, on_train 数据准备有延迟 (进程未起) → 15s 轮询秒判"完成"秒推进 (14 秒 [1/7]→[2/7] 假象)。修: **启动后 45s 窗口内不判完成 + 进程在时重置窗口** (`_zoo_start_ts` 时间戳)。

## 远程自主串行训练脚本模式 (zoo_train_v2.sh)

```bash
run_one() {  # $1=name $2=config $3=data_root
  [ -f "$CFG" ] || { echo "[$POL] 配置缺失 — 跳过" >> /tmp/zoo_train.log; return 1; }
  sed -i "s|^  root: .*|  root: $DATA|" "$CFG"   # 数据 root 统一 (远程只传 1-2 个数据集)
  $PY -u -m lerobot.scripts.lerobot_train --config_path "$CFG" >> /tmp/zoo_train.log 2>&1
}
# 特殊模型: awe_zflow 用独立脚本 tools/train_awe_zflow.py; vla_touch 无 config 跳过; expert_policy 基准不训
```
监控 cron 查状态**必须进程优先** (先 pgrep, 有→训练中) — 直接 grep ALL_DONE 会匹配旧 log 误判完成。

## 防假阳性验证 (提交后必须查容器存活)

```
docker ps --filter name=zmax_train --format {{.Names}}   # 容器在
tail /tmp/remote_train.log                               # 无 Error/Traceback
```
坑: `grep [l]erobot_train` 会匹配提交命令的 ssh shell 自身 → 假"存活"; nohup 秒崩但 ssh 返回 pid → 假"已启动"。
docker run -d 的 `> log` 重定向只捕获容器 ID, 训练日志要用 `docker logs zmax_train`。

## 其他坑

- **docker restart 会杀掉正在跑的 docker build** — build 期间别碰 docker daemon; 构建用本地后台 ssh (notify_on_complete) 保持连接。
- build 中断现象: `docker images` 列表空 + log 停在 "Pull complete" + buildkit 进程 0 = 死了, 重启 build (层缓存续传)。
- `docker images -q <tag>` 有值但 `docker run` 找不到 = build 未完成 tag 或 daemon 状态混乱, 用 `docker images --format` 确认真实列表。
- 容器秒退排查: 前台 `timeout 60 docker run --rm ... 2>&1 | tail` 直接看 Traceback (--rm 会删容器丢日志)。
- **服务器重启会改 SSH 端口/密码** (24212→24424, neeh3Yah→da9eo7yo) — Connection refused 持续时问老倪要新凭据, 更新 ~/.zmax_ssh.json + GUI 默认端口 + 记忆。
