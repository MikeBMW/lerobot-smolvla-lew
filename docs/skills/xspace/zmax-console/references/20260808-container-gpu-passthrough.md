# 20260808 容器化模型引擎 — 远程 GPU Docker 训练全坑

> 场景: 模型引擎连远程 GPU 服务器(223.109.239.36:24424 root/da9eo7yo), 训练走 Docker 容器 (zmax-train 镜像)。
> ⚠️ SKILL.md 纪律行的 "docker run --gpus all" 已过时 → 本 ref 为准 (toolkit 装不上, 用 --device 手动透传)。

## 服务器环境事实 (2026-08-08)
- 无 curl (只有 wget) → nvidia 官方源/API 全用 wget; apt install curl 没先装是最大弯路
- nvidia-container-toolkit 装不上: apt 源无包 + 官方源 Release 404 + GitHub release 下载受限 → **放弃 toolkit**
- Docker Hub 直连失败 → `/etc/docker/daemon.json` 配 registry-mirrors (docker.1ms.run / docker.m.daocloud.io) + systemctl restart docker
- 服务器重启后 SSH 端口/密码会变 (24212/neeh3Yah → 24424/da9eo7yo) — Connection refused 持续 = 服务器重启中, 等恢复, 问用户要新凭据
- `~/.zmax_ssh.json` 存凭据 (host/port/user/pwd), GUI SSH 面板默认预填该文件

## GPU 容器免 toolkit 透传 (核心方案)
toolkit 装不上时, `--gpus all` 不可用 → 手动设备透传:
```bash
docker run -d --rm \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  -v ~/lerobot-smvla-lew:/app -w /app --name zmax_train \
  zmax-train:latest python -m lerobot.scripts.lerobot_train --config-path <cfg>
```
- 验证: `docker run --rm <devices挂载> zmax-train python -c 'import torch; print(torch.cuda.is_available())'` → True + V100
- 镜像里没有 nvidia-smi (pytorch 官方镜像) — 用 torch.cuda 验证, 不要 exec nvidia-smi

## Dockerfile 关键 (pyproject >=3.12 vs 镜像 Python 3.10)
- pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime 是 **Python 3.10**; lerobot pyproject requires-python ">=3.12" → `pip install -e .` 直接失败
- 修复: `pip install --no-cache-dir --ignore-requires-python -e . --no-deps` (强制装, 实测 lerobot-0.5.2 可跑)
- 依赖: `--ignore-requires-python transformers sentencepiece protobuf huggingface_hub accelerate`
- 装失败被 `2>/dev/null; true` 吞掉 → 容器秒退难查; 诊断: `docker run --rm zmax-train python -c 'import lerobot'`
- .dockerignore 排除 data/ outputs/ reports/ 大文件 (镜像只装代码, 数据运行时 -v 挂载)

## 构建与日志坑
- **systemctl restart docker 会杀掉正在跑的 docker build** (buildkit 进程消失, log 卡住) — CTK 安装与 build 不能并行
- `docker build ... > /tmp/docker_build.log` 后 `&& echo DONE || echo FAIL` — 输出矛盾时以 `docker images --format '{{.Repository}}:{{.Tag}}'` 为准
- `docker run -d ... > /tmp/remote_train.log` 重定向的是 **docker run 命令输出 (容器 ID)**, 训练日志在 `docker logs zmax_train` — 提交命令的日志路径是假日志!
- 容器秒退 (--rm 删除) → 诊断要重跑不带 --rm 或用 docker ps -a + docker logs
- build 中断后重跑: 层缓存 (Already exists) 续传, 但 pull 层网络不稳会反复断 — 本地后台 ssh 保持连接跑 build (notify_on_complete) 最稳

## 远程提交假阳性验证 (三次教训)
1. 服务器只有 `python3` 无 `python` → 提交命令必须 `python3`/`/root/...-venv/bin/python3` 或容器内 `python`
2. lerobot 是 pip 包 (site-packages), 不是仓库目录 → 必须 `python3 -m lerobot.scripts.lerobot_train` 模块方式
3. 存活验证: `ps aux | grep [l]erobot_train` 会匹配到**提交 shell 自身** (ssh 命令行含该串) → 排除 ssh + 检查日志无 Error/Traceback/No such file
   - 容器版: `docker ps --filter name=zmax_train --format {{.Names}}` + 日志无 Error
4. config root 是相对路径但指向本地数据 (metaworld_peg_long 等) → 远程提交前 `sed -i 's|^  root: .*|  root: data/metaworld_peg|' <cfg>`

## 提交命令模板 (GUI 模型引擎 + simulink 双处)
```
sshpass -p 'PWD' ssh -o StrictHostKeyChecking=no -o Port=PORT USER@HOST "
  cd ~/repo && git pull -q 2>/dev/null;
  sed -i 's|^  root: .*|  root: data/metaworld_peg|' <cfg> 2>/dev/null;
  if ! docker images -q zmax-train:latest >/dev/null 2>&1; then
    nohup docker build -t zmax-train:latest . > /tmp/docker_build.log 2>&1 & echo BUILDING;
  else
    docker run -d --rm --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
      -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
      -v ~/repo:/app -w /app --name zmax_train zmax-train:latest \
      python -m lerobot.scripts.lerobot_train --config-path <cfg> > /tmp/remote_train.log 2>&1; echo RUNNING;
  fi"
```
- BUILDING → 日志提示"镜像构建中, 完成后重试"; RUNNING → sleep 3 后验证 (docker ps + log 无 Error)
- 数据上传: `scp -r data/<ds> root@HOST:~/repo/data/` — 目标 data/ 目录必须先 mkdir, 否则 scp -r 报 failed to upload

## GUI 侧 (studio.py)
- SSH 面板默认预填 ~/.zmax_ssh.json; 端口用 `-o Port=` (ssh 的 `-p` 被 sshpass 吞, 连到 22)
- 连接成功 → 自动远程 git pull + 环境状态轮询 (远程 venv/镜像/就绪标签, 30s)
- 参数联动: 模型下拉切换 → steps/batch/lr 读 config (`^\s*lr:` 缩进) + 架构预设 dict (vlm/expert=0 时禁用控件, QSpinBox minimum clamp)

## 模型引擎参数联动坑 (studio.py _on_model_changed)
1. **dict.get(name, {...}[name]) 的默认参数无条件求值** → 默认 dict 缺 key (官方专家/MLP 蒸馏) → KeyError 崩整个方法 (被 except 吞, 参数区不更新) — 修: `A.get(name) or B.get(name, "fallback")` 链式 get, 绝不用 `get(x, d[x])`
2. **QSpinBox 无 decimals()** (QDoubleSpinBox 才有) → `spin.decimals()` AttributeError 被吞 → setValue 不执行 — 修: try float 先 (QDoubleSpinBox), except 再 int (QSpinBox)
3. config 的 lr 在 `optimizer:` 嵌套下 (有缩进) → 正则必须 `^\s*lr:` 否则读不到 (steps/batch_size 顶层无缩进但统一 \s* 兼容)
4. 架构预设 (obs/chunk/vlm/expert/width/freeze/wm) 必须**独立于 if cfg: 块**执行 — 放 cfg 内则 config 文件不存在 (官方专家/MLP) 时整段跳过
5. vlm/expert=0 的模型 (ACT/MLP/专家): 控件 setEnabled(False) + setValue(minimum) (QSpinBox minimum 会 clamp 0→minimum), 且 >0 模型要 setEnabled(True)+setValue(预设)
6. 顶层 `try/except: pass` 吞异常难调试 — 临时把 except 改 `except Exception as e: print(repr(e))` 定位, 修完恢复
