# 2026-08-08 模型引擎容器化远程训练 + simulink 连线索引映射

## 1. 远程 GPU 服务器容器化训练 (Model Engine 远程路径)

### SSH 铁律
- `sshpass -p 'pw' ssh ... -p PORT` — **-p 被 sshpass 吞**（连 port 22 被拒），必须 `-o Port=PORT`
- 服务器可能**重启换端口/密码**（223.109.239.36 24212→24424, neeh3Yah→da9eo7yo）——连不上先重试/问用户，别死磕旧凭据
- 服务器可能缺 curl → 用 wget；缺 `python` 命令 → 用 `python3`
- 更新 `~/.zmax_ssh.json` + studio.py `ssh_port.setText` 默认值 + memory 同步

### GPU 透传 (免 nvidia-container-toolkit)
toolkit 装不上（服务器无 curl→官方源配不了；GitHub release 下载受限）时，**手动设备透传**即可 GPU 训练：
```
docker run -d --rm \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  -v ~/repo:/app -w /app --name zmax_train zmax-train:latest \
  python -m lerobot.scripts.lerobot_train --config-path <cfg>
```
- 容器内验证：`torch.cuda.is_available()` True + V100 名字（镜像无 nvidia-smi，别用它测）
- 不需要 `--gpus all`（那需要 nvidia runtime/toolkit）

### 镜像要求 (关键坑)
- **lerobot fork 用 PEP695 泛型语法**（`def f[T](...)`、`class C[T](...)`），Python 3.10 解析直接 SyntaxError
- pyproject requires-python >=3.12；pytorch/pytorch:2.2.0 镜像只有 3.10 → 两条路：
  - **路 A（推荐长期）**：换 Py3.12 镜像 `pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime`（V100 sm_70 支持；但 2.5.1 实际仍是 3.10.13！2.6/2.7 系列才 3.12，且国内拉取常超时/403）
  - **路 B（快路径，本会话走通）**：**镜像保持 3.10 + 去 PEP695 改源码**——全仓库只 3 处定义（io_utils def、processor/pipeline class、datasets/streaming class）+ 若干调用处。**改完定义必须连调用处一起去下标**（`RobotProcessorPipeline[...]`→`RobotProcessorPipeline`），且用**跨行非贪婪正则** `cls + r'\[[\s\S]*?\]'` 仍会被嵌套 `tuple[...]` 截断（残留 `, RobotAction]`）——最稳是逐处看原版手动 patch
  - **路 C（最快出训练结果）**：**远程 venv 3.12** `/root/lerobot-venv`（Python 3.12.13 + torch 2.2.2+cu118 已装）——3.12 原生满足 requires-python，`pip install -e .` 无需改码；容器 3.12 镜像那条线挂起不阻塞训练
- Dockerfile `pip install --ignore-requires-python -e .` 全依赖（`--no-deps` 会漏 termcolor/tensorboard 等，训练启动秒崩 ModuleNotFoundError）

### 容器训练崩溃迭代排错 (crash-loop 三连)
- 容器秒退（`docker run -d` 返回容器 ID 但 `docker ps` 无）时，**前台跑 + timeout 看 tail**：`timeout 50 docker run --rm ... python -m lerobot.scripts.lerobot_train --config-path <cfg> 2>&1 | tail -6`
- 典型顺序：`--no-deps` 漏包 → PEP695 def 语法 → PEP695 class 语法 → 泛型调用处 `TypeError: 'type' object is not subscriptable`——每修一层跑一次，别一次赌全

### 构建/网络坑
- 国内服务器 Docker Hub 直连失败 → `/etc/docker/daemon.json` registry-mirrors：
  `["https://docker.1ms.run","https://docker.m.daocloud.io","https://dockerproxy.com"]` + `systemctl restart docker`
- **`systemctl restart docker` 会杀死正在跑的 docker build**（buildkit 进程消失、log 停住）——装 toolkit/改 daemon 时别同时 build；build 用本地后台 ssh 保持（notify_on_complete）
- `docker images -q zmax-train:latest` 有值但 `docker run` "Unable to find image locally" = 构建中间态/tag 未落——用 `docker images --format '{{.Repository}}:{{.Tag}}'` 全量确认

### 提交后验证 (防假阳性)
- **旧坑**：`nohup python lerobot_train & echo $!` 返回 pid 但秒崩（python 不存在/lerobot 没装）——ps grep 还会匹配到提交 shell 自身 → 假"已启动"
- **docker 版**：`docker run -d` 把容器 ID 重定向进日志（训练输出在 `docker logs zmax_train`，不在重定向文件）——验证 = `docker ps --filter name=zmax_train` + `docker logs | tail`
- 提交命令带 `sed -i 's|^  root: .*|  root: data/metaworld_peg|' <cfg>`（远程数据目录与本地 config root 不一致）

## 2. simulink 模板连线索引映射 (关键 bug)

**症状**：加载「🔬 模型对比」后 SmolVLM2-500M / SmolVLM2·LEW / SigLIP 入0出0（"模块什么都没接，模型没法运行"）。

**根因**：`load_reference_app` 里布局分支**跳过共享定义**（结构条件共享节点 `continue`）→ `ids` 列表（创建顺序）与 edges 数值（**定义索引**，含被跳过的）错位——`ids[fi]` 全偏 1。

**修复**：加 `index_to_id = {}`，创建每个节点时记录 `index_to_id[i] = n["id"]`（i=enumerate 定义索引）；edges 转换用 `fid, tid = index_to_id.get(fi), index_to_id.get(ti)`。两个分支（layout/else）都要记。
- 同理：**结构条件 5 个行级定义放模板末尾**，其定义索引按实际 `enumerate` 数（共享占 index 2 → 行级是 59-63 不是 58-62！）——写 edges 前先跑脚本打印真实索引（`[i for i,item in enumerate(specs) if '结构条件' in str(item[1])]`），别手数。

## 3. 验证方法
- 模板连线验证（offscreen）：加载模板 → 对目标节点 `n_in = sum(1 for l in m.links if l['t']==nid)` / `n_out`——主干应入1出1，行级🧩应入2出1（State→🧩 + 主干→🧩 → 后续）
- offscreen 下 `isVisible()` False 才是"隐藏生效"；`isHidden()`/`isVisibleTo()` 语义不可靠（parent 未 show）
- QSpinBox 无 `decimals()`（QDoubleSpinBox 才有）——设值 try float 再 int 回退

## 4. 数据/结论
- novae 数据 = `data/metaworld_peg_grab6`（68 条纯接近，1.6M）
- 无 VAE 结论：peg-insert 单模态唯一路线（填空题）→ use_vae:false 决定性；原版 ACT 多模态大数据才需要 VAE（选择题开关）。控制台：ACT/MLP 标 🚫无VAE，simulink ACT 行「🚫 VAE 编码器（无）」，config use_vae:false
