---
name: docker-gpu-training
title: "Docker GPU Training"
description: "Use when Docker-GPU training on a remote server."
trigger: "Use when the user wants containerized training (模型引擎容器化/Docker GPU 训练/远程 GPU 服务器跑训练), or when `docker run --gpus all` fails on a remote server."
---

# Docker GPU Training — 远程 GPU 服务器容器化训练

## ✅ nvidia-container-toolkit 可装路径（2026-08-09 新服务器 4090 实测——先试装，别默认透传）

之前结论"国内装 toolkit 极难"被推翻一半：**有 wget + apt 源可达就能装**。唯一硬坑是
`gpg --dearmor` 管道直接导入报 `gpg: cannot open '/dev/tty'`——**必须 `--batch --yes` + 进程替换**：

```bash
# ① key: 无 curl 用 wget; gpg 必须 --batch --yes + < <(wget -qO-) (否则 /dev/tty 报错 key 没导入 → apt 报 NO_PUBKEY)
gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg < <(wget -qO- https://nvidia.github.io/libnvidia-container/gpgkey)
wget -qO /etc/apt/sources.list.d/nvidia-container-toolkit.list https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list
sed -i "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#" /etc/apt/sources.list.d/nvidia-container-toolkit.list
# ② 装 + 配置 runtime + 重启 docker
apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
# ③ 验证: docker info 出现 "nvidia" runtime, 然后 docker run --gpus all 能 nvidia-smi
```
验证 `docker info | grep -iA3 Runtimes` 应含 `nvidia runc`。装完 `docker run --rm --gpus all <img> nvidia-smi` 冒烟。
**顺序：先探测（curl/wget + apt update 能否拉到包）→ 能装就装；只有装不上（源 404/无网）才降级 --device 透传。**

## 🐛 cuDNN CUDNN_STATUS_NOT_INITIALIZED — 远程容器训练启动即崩（2026-08-09 4090 实测，最重要的远程坑）

**症状**：远程提交训练 → 容器 Up 几十秒 → 退出；`docker logs` 尾部 `RuntimeError: cuDNN error: CUDNN_STATUS_NOT_INITIALIZED`，
崩在 ACT 首次 `conv2d`（`modeling_act.py forward → backbone → F.conv2d`）。**关键诊断特征**：
`torch.cuda.is_available()=True`、`torch.backends.cudnn.is_available()=True`、`ctypes 加载 libcudnn.so.9` 正常——
但**任何实际卷积（conv2d）必崩**。cuda init OK ≠ cuDNN 能用，别被前两步骗了。

**根因**：镜像 torch 2.4.1+cu124 捆绑 cuDNN 9.19，配驱动 550.127 在该容器组合下 conv 初始化失败
（libcudnn 依赖齐全、ldd 无 not found——是运行时初始化问题不是缺库）。

**修复（实测有效，训练稳定 1.2 step/s）**：禁用 cuDNN fallback 到普通 CUDA 卷积——
`torch.backends.cudnn.enabled = False` 放**训练入口脚本**（不能靠环境变量 `TORCH_CUDNN_ENABLED=0`，torch 不读）：
```python
# remote_train_entry.py（仓库根，远程 git pull 即同步；容器挂 /app 直接 python 执行）
import torch
torch.backends.cudnn.enabled = False
import sys
sys.argv = ['lerobot_train'] + sys.argv[1:]
from lerobot.scripts.lerobot_train import main
main()
```
提交命令从 `python -m lerobot.scripts.lerobot_train --config_path x.yaml`
改为 `python remote_train_entry.py --config_path x.yaml`（两处提交路径都要改：studio.py `_start_remote_training` + simulink_model on_train 远程分支）。

**验证命令**（容器内跑通 = 修复有效；跑不通 = 还崩）：
```bash
docker run --rm --runtime nvidia --gpus all --entrypoint python zmax-train:latest -c \
"import torch, torch.nn as nn; torch.backends.cudnn.enabled=False; \
x=torch.randn(1,3,224,224,device='cuda'); m=nn.Conv2d(3,16,3,padding=1).cuda(); \
y=m(x); torch.cuda.synchronize(); print('CONV_OK', tuple(y.shape))"
# 期望 CONV_OK (1,16,224,224)；不带 cudnn.enabled=False 时同一命令 CUDNN_STATUS_NOT_INITIALIZED
```

## ⚠️ 装了 toolkit 但 `--gpus all` 报 "Found no NVIDIA driver" — 要显式 `--runtime nvidia`（2026-08-09 实测）

daemon.json 已配 `runtimes.nvidia`（nvidia-container-runtime）+ `nvidia-ctk info` 正常识别 4090，
但裸 `docker run --gpus all` 仍报 `RuntimeError: Found no NVIDIA driver on your system`（torch 层）。
**该 docker 版本必须 `--runtime nvidia --gpus all` 双写**才生效：
```bash
docker run --rm --runtime nvidia --gpus all <img> nvidia-smi   # ✅ 出 GPU 表
docker run --rm --gpus all <img> nvidia-smi                   # ❌ 可能报 no driver
```
排查顺序：`docker info | grep -iA2 Runtimes`（应含 nvidia）→ `nvidia-container-cli info`（应识别 GPU）→
若都 OK 但 --gpus all 失败 → 加 `--runtime nvidia`。注意与 **--device 三设备透传 + libcuda.so.1 挂载**（老降级方案）
不冲突但**不要混用**；远程 Linux 有 toolkit 时优先 `--runtime nvidia --gpus all`（--device 透传在 cuDNN 组合下可能崩 conv）。

## 📡 远程训练日志实时拉流（2026-08-09 老倪"远程信息得详细显示"）

- **`docker run -d ... > /tmp/remote_train.log` 收的是容器 ID 不是训练日志**——`-d` 后台模式下
  重定向捕获的是 docker run 自身 stdout（容器 ID 一行）。训练日志在 **`docker logs <container>`**。
  拉流命令：`docker ps -q --filter name=<c> | head -1; echo ---; docker logs <c> 2>&1 | tail -n +N`
  （`---` 前 = 存活标记，后 = 增量日志；N = 已读行数，每 5s 拉一次；容器退出后再拉一次最终日志）。
- 提交命令里 `docker rm -f zmax_train 2>/dev/null; docker run -d ...` 会**删掉上一个容器**——
  崩溃容器日志随之消失，无法诊断。诊断崩溃：前台跑一次（不带 -d）拿完整 traceback，或
  `docker events --since 15m` 看 exitCode（exitCode=1 启动即崩 vs 137 被 kill）。
- 远程输出目录固定已存在 → `FileExistsError: Output directory ... already exists and resume is False` 秒退
  （rc≠0 但日志区像"没反应"）。提交前 sed output_dir 成时间戳目录：
  `sed -i "s|^output_dir: .*|output_dir: outputs/train/<cfg>_$(date +%Y%m%d_%H%M%S)|" <cfg>`。

## GPU 透传（免 nvidia-container-toolkit — 装不上的降级方案）

国内/受限环境装 nvidia-container-toolkit 失败时（curl 缺失、官方源 Release 404、GitHub CDN 受限）：
**替代：手动设备透传**——torch.cuda 完全可用：

```bash
docker run -d --rm \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  -v ~/repo:/app -w /app --name train \
  train-image python -m pkg.scripts.train --config-path cfg.yaml
```

验证（镜像无 nvidia-smi——pytorch 官方镜像不带）：
```bash
docker run --rm --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  train-image python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## 🐛 WSL2 本地容器 GPU 访问 ≠ 远程（2026-08-08 实测）

**WSL2 里没有 `/dev/nvidia*` 设备节点**（只有 `/dev/dxg`），`--device /dev/nvidia0` 直接报
`docker: Error response from daemon: error gathering device information while adding custom device
"/dev/nvidia0": no such file or directory`（GUI 日志区看到这个 = 本地容器命令误用了远程的 --device 写法）。

- **诊断**：`ls /dev/nvidia*` 无输出 + `ls /dev/dxg` 存在 = WSL2 → 容器用 **`--gpus all`**（NVIDIA Container Toolkit，飞书端已装）→ torch.cuda 直接可用，**不需要** libcuda.so.1 挂载
- **远程 Linux 服务器**（有 /dev/nvidia0）→ 用 `--device` 三设备 + libcuda.so.1 挂载（见上节）
- **本地训练切容器（GUI on_train 本地分支模板，2026-08-08 老倪"切成本地容器运行"）**：
```python
cmd = ["sudo", "docker", "run", "--rm",
       "--gpus", "all",
       "-v", f"{root}:/app", "-w", "/app",
       "-e", "PYTHONPATH=/app/src",   # 🐛 lerobot 源码在 /app/src（镜像 COPY 布局），不加则 import lerobot 失败
       "--entrypoint", "python", "zmax-std:1.0",
       "-u", "-m", "lerobot.scripts.lerobot_train",
       "--config_path", os.path.join("/app", os.path.basename(tmp_cfg))]
```
  - 本地 docker 是 `sudo docker`（用户未重登加组前）——GUI 里直接拼 `sudo docker`（WSL 免密 sudo）
  - 数据 root 陷阱：`config_act_metaworld.yaml` 默认 `root: data/metaworld_act`——本地只有
    `data/metaworld_peg` → 容器训练报 `FileNotFoundError: no parquet file: data/metaworld_act/data`
    → 训练前 sed root 到实际存在的数据目录（on_train 的 sed 分支已处理，手动直跑 config 要自己改）
  - **容器内验证 cuda**：`sudo docker run --rm --gpus all zmax-std:1.0 python -c "import torch; print(torch.cuda.is_available())"` 挂 --gpus all 才返回 True；不带 GPU 参数返回 False 是正常的，别误判镜像坏
  - 入口脚本拦截：镜像带 `zmax-train` 入口（不传 config 打印用法）——验证内部环境用
    `--entrypoint python` 覆盖入口

## Dockerfile 坑

- **Python 版本不匹配**：pytorch 官方镜像（2.2 系列）= Python 3.10，若 pyproject `requires-python >=3.12` → `pip install --ignore-requires-python -e .`（否则拒绝安装）
- **必须全依赖安装**：`--no-deps` 会漏 termcolor/tensorboard 等 → 训练启动 ModuleNotFoundError 秒退。用 `pip install --ignore-requires-python -e .`（带依赖）
- 失败命令加 `2>/dev/null; ...; true` 会吞错误——先跑一次不吞的看真实报错
- **`pip install -e .` 会把 torch 覆盖成最新（cu130）→ 必须最后强制降级**（2026-08-08 V100 实测，v1→v2→v3 三版 Dockerfile）：基础镜像 torch 版本正确，但 `-e .` 装项目依赖时 pyproject 的 torch 约束不锁版本 → 装成 2.11.0+cu130，驱动 550 只支持 CUDA 12.4 → `torch.cuda.is_available()=False`（报 "driver too old (found 12040)"）。**修复：RUN 最后一步强制固定**：
```dockerfile
RUN pip install --no-cache-dir --ignore-requires-python -e . 2>/dev/null; \
    pip install --no-cache-dir --ignore-requires-python termcolor tensorboard 2>/dev/null; \
    # 最后强制降级 (防 -e . 覆盖成 cu130; 匹配驱动 550/CUDA12.4, V100 sm_70)
    pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu124 2>/dev/null; \
    # 训练必需 extras: datasets(数据加载) av(视频解码) accelerate(训练加速)
    pip install --no-cache-dir --ignore-requires-python datasets av accelerate 2>/dev/null; \
    # 🐛 torchcodec 与 torch 2.4.1 不兼容 (libtorchcodec_core4.so 加载失败) → 卸载; 本地数据集用 av 解码不需要 torchcodec
    pip uninstall -y torchcodec 2>/dev/null; true
```
- **补依赖是迭代的**：`import_utils.require_package` 逐个报（`'datasets' is required` → `'av' is required` → `'accelerate' is required`）——`pip install lerobot[dataset,training]` 一次装全，别一个错补一个；容器已起时 `docker exec <c> pip install xxx` + `docker commit` 比重建快
- **验证顺序**（容器内必须依次确认）：① `python -c "import torch; print(torch.cuda.is_available())"` = True ② `import datasets, av, accelerate` 无错 ③ 再提交训练——每次失败都是新缺依赖，先验 CUDA 再跑训练
- **git 同步数据会丢视频**（2026-08-08 远程训练图像为空根因）：`.gitignore/.dockerignore` 排除大文件 → 远程 `git pull` 后数据目录只有 parquet + `file-000.mp4.metadata`（29KB），**没有实际 mp4** → 模型纯 state 训练（图像全空）。**修：关键数据集必须 scp/rsync 完整目录到远程**（`scp -P 24424 -r data/xxx root@host:/root/lerobot-smolvla-lew/data/`），并验证 `ls .../chunk-000/file-000.mp4` 实际大小 >100KB

## 🐛 PEP695 泛型（Py3.12 代码 vs Py3.10 镜像）——装上 ≠ 能跑

`--ignore-requires-python` 能装上，但代码用 **PEP695 泛型**（3.12 专属）→ 3.10 运行时 **SyntaxError 秒退**（迭代排错常见 3-5 轮，每轮崩在不同文件）：

```python
def f[T: JsonLike](...)    # 函数泛型
class C[TInput, TOutput]   # 类泛型
type NameOrID = str | int  # type 别名
RobotProcessorPipeline[tuple[RobotAction, ...], RobotAction]  # 泛型调用(嵌套/跨行, 可能上百处)
```

修复（去泛型 = 3.10 兼容，3.12 也能跑）：
- `def f[T](...)` → `def f(...)`；`class C[T](Base)` → `class C(Base)`
- `type X = Y` → `X = Y`（普通赋值）
- **调用处 `Pipe[T1, T2](...)` → `Pipe(...)`**：数量可能上百（114 处实测）——用**栈匹配**去下标（处理嵌套 `tuple[...]` 和跨行 `[`）：
```python
def strip_all(src, cls):
    out, i = [], 0
    while True:
        j = src.find(cls + "[", i)
        if j < 0: out.append(src[i:]); break
        out.append(src[i:j] + cls)
        k = j + len(cls); depth = 0
        while k < len(src):
            if src[k] == "[": depth += 1
            elif src[k] == "]":
                depth -= 1
                if depth == 0: break
            k += 1
        i = k + 1
    return "".join(out)
```
- 改完**全仓库 ast.parse 扫残留**（`def/class \w+\[[A-Z]` + `type \w+ =` + 各类 `Pipe[`）
- **去 class 泛型后内部 `T` 引用残留 → NameError `name 'T' is not defined`**：`class C[T]:` 去掉后方法签名 `Iterable[T]`/`-> T`/`deque[T]` 还在用 T → 文件级补 `T = TypeVar("T")`（from typing import TypeVar）——3.10 兼容且不报错
- **去下标用正则（`[^\]]*` 或非贪婪 `[\s\S]*?`）会在嵌套括号处残留**（如 `RobotProcessorPipeline[tuple[A, B], C]` 只剥到内层 `]` → 残留 `, C]` 语法错）——用**栈匹配**（上面 strip_all）；改坏了直接 `git checkout <file>` 恢复重来
- 教训：**先 grep 全仓库 PEP695 数量**再决定修代码 vs 换 3.12 镜像——量少（几处）改代码快；量多（上百）直接换 Python 3.12 镜像（pytorch/pytorch:2.5.1 仍是 3.10！要 2.6+ 且确认 tag 存在，镜像加速器 403 常见）

## venv 3.12 快路径（容器折腾久时优先）

服务器 `apt install python3.12 python3.12-venv`（deadsnakes）+ venv + `pip install -e .`——3.12 原生支持 PEP695，**无需改代码**，比容器快得多。踩坑：
- **`pip install -e .` 会重装 torch 到最新**（如 2.11.0+cu130——与服务器驱动 12.4 不匹配 → `torch.cuda.is_available()=False`）→ 用 `--no-deps -e .` 再补核心依赖（termcolor/tensorboard/transformers/huggingface_hub/accelerate），torch 手动装匹配驱动的版本：`pip install torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cu118`（cp312 wheel ✓ V100 sm_70 ✓ 驱动 12.4 ✓）
- 训练提交同容器链：git pull + sed 数据 root + `python3 -m lerobot.scripts.lerobot_train`（pip 模块方式）+ 提交后 3s 存活验证
- **补依赖是迭代的**：`import_utils.require_package` 逐个报（`'datasets' is required` → `'av' is required` …）——`pip install lerobot[dataset]` 一次装全（或循环补 datasets/av/…），别一个错补一个
- **新版 lerobot_train CLI 参数变化**：`lerobot_train.py: error: unrecognized arguments: --config-path xxx.yaml`——**注意参数名是 `--config_path`（下划线）不是 `--config-path`**（Hydra 短横线会 unrecognized）——本地 GUI training_backend 构造的命令就是 `--config_path`（对照 `tools/gui/training_backend.py` 的 start 方法 + `grep -rn --config_path tools/`）；提交前先确认 fork 的入口参数（`python -m lerobot.scripts.lerobot_train --help`）并**对照本地 GUI 实际调用方式**
- **串行训练脚本秒退假象**：后台脚本循环跑 7 模型，log 全 `rc=0` 但 25 秒跑完 5 个模型、`grep -c 'Training:' log` = 0——**rc=0 ≠ 训练成功**（缺依赖 ImportError 时脚本可能仍记 rc=0）——验证训练真实性必须 `grep -cE 'Training:|loss' /tmp/train.log`（有进度行才算真训练），并 `pgrep -f lerobot_train` 确认进程存活

## 🐛 transformers 版本矩阵（远程 venv 训 smolvla_lew 等 5.x 模型时逐个踩）

lerobot fork 的 smolvla_lew/molmoact2/wall_x/groot 等策略 import transformers 深层 API，**5.x 各小版本互不兼容**（2026-08-08 实测，4 轮降级/升级）：

| 版本 | 症状 |
|---|---|
| 5.14.1 | `NameError: name 'torch' is not defined`（integrations/tensor_parallel.py 需要新 torch API）|
| 4.49.0 / 4.51.3 | `cannot import name 'Qwen2_5_VLTextConfig'`（qwen2_5_vl 无 TextConfig）|
| 5.5.4 | `from transformers.generation import GenerationMixin` ImportError（远程文件差异）；还有 `integrations/accelerate.py` 的 `NameError: name 'nn' is not defined` |
| **4.44.2 + torch 2.4.1+cu124** | **实测最稳组合**（飞书端 v6 镜像——4 轮降级折腾后的最终方案，多模型重跑不崩）|

**⚠️ 4.44.2 不是万能（SmolVLA 曾被认为需更高版本——2026-08-08 实测推翻）**：早期结论认为
`transformers.models.qwen2_5_vl`（4.49+ 才有）是 SmolVLA 必需；**最终验证发现 modeling_smolvla_lew.py
已移除 Qwen 导入（\"移除原V-JEPA、Qwen无用导入\"），SmolVLA 根本不需要 qwen2_5_vl**——之前 30 秒秒退
的根因是 transformers 5.5.4 与 torch 版本错配（DTensor/torch_compilable_check），不是缺 qwen。
**真正的最终稳定组合 = 本地 .venv 验证过的：transformers 5.5.4 + torch 2.11.0+cu128**
（本地 smolvla_peg_long2 训练通过 + DTensor OK + torch_compilable OK——以 `pip show transformers` +
`python -c "from torch.distributed.tensor import DTensor"` 双重确认）。4.49-4.51 缺 torch_compilable_check
（`cannot import name 'torch_compilable_check' from 'transformers.utils'`，eo1 策略顶层引用），5.x 又
需 torch 2.5+（DTensor）。**规则：以本地能跑通训练的版本为准，别在远程从零试版本矩阵。**

**规则**：
- **以本地 `.venv` 能跑通训练的版本为准**（本地 5.5.4 全 import OK——`pip show transformers` 看本地版本，远程装同版本 `--force-reinstall`）
- **⚠️ huggingface-hub 必须 >=1.5.0（2026-08-09 arm64 构建实测）**：requirements.lock 曾写 `huggingface-hub>=0.24,<0.37` → arm64 `docker build` 直接 `ResolutionImpossible: Cannot install huggingface-hub==0.36.0 and transformers==5.5.4 because these package versions have conflicting dependencies`（transformers 5.5.4 要求 `huggingface-hub<2.0,>=1.5.0`）。**修：lock 里 `huggingface-hub>=1.5.0,<2.0`**。排查命令：`pip install --dry-run transformers==5.5.4 2>&1 | grep huggingface-hub` 直接看它要求的版本范围
- **4 轮都崩时直接上 transformers 4.44.2**（最老但最稳，避开 4.49+ 的 TextConfig 缺失与 5.x 的 torch/nn/GenerationMixin 系列坑）；另一会话已验过的镜像 tag（如 v6）优先直接用，别自己从头试
- **`GenerationMixin` import 改标准路径** `from transformers.generation.utils import GenerationMixin`（4.x/5.x 都兼容——`transformers.generation` 顶层在 5.x 部分版本没有）——改 lerobot 源码 3 处（molmoact2/wall_x/groot），提交后远程 git pull
- **eo1 的 `Qwen2_5_VLTextConfig` import 加 try/except 降级**（4.x 无此名 → `Qwen2_5_VLTextConfig = None` + 只 import VLConfig/VLVisionConfig）——否则 4.49/4.51 连 import 链都过不去（lerobot.policies.__init__ 全量导入）
- 远程 force-reinstall 失败（版本没变）时 `pip install 'pkg==ver'` 不带 --force 看真实输出（有时 uninstall 链被 grep 吞了）
- accelerate.py 的 `nn` 未定义可直接 sed site-packages 补 `import torch.nn as nn`（临时，训完可还原）

## 远程后台脚本保活 + 训练输出实时化

- **`nohup bash x.sh &` 经 ssh 断开后会被杀**（进程消失、log 停在半途）→ 用 **`setsid bash x.sh < /dev/null & disown`** 彻底脱离会话
- **python 非 tty 块缓冲**：训练 stdout 攒 4K 才输出 → GUI/日志看不到实时进度 → 命令加 **`-u`**（`python -u -m lerobot.scripts.lerobot_train`）
- **tqdm `\r` 进度条不触发 `for line in p.stdout`**（永远等不到 \n，日志"卡住"）→ 子进程读取改**块读 + 按 \r/\n 分行**：`p.stdout.read(4096)` 累积 buf，`while b"\n" in buf or b"\r" in buf: split` 后逐行 emit（进度条每帧都实时）
- **训练队列秒推进误判**：轮询 `pgrep -f lerobot_train` 判"完成"，但 on_train 数据准备有延迟（进程未起）→ 14 秒误推进到下一个模型 → **启动后 45s 窗口内不判完成**；pgrep 有进程时**重置窗口**（等真正结束才推进）
- **监控脚本进程优先**：`grep ALL_DONE` 会匹配 log 里的旧记录（重跑多次后误报"完成"）→ 先 `pgrep` 有进程 = 训练中，无进程再看尾部 ALL_DONE

## 标准容器框架（一处构建 → 训练/推理/多端部署，2026-08-08 老倪设计）

一个标准容器环境四处运行：远程 GPU 训练 / 本地推理 / Mac(arm64) 数据 / Orin(arm64) 真机推理。
设计要点与完整模板见 `references/standard-container-framework.md`（仓库 `docker/` 目录即活模板）：
- **多阶段 Dockerfile**（`AS base` 系统依赖 → `AS train` GPU 训练 → `AS infer` 轻量推理）
- **多平台**：`ARG TARGETPLATFORM` + `if [ "$TARGETPLATFORM" = "linux/arm64" ]` 分支装 CPU/GPU torch；buildx `--platform linux/amd64,linux/arm64`
- **requirements.lock 锁定依赖**（唯一真相——**最终统一基线 transformers 5.5.4 + torch 2.11.0+cu128**，2026-08-08 本地全模型验证组合，已推 GitHub 81039f8a）。**版本演化史**：v6 镜像 (4.44.2+2.4.1) 只够 ACT/VLA-Touch/AWE；SmolVLA 曾误判需 qwen2_5_vl (4.49+)，最终确认 modeling_smolvla_lew.py 已移除 Qwen 导入——**真正决定因素是 transformers 5.x 要 torch 2.5+ 的 DTensor** → **最终 lock: transformers==5.5.4 torch==2.11.0 torchvision==0.26.0**（本地 smolvla 长轨迹训练验证过），Dockerfile 先 `pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url .../cu128` 再 `pip install -r requirements.lock`（torch 显式 cu128，PyPI 默认无 CUDA wheel；V100 驱动 550/CUDA12.4 兼容 cu128）
- **⚠️ torchvision 必须锁版本（2026-08-08 实测）**：Dockerfile 里 `pip install torch==2.4.1 torchvision`（torchvision 不带版本）→ pip 解析 torchvision 最新版（需要 torch 2.11）→ **把已装好的 torch 2.4.1 覆盖成 torch 2.11.0**（log 显示 `Downloading ... torch-2.11.0 ... from torch==2.11.0`）→ 构建白拉 2GB + 版本错乱。**铁律：torch/torchvision 必须同源同版本一次装齐**（`torch==X.Y.Z torchvision==A.B.C`），版本号以 requirements.lock 为准，Dockerfile 与 lock 双处一致（改一处必须同步另一处，验证脚本可 grep 比对）
- **⚠️ requirements.lock 里绝不写 torch/torchvision 行（2026-08-08 实测 BUILD_RC=1）**：Dockerfile 已预装 torch（cu128 源 / arm64 CPU 分支）——lock 里再写 `torch==2.11.0` 会**重复安装**，pip 解析冲突 → `docker build` 失败（`returned a non-zero code: 1`，卡在第二个 torch 安装 RUN）。**规则：torch/torchvision 只由 Dockerfile 平台分支管，lock 只写其余依赖**（注释标明「torch 由 Dockerfile 预装 — 此处不重复装」）；lock 被外部（飞书端）改回带 torch 行时 patch 后先 grep 确认 `torch==` 不在 lock 里
- **构建加速终极方案：COPY 本地已验证 site-packages（2026-08-08 飞书端策略，cuda True 验证通过）**：pypi.nvidia.com / download.pytorch.org 慢、超时是容器构建最大耗时（torch 2.11 CUDA 全家桶 ~3GB 逐个包下载）——直接 `COPY` 本地 `.venv/lib/python3.x/site-packages` 进镜像（本地已全 7 模型验证过、与训练环境完全一致），绕开全部 pip 下载坑；代价是镜像大（28GB）但一次成型、容器内 cuda True + lerobot OK。验证镜像别忘：**容器验证 cuda 必须挂 `--device /dev/nvidia0...` + libcuda.so.1**——不带设备 `torch.cuda.is_available()` 返回 False 是正常现象，别误判镜像坏了；lerobot 在 `/app/src`（`sys.path.insert(0,'/app/src')` 再 import）
- **统一入口**（容器内 `zmax-train --config_path x.yaml` / `zmax-infer --policy act`），train 入口自动 sed 数据 root
- **无 registry 推送**：buildx `-o type=docker,dest=/tmp/x.tar` + scp + 远程 `docker load`（push.sh 分 remote/mac/orin）
- **GUI 容器集成模式**（2026-08-08）：模型引擎加 🐳 容器区——`_poll_remote_container`（QTimer 15s SSH 查 `docker ps` + `docker logs tail`，**状态变化才 emit 防刷屏**，日志区实时显示容器安装/训练）；上传按钮**检测本地 docker 可用性**——本地无 docker 自动 fallback 远程 `git pull && docker build`（Dockerfile 即"上传"），别让用户看到 `No such file: 'docker'` 报错。**坑（2026-08-08 修复）：检测必须包 try/except**——`_sp.run(["docker",...])` 在 docker CLI 不存在时抛 **FileNotFoundError**，会跳过 fallback 直接进外层 except（用户只见"容器同步开始…"再无下文）→ 检测整体 try，`has_local=False` 时走远程构建分支
- **模式选择 UI 演化（老倪偏好，2026-08-08）**：容器管理模式 UI 三次迭代——①状态机单选按钮（点击到达状态+执行按钮）→ 老倪"逻辑太复杂，简单点"；②裸 QRadioButton 点选 → 老倪"太简单，不好看"；③**三模式卡片**（QPushButton checkable + QButtonGroup exclusive + QSS `:checked{border:3px solid 青色; background:高亮}`，150×64 卡片带标题\n副标题，默认选中远程训练）→ 满意。**规则：模式/状态选择用卡片式（选中外边框包裹高亮），别搞复杂状态机，别用裸 radio**
- **三模式卡片 = GPU 引擎选择（最终版 2026-08-08，老倪两次纠正）**：🚀 远程训练→`_ct_pick` 设 `gpu_mode="remote"`；🎮 本地运行→`gpu_mode="local"`；📱 端侧部署→推送。`_start_training` **只对 deploy 分流**（`_container_action("mac")`），其余统一走 Model Zoo 训练队列——GPU 引擎由卡片联动，simulink on_train（5012 行）按 `gpu_mode` 分流：remote→远程容器 / local→本地 4060 真训练。**两个坑（老倪纠正）**：① 曾把"本地运行"当推理（`on_infer_video`）→ 点训练直接弹 scope → 老倪"应该开始训练，怎么弹 scope"——**scope 是 simulink 的功能，本地运行必须真训练**；② 训练按钮固定走队列不读模式 → "本地推理没反应"。**规则：模式 = 引擎，本地运行 = 本地训练，绝不用推理弹窗冒充**（推理/评测走 simulink 画布的节点，不在训练按钮）
- **布局定稿（2026-08-08 老倪）**：配置通道表格 `layout.addWidget(self.param_scroll, 1)`（stretch 向下伸长占满全高，看不全用 param_scroll 右侧滚动条 `ScrollBarAsNeeded`）；容器管理 `cg` 从 `param_layout.addRow(cg)` 移出 → 主布局 `layout.addWidget(cg)`（param_group 外层、页面底部独立区）——容器管理不放配置表格组内
- **🏗 架构页消失 = modules/stack/names 三处不同步（2026-08-08 老倪\"首页的架构，原来的三层架构功能卡哪去了\"）**：ArchitectureModule（L2/L3/L4 + SYS0/1/2 三层卡）代码一直在但**之前删 Architecture 页时只删了 stack.addWidget 没删全**——导航 `_on_nav` 走 `self.modules.get(target, 0)`，modules 里没有 `\"architecture\"` → 点架构导航落到首页/空页。**恢复需同步三处**：① `self.modules[\"architecture\"] = 12`（stack 末尾新 index）② `self.stack.addWidget(ArchitectureModule())`（dataspace 之后）③ `names` 列表补到 14 项（`\"数据空间\", \"架构总览\"`——否则 `names[idx]` 越界 IndexError 崩状态栏）。**规则：删/加 stack 页必须 modules dict + addWidget + names 三处一起动；三层卡（SystemSidebar 的 sys2/sys1/sys0 + ArchitectureModule 页）是首页架构入口，别单独删页留入口**
- **反复弹 scope/rollout 窗口的诊断（2026-08-08 老倪\"怎么反复启动scope\"）**：多个「🎮 7 模型仿真 rollout 对比」窗口同时出现 ≠ 训练触发——simulink 画布的 video 节点双击才走 `on_node_activated`（5742 行 `params.get(\"video\")` → `on_infer_video`）；批量出现 = 旧 GUI 实例残留/误触发。**处理：`xdotool search \"\"` 全窗口列表按标题过滤 `*rollout 对比*` → `xdotool windowkill` 逐个关 + 确认 `pgrep -f lerobot_train` 无本地训练（排除训练完成自动弹）+ 重启 GUI 清残留状态**。别在没确认触发源前改训练逻辑
- **文案定稿（2026-08-08 老倪）**："本地推理"→"本地运行"（7 处，infer 模式 key 不变）；训练按钮 "▶ Start Training"→"▶ Start"（通用开始——无论在哪个容器/位置，模式决定动作）
- **Stop 按钮重写（2026-08-08 老倪"Stop 不好用/没反应"）**：取消 Pause（按钮+`_pause_training` 全删，**遗留 `pause_btn` 引用一并清**——如训练启动回调里的 `self.pause_btn.setEnabled(True)` 会 AttributeError）；"⏹ Stop Training"→"⏹ Stop"。**根因：旧 `_stop_training` 调 `train_backend.stop_training` 对队列训练无效**（训练走 simulink `_run_cmd` 的 Popen，不走 train_backend）→ 重写为：① 清 `self._zoo_queue=None` + `_zoo_timer.stop()`（防队列继续推进）② `pkill -9 -f lerobot_train` + `pkill -9 -f train_awe_zflow` ③ simulink `on_stop()`（远程容器训练也停）④ Start 恢复/Stop 禁用。删除方法时留意**残留缩进块**（旧代码尾部 `self._log("⏹ Training stopped")` 未删干净 → IndentationError，先 ast.parse 再提交）
- **布局紧凑（2026-08-08 老倪"空着一大段"）**：模型引擎页 `layout.setSpacing(16)→6` + `setContentsMargins(20,20,20,20)→(16,6,16,12)`——标题区与 GPU 服务器状态区整体上移贴紧，不留大片空白
- **模型引擎自动连接**：`__init__` 末尾 `QTimer.singleShot(3000, _auto_connect_gpu)`——检查 `~/.zmax_ssh.json` 存在且 `remote_engine` 未连接 → 自动 `_connect_gpu()`（无需手动点连接按钮）；连接成功后启动容器状态轮询
- **⚠️ 远程不可达不许误导（2026-08-08 老倪"远程我都关机了，你这是误导；按照实际的信息输出"）**：`_on_gpu_mode` 必须加 `self.remote_engine.get("connected")` 才显示"训练引擎 → 远程 GPU"——否则 radio_remote 被选中 + engine 存在但 SSH 没连上时，日志仍假报远程（远程关机后用户看到"训练引擎 → 远程 GPU" = 误导）。`_connect_gpu` 失败分支补 `self._log("⚠️ 远程 GPU 不可达 (已关机/网络不通) — 自动使用本地引擎 (4060)")`。**验证**：mock `remote_engine=None` 与 `remote_engine={"connected": False}` 两种情况调 `_on_gpu_mode` → `gpu_mode` 都必须是 `"local"`。**规则：状态信息必须按实际输出——连不上就明说连不上并自动降级本地，绝不报"已连接/远程引擎"**
- **⚠️ `_auto_connect_gpu` 快速失败探针（2026-08-08 老倪"我啥也没干呢，你肯定连不上，报连不上的信息啊"）**：启动自动连接若直接 `_connect_gpu()`，SSH 全流程在远程关机时慢且日志停在"模型引擎自动连接远程 GPU…"无下文 → 先做 **3 秒可达性探针**：`sshpass ssh -o ConnectTimeout=3 -o BatchMode=yes host 'echo OK'`（`timeout=6`），stdout 无 `OK` → 立即 `self._log("⚠️ 远程 GPU 连不上 (已关机/网络不通) — 使用本地引擎 (4060 容器)")` + `gpu_mode="local"` + `radio_local.setChecked(True)` 并 return（不调 `_connect_gpu`）；探针通过才 `_connect_gpu()`。文案"检测远程 GPU…"而不是"自动连接…"（还没连上）。**验证**：真实调用（远程关机时）断言 `gpu_mode=="local"` + 日志含"连不上/不可达"
- **远程关机不影响本地容器训练（2026-08-08 实测）**：本地 zmax-std:1.0 容器 GPU 直通完全独立——远程服务器关机只损失 V100 加速（本地 4060 慢些），训练/评估/推理全链路本地容器可跑（5 模型容器训练产物全在本机 `outputs/train/`）。GUI 自动连接在远程关机时走上面的"不可达"提示 + `gpu_mode=local`，本地容器轮询（`_poll_remote_container` 本地分支）照常显示容器训练状态
- **训练日志必须桥接到模型引擎日志区（2026-08-08 老倪\"日志呢\"根因）**：simulink 的 `on_train` 日志走 `log_signal`（连 simulink 自己的日志页）——模型引擎（TrainingModule）日志区看不到 → 用户只看到队列推进行、看不到训练细节 → 主窗口连接处补 `self.simulink.log_signal.connect(self.model_engine._log)`（_log 已线程安全，可跨线程 emit）
- **容器状态要详细状态树（老倪\"日志太少，跟没有一样\"）**：`_poll_remote_container` 只输出一行容器状态不够——SSH 一次拉全：`docker ps -a`（含 Exited/Paused）+ `docker images | grep zmax-train`（镜像/大小）+ `docker logs` 提取 `Training: N%|loss X|config_*.yaml|开始训练` + `nvidia-smi`，状态变化时输出树状：`🐳 远程容器: …\n   ├ 镜像: …\n   ├ 训练: …\n   └ GPU: …`（变化才输出防刷屏，但内容必须全）
- **本地容器也要反馈（2026-08-08 老倪"还是没看到进容器"根因）**：`_poll_remote_container` 只查远程 SSH ——本地容器化训练后用户看不到容器 → 函数开头加**本地分支**：`if getattr(self, "gpu_mode", "local") != "remote":` → `subprocess.check_output(["sudo","docker","ps","--format","{{.Names}} {{.Image}} {{.Status}}"])` → 过滤 `zmax-std` + `Up` 的容器 → `_ct_status.setText(f"🐳 本地容器: {name} 训练中")` + 变化时 `_log("🐳 本地容器运行中: … 训练在容器内执行 (docker)")`；无容器则显示"本地容器: 未运行" + 提示点 Start。**验证**：mock `gpu_mode="local"` 直接调 `_poll_remote_container()` + `app.processEvents()` 断言 `_ct_status.text()` 含"本地容器"——容器实际在跑时应显示容器名（如 `recursing_villani 训练中`），无容器时显示"未运行"
- **本地容器也要显示训练进度（2026-08-08 老倪"改成显示到日志区，马上改"）**：本地分支 `docker ps` 找到运行容器后追加 `sudo docker logs --tail 3 <cname>`（timeout 8）逐行提取 `Training: N%` / `loss ... step:` → `self._log(f"   ├ 进度: {prog}")`（每 15s 轮询更新，日志区实时见 Training 百分比）。**"训练半天不开启"诊断（2026-08-08 实测）**：往往不是没训练——先 `ls -t outputs/train/` 看时间戳目录（有 ckpt 说明训过）+ `sudo docker logs <c> | grep Training` 看真实进度 + `nvidia-smi` GPU%，确认训练在跑再怪日志显示；队列顺序与容器不符（[1/7]ACT 但容器在训 smolvla）多半是 ACT 已完成/被开关跳过，查 `outputs/train/act_*` 的 checkpoints 确认
- **训练秒崩且无日志的另一根因 = 输出目录已存在（2026-08-08 实测）**：`FileExistsError: Output directory outputs/train/xxx already exists and resume is False` → 秒退 rc≠0（直接跑 config 时）。`on_train` 已用 `ts_dir = "<policy>_" + time.strftime("%Y%m%d_%H%M%S")` + `re.sub(r"(output_dir:\s*).*", ...)` 规避；手动/脚本直跑 config 时先确认/改名 output_dir，别让日志区"没反应"误导排查方向
- **Qt 跨线程 GUI 操作崩溃铁律（2026-08-08 实测）**：后台线程里直接 `log_text.append`/`setEnabled` 会崩（用户报"容器管理崩溃"）→ `_log` 检测 `threading.current_thread() is main_thread()`，非主线程用 `QTimer.singleShot(0, lambda: ...)` 回主线程执行（拆 `_append_log` 方法）；线程 finally 里恢复按钮同样 `QTimer.singleShot(0, ...)`

## 本地 WSL 装 docker（2026-08-08 实测——后台无 tty 是唯一坑）

老倪要求"本地也要装 docker 让本地运行走容器"。WSL 里装 docker.io 的方法与坑：
- **`sudo apt-get install -y docker.io` 放后台（background=true）会失败**：报 `sudo: A terminal is required to authenticate`——**sudo 要 tty，后台进程没有**。先 `sudo -n true` 确认免密（WSL 默认 NOPASSWD 时前台直接可用），**必须前台跑** apt 安装（timeout 给足 400s）
- 装完（WSL 无 systemd）：`sudo service docker start` 启动 daemon（不是 systemctl）
- 用户加组（可选，当前会话仍需 `sudo docker`）：`sudo usermod -aG docker $USER`（重新登录才生效）
- 验证：`sudo docker run --rm hello-world`（"Hello from Docker!"）+ `sudo docker images`（看已有基础镜像如 nvidia/cuda:12.4.1-base）
- 本地 docker 就位后：本地容器构建 `sudo docker build --target train -t zmax-std:1.0 -f docker/Dockerfile .`（后台 + notify；GUI 上传按钮的本地检测 `_sp.run(["docker",...])` 从此走 save→scp→load 真上传路径）

## .dockerignore 放行 site-packages 的精细写法（2026-08-08 实测——COPY 失败 3 轮的根因）

想把本地已验证的 `.venv/site-packages` COPY 进镜像（免 pip 下载），`.dockerignore` 必须**逐级放行**：
```gitignore
.venv/*
!.venv/lib/
.venv/lib/*
!.venv/lib/python3.12/
.venv/lib/python3.12/*
!.venv/lib/python3.12/site-packages/
```
**坑**：只写 `.venv/lib/python3.12/site-packages/*` + `!.venv/lib/python3.12/site-packages/` **无效**——父级 `.venv/` 已排除整个树，`!` 只重新包含目录本身不含内容 → `COPY` 报 `file not found in build context or excluded by .dockerignore`。**验证**：临时 Dockerfile `COPY .venv/lib/python3.12/site-packages/torch /test` + `docker run --rm <ctx> ls /test` 看是否真可复制，别直接跑全量构建。

## 构建只取 train 阶段 + 全阶段默认构建的坑（2026-08-08 实测）

多阶段 Dockerfile（base→train→infer）**默认 build 构建所有阶段**——infer 阶段若残留旧 torch 版本（如 2.4.1 cu124），每次 build 都白拉 797MB 且与 train 的 2.11.0 冲突。**只构建目标阶段**：`docker build --target train -t zmax-std:1.0 -f docker/Dockerfile .`。改版本时**两个阶段都要改**（grep 全部 `torch==` 行确认无残留旧版本）。

## 模型引擎强制容器训练（2026-08-08 老倪"不要用本地虚拟机环境训练，用容器"）

simulink_module.py `on_train` 三个分支全改容器（**删除本地 .venv 直训旧代码**）：
- ACT/SmolVLA/LEW：`sudo docker run --rm --gpus all -v {root}:/app -w /app -e PYTHONPATH=/app/src --entrypoint python zmax-std:1.0 -u -m lerobot.scripts.lerobot_train --config_path /app/<cfg>`
- VLA-Touch/AWE：同容器但跑独立脚本 `-u /app/tools/train_vla_touch.py --data-root /app/<relpath>`（`os.path.relpath(data_root, root)` 转容器内路径）
- **⚠️ 独立脚本（train_vla_touch.py/train_awe_zflow.py）容器运行也必须 `-e PYTHONPATH=/app/src`（2026-08-10 实测）**：这俩脚本 import `lerobot.datasets.lerobot_dataset`，忘加 PYTHONPATH → 容器内秒退 `ModuleNotFoundError: No module named 'lerobot'`（EXIT=1 但 4 秒"完成"，日志只留一行启动横幅，像没跑）。**只对 lerobot_train 记得加、对独立脚本漏加是常见错**——统一模板：所有容器内跑仓库脚本的 docker run 都带 `-e PYTHONPATH=/app/src`
- **config root 必须转容器内路径**：模板生成 runtime 配置时 `re.sub(r"(root:\s*).*", f"root: /app/{os.path.relpath(data_root, root)}", ...)`——本地路径 `data/metaworld_peg` 容器内不存在 → `FileNotFoundError` 秒退
- **全量训练脚本必须生成带时间戳的 config**（`re.sub(output_dir...)` 加 `ts_dir`）：直接复用模板会 `FileExistsError: Output directory ... already exists` 秒退（rc≠0 但日志区像"没反应"）
- **⚠️ VLA-Touch/AWE 独立脚本 ckpt 目录硬编码 000050（2026-08-09 5000 步训练实测）**：`train_vla_touch.py` / `train_awe_zflow.py` 的 `ckpt_dir = os.path.join(out_dir, "checkpoints", "000050", "pretrained_model")` 是**硬编码**——`--steps 5000` 训完仍只落 `000050/pretrained_model`（不随步数变），且目录名 `vla_touch_<ts>` 若与旧训练同秒会**复用旧目录**。**判别训练是否真的跑完 5000 步：看训练日志的完成时间戳/`===[name] 完成 EXIT=` 行，别按 ckpt 目录名或 005000 目录判断**；评估用 `train_curve_<policy>.json` 指向该 ckpt 即可（000050 里是最新权重）
- 全量队列脚本每轮日志名带模型名（追加式 log，别每轮覆盖）
- **⚠️ 容器产物 root 权限坑（2026-08-08 实测）**：容器训练以 root 写 checkpoint，
  `model.safetensors` 权限 **0600 root** → 本地用户读不了 → 评估/加载报
  **`FileNotFoundError: .../model.safetensors`**（权限不可读伪装成文件不存在）。
  训练完成后**必做**：`sudo -n chown -R xspace:xspace outputs/train/<dir>` +
  `sudo -n chmod -R u+rw,go+r ...`（reports/ 下的 train_curve_*.json 也可能被
  root 只读化 → 一并 chown reports/）。别在没查权限前怀疑路径/加载逻辑。
- **评估/rollout/报告也强制容器（2026-08-08 老倪\"删掉本地训练代码；强制使用 docker 训练\"）**：
  不只 on_train——`rollout_video.py` / `compare_models.py` / `generate_report.py` 三处调用同样换
  `sudo docker run --rm --gpus all -v {root}:/app -w /app -e PYTHONPATH=/app/src --entrypoint python zmax-std:1.0 /app/tools/xxx.py`
  （rollout 的 `--out` 路径转 `/app/reports/...`；`--data-root` 用 `os.path.relpath(data_root, root)` 转容器内路径）。
  **全链路（训练/评估/推理/报告）无 venv 直跑残留**——grep 确认：`grep -c '\"--gpus\", \"all\"'` ≥5 处 +
  `grep -n '.venv'` 只剩 `_PY` 常量（CICD 流水线用）和注释说明
- **运行容器时终端显示容器属性（2026-08-08 老倪\"将容器在哪，属性信息，在终端显示出来\"）**：
  容器启动前 `log_signal.emit` 五行属性树——`🐳 容器启动: 本地 (WSL2 docker) · 镜像 zmax-std:1.0 (28GB · torch 2.11.0+cu128 · transformers 5.5.4)` +
  `   ├ GPU: --gpus all (RTX 4060 · NVIDIA Container Toolkit)` + `   ├ 挂载: {root} → /app (工程/数据/输出)` +
  `   ├ PYTHONPATH: /app/src · 工作目录: /app` + `   └ 训练: {pname} · 容器内执行`。
  用户要在终端看到容器在哪、什么属性——别只默默跑
- **日志智能滚动（2026-08-08 老倪\"终端别自动跳回末尾……突然跳了又找不到了……别总自作多情\"）**：
  `_append_log` 不能总是 `scrollbar.setValue(scrollbar.maximum())`——用户正看上面时新日志一跳到底就找不到了。
  **改：append 前读 `at_bottom = scrollbar.value() >= scrollbar.maximum() - 12`，只有用户在底部才跟随滚动**，
  否则 append 保持当前位置。规则：日志区自动滚动只在用户已拉到底时生效，绝不打断用户阅读位置

## 每模型训练开关（画布最前端 + 控制台双通道，2026-08-08 老倪）

老倪要每个模型（ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE/MLP蒸馏/官方专家）有独立训练开关，放**所有 node 最前端**（像 YOLO 感知开关的位置），让用户从一开始就感知开/关。双通道实现：
- **画布通道（simulink_module.py REFERENCE_APPS）**：CICD 主控台模板里总开关 `("train_gate", "☑ 训练开关", ...)` 之后加 7 个 `("train_gate", "ACT 训练开关", {"train_enabled": True, "policy": "act", ...})`——`policy` 参数区分模型；画布双击切换复用已有 `_toggle_train_gate`
- **`_train_gate_state(policy=None)`**：总开关（无 policy 参数）任一关 → False；模型开关（`params.policy == policy` 匹配）关 → False；无匹配开关 → True（向后兼容）
- **`on_train` 开头**：`if not self._train_gate_state(policy=policy): log_signal.emit("⏭ 跳过 X — 画布训练开关: 关"); return True, "跳过"`——训练最开始时检查
- **控制台通道（studio.py）**：训练按钮上方 `QGroupBox("🎛 训练开关")` 放 7 个 `QCheckBox(f"训练：开 {label}")`（QSS 开关样式 `QCheckBox::indicator:checked{background:绿}`，30×16 圆角），存 `self._zoo_sw[policy]`；`_zoo_next` pop 模型前 `while` 循环跳过 `not sw.isChecked()` 的模型（`_log("⏭ 跳过 X (训练开关: 关)")`），队列全跳过则提示完成
- **验证**：mock `m.nodes` 含总开关 + act开关(关) + smolvla开关(开)，断言 `_train_gate_state(policy="act") is False` / `policy="smolvla" is True` / 总开关关 → 全 False；控制台验证关 act 开关后 `_zoo_next` 跳过 act（mock pgrep 返回空，否则被真实训练进程的 pgrep 拦截不执行跳过）
- **坑**：给 on_train 插入开关检查时**保留原多行 docstring 全文**（`steps/batch_size/lr 来自节点逻辑…` 那段）——截断成裸字符串会 `SyntaxError: invalid character '—'`

## 全息 ID 管控系统（深度交互，2026-08-08 老倪"我需要看到每个窗口的ID，无歧义下指令"）

老倪要全局整理所有可交互元素（窗口/按钮/开关/表格/日志），每个有唯一 ID，通过 ID 无歧义对话（"点 B-01""开 S-03""切 M-02""查 T-01"）。实现于 studio.py TrainingModule：

- **⚠️ ID 渲染到控件本身——三次迭代的最终形态（老倪纠正到第三版才满意）**：①第一版「🌐 全息 ID 管控」表格面板（QTableWidget 列出 ID/名称/类型/状态）→ 老倪"我不会去用表格查询，那是你的事情；ID 要渲染到每个控件上；重改"（表格整块移除，`_holo_refresh` 加 `if not hasattr(self, "_holo_table"): return` 容错）；②第二版 ID 写进控件文字（按钮 `"▶ Start [B-01]"`/模式卡片 `f"{title} [M-0x]\n{sub}"`/开关 `f"训练：开 {label} [S-0x]"`/表格标题 `" 配置通道 [T-01] "`/日志 `"📋 终端日志区 [L-01]"`）→ 老倪"你的窗口，还是原来的窗口，没有看到 ID"（字在按钮文字里不明显且污染文案）→ **③最终形态：`_holo_badge(widget, h_id)` 角标方法——控件外包 QVBoxLayout（控件在上 + 左下角 10px 青色加粗 QLabel 小字 ID），控件文字全部恢复原名**（▶ Start / ⏹ Stop / 🔄 恢复默认 / 🔼 上传容器到远程 / 模式卡片 "🚀 远程训练\nV100 服务器" / 开关 "训练：开 ACT" / " 配置通道 " / "📋 终端日志区"）；**仅窗口标题保留 `[W-01]`**（`"XSpace Studio — Z-MAX v1.7.0 [W-01]"`）。用法：`btn_layout.addWidget(self._holo_badge(self.start_btn, "B-01"))`。**注册表 `_holo_reg` 保留在内部（那是我的事）**
- **ID 前缀体系**（人类可读分类）：`W-01` 主窗口 / `W-02` Model Engine 页；`B-01` Start / `B-02` Stop / `B-03` 恢复默认 / `B-04` 上传容器；`M-01..03` 模式卡片（远程训练/本地运行/端侧部署）；`S-01..07` 训练开关（ACT/SmolVLA/…/官方专家）；`T-01` 配置通道表格；`L-01` 终端日志区
- **`_register_holo_all()`**：逐类注册（按钮 lambda isEnabled / 模式 isChecked / 开关 isChecked / 表格/日志行数）；末尾 `self._holo_refresh()`
- **🐛 延迟注册坑（2026-08-08 实测注册表只有 7 个 ID）**：注册调用点在构造早期（容器区后 ~2504 行）——此时 `start_btn`/`_zoo_sw`/`_ct_mode_btns` **还没构造** → hasattr 全 False → 开关/按钮没注册、`_holo_act("S-01")` 报"❌ 无此 ID"。**修：`QTimer.singleShot(600, self._register_holo_all)` 延迟到构造完成后注册**（或构造尾部再调）。验证要等 700ms + processEvents 再断言注册表 ≥14 个 ID
- **`_holo_act(h_id)` 执行 ID 指令**：按钮/模式 → 映射表 click()（`{"B-01": "start_btn", ..., "M-01": ("_ct_mode_btns", "train")}`，tuple 取 `getattr(self, k)[key].click()`）；开关 → `{"S-01": "act", ...}` 映射 `self._zoo_sw[k].toggle()`；返回 `"✅ 已切换 S-01 (训练开关 ACT) → 关"` 等结果串（会话里直接回应用户）
- **验证（角标形态）**：构造 + 等延迟 700ms + processEvents → `len(m._holo_reg) >= 14` + `m._holo_act("S-01")` 后 `_zoo_sw["act"]` 状态翻转 + 角标断言——源码含 `self._holo_badge(self.start_btn, "B-01")`/`self._holo_badge(b, mid)`/`self._holo_badge(self._btn_upload_ct, "B-04")`；控件文字**已恢复原名**（`m.start_btn.text() == "▶ Start"`）；`m._holo_badge(m.start_btn, "B-01")` 返回的 wrap 有 layout；`"[W-01]" in 窗口标题`——**UI 形态 = 控件左下角角标，断言角标包裹 + 控件原名，别断言文字里的 ID**
- 老倪深度交互流程：用户说 ID → 我调 `_holo_act`（或 xdotool 定位）→ 日志区/回复里报结果——**控件状态永远以控件自身状态为准，别猜**
- **🐛 递归全局包装会崩 GUI——禁止 `replaceWidget` 批量包角标（2026-08-08 实测 GUI 进程直接死）**：老倪\\\"所有、所有、所有控件都要有 ID\\\\\\\" → 写了 `_holo_apply_all/_holo_walk/_holo_walk_layout` 递归遍历所有页布局，对每个按钮/开关/下拉/输入 `lay.replaceWidget(wgt, wrap)` 包角标：**① offscreen 验证环境 segfault（exit 139）；② 真实 GUI（DISPLAY=:0）启动后 1.5s 递归执行时进程直接死（`ps aux` 无 studio、xdotool 找不到窗口）**——QStackedWidget 多页 + 复杂嵌套布局下 replaceWidget 会破坏 Qt 布局所有权。**处理：主窗口构造尾部的 `QTimer.singleShot(1500, lambda: self.model_engine._holo_apply_all(self))` 整段注释禁用（保留代码供日后安全遍历用），手动逐控件 `_holo_badge(...)` 角标（Start/Stop/上传/模式卡片）继续生效**。**规则：给已存在的控件加角标/包裹一律手动在构造处 `_holo_badge(widget, id)` 包（布局明确、可验证）；不要递归遍历 reparent/replaceWidget——Qt 布局树不是随便能改的，崩了 GUI 连窗口都出不来**。GUI 崩溃恢复流程：`pkill -9 -f studio.py` → 注释掉危险调用 → 重启确认窗口出现（`xdotool search` 见标题）→ 再补验证
- **✅ 最终安全形态：`_holo_badge_overlay` 叠加 QLabel（2026-08-08 实测——递归全控件版恢复的唯一安全路径）**：`QLabel(h_id, widget)` 直接以控件为 parent 的子标签（`lbl.move(2, widget.height()-lbl.height()-2)` + `lbl.raise_()`），**完全不改布局**——QLabel 叠在控件左下角，无需 replaceWidget/reparent，多页复杂布局不崩。`_holo_apply_all(root)` 新版：`for w in root.findChildren(QWidget)` + `isinstance(w, (QPushButton, QCheckBox, QRadioButton, QComboBox, QLineEdit, QTableWidget, QGroupBox))` → `_holo_badge_overlay(w, h_id)` + 写 `_holo_coords`（ID 用 `_holo_seq_id`）。**页识别 `_holo_page_of(w)`**：沿 parent 链找 objectName（`simulink`→P11 / `model_engine`→P03 / `home`→P01…12 页映射），无匹配 → P00。主窗口构造尾部恢复 `QTimer.singleShot(1500, lambda: self.model_engine._holo_apply_all(self))`（overlay 版不崩）。**清理**：旧 replaceWidget 版 `_holo_apply_all/_holo_walk/_holo_walk_layout/_holo_assign_id` 同名方法删除（Python 后定义覆盖 + lint 报重声明；`_holo_name/_holo_type/_holo_state` 保留共用）。**验证**：静态断言 `def _holo_badge_overlay` + `QLabel(h_id, widget)` + 单一 `def _holo_apply_all` 定义 + `replaceWidget` 不在新版段；运行时 `m._holo_badge_overlay(w, id)` 返回 QLabel 且 `hasattr(w, "_holo_badge_lbl")`；**offscreen 下千万别实际调 apply_all 全树遍历**（findChildren 到 QGroupBox 叠加也可能触发插件崩溃）——静态 + 单控件验证即可
- **🌐 3D 坐标 ID 系统（2026-08-08 老倪\"需要有个坐标系统，类似3D坐标……每个ID都是这个结构的一个点\"——角标之后的最终形态）**：ID 升级为 `X.Y.Z` 三维坐标——**X=页（P01首页…P12数据空间 12 页）、Y=区块（01训练区 02容器区 03配置区 04数据区 05评估区 06日志区 07导航区 08状态区 09对比区 10部署区）、Z=控件序号**。类级常量 `HOLO_PAGES`/`HOLO_ZONES` + 方法 `_holo_coord(x,y,z)`→`\"P03.01.01\"`、`_holo_coord_desc(\"P03.01.01\")`→`\"模型引擎 · 训练区 · 控件01\"`（人类可读）、`_holo_coord_register(x,y,z,widget,name,type,getter)` 写 `self._holo_coords[cid]`。**`_holo_act` 支持两种 ID**：含 `.` 的坐标 ID 查 `_holo_coords`（按钮 click / 开关 toggle / 下拉 showPopup），无点走旧 `_holo_reg`（B-01/S-01 简写）。P03 模型引擎页注册 16 点：`P03.01.01`Start `P03.01.02`Stop `P03.01.03`恢复默认 `P03.01.05..11`训练开关(ACT..官方专家) `P03.02.01..03`模式卡片 `P03.02.04`上传 `P03.03.01`配置表格 `P03.06.01`日志区。**规则：坐标 = 控制台结构的点，注册表就是全局数据空间——说\"P03.01.01\"即点 Start，无歧义**
- **🎨 画布节点左下角 ID 绘制（2026-08-08 老倪\"simulink 功能也没有 ID 啊\"）**：模型引擎页有角标后画布（simulink）节点还是没 ID → 在 `NodeItem.paint`（simulink_module.py ~1018 行）主体绘制后追加：`painter.setPen(QColor(\"#00d4aa\")); painter.setFont(QFont(\"Arial\", 7)); nid = getattr(self, \"nid\", None) or f\"P11.{self.sid % 100:02d}\"; painter.drawText(QRectF(6, self.h - 13, ...), Qt.AlignLeft, nid)`——**每个画布节点左下角青色 7px 小字 ID**（P11 = 画布页坐标）。规则：画布节点 ID 用 paint 绘制（不是控件角标），节点创建处可分配可读 `nid`（默认 sid 兜底）

## 国内镜像加速器

Docker Hub 直连失败（`registry-1.docker.io` 拉取失败 / `unable to prepare context`）：
```json
/etc/docker/daemon.json → {"registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.1ms.run"]}
systemctl restart docker
```

## Dockerfile 在子目录时 COPY 路径按构建上下文根解析（2026-08-08 实测）

`docker build -f docker/Dockerfile .` 时，Dockerfile 里的 `COPY x` 相对**构建上下文根**（`.`），
**不是 Dockerfile 所在目录**——`COPY requirements.lock` 报
`COPY failed: file not found in build context or excluded by .dockerignore: stat requirements.lock`。
修：`COPY docker/requirements.lock /app/requirements.lock`（带子目录前缀）。同理 COPY . 之前先确认
入口脚本路径（train.sh/infer.sh 也在 docker/ 下 → `COPY docker/entrypoints/train.sh ...`）。

## 日志与进程陷阱

- `docker run -d ... > host.log`：host.log 只收**容器 ID**；训练日志在 `docker logs <container>`——验证/查进度用 docker logs
- `systemctl restart docker` 会**杀正在跑的 docker build**（buildkit 进程消失、log 卡死）——构建期间绝不重启 docker
- 提交后验证存活：`docker ps --filter name=<c>` + `docker logs <c>` 无 Error/Traceback——不要 grep 宿主 log（只有容器 ID）或 ps 进程（会匹配提交 shell）
- **`docker commit` 前必须先 `docker unpause`（2026-08-08 实测）**：SSH 会话中断会把容器挂成 `Up N minutes (Paused)`，此时 commit 的镜像层可能是**旧状态**——容器内 `python -c "import torch, torchaudio"` 验证 OK，但 commit 出来的镜像跑起来仍报旧的 CUDA 版本冲突。**铁律：commit 前 `docker ps` 确认非 Paused；commit 后用新镜像 tag 起一个干净容器重新验证，别信原容器内的验证结果。**
- **`pip force-reinstall` 会被 pip 缓存骗（2026-08-08 实测）**：`--force-reinstall torchaudio==2.4.1 --index-url .../cu124` 后 `pip show` 仍是 cu121——先 `pip cache purge` 再装；且 force-reinstall 会**连带升级 torch**（依赖关系）→ torch 又跳回最新 cu130 → 更乱。**修：torch/torchvision/torchaudio 三者同源同版本一次装齐**（全 cu121 或全 cu124，别混），必要时 `pip uninstall -y torch torchaudio torchvision` 后一次装。
- **串行队列每轮日志名必须带模型名（2026-08-08 实测）**：队列脚本 `> /tmp/train_tmp.log` 复用同名日志 → 上一轮失败的日志被下一轮覆盖 → 查失败原因时只剩最后一个模型的输出。修：`docker run ... bash -c "... > /tmp/train_${name}.log 2>&1"`，失败排查 `docker cp <c>:/tmp/train_<name>.log`。
- **多端（飞书端 bot + CLI 会话）同时操作远程容器会互踢（2026-08-08 实测）**：另一端会 `docker pause/stop/rm` 你的容器（exec 报 `container is paused` → unpause 后变 `No such container`）→ **动远程容器前先对账**：`docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}'` + `docker top <c>` 看容器在跑什么；协调分工（谁 commit/谁训练），别自己从零起容器覆盖对方正在跑的。被删后重建：`docker run -d --name zmax_train --device 三设备 -v libcuda.so.1 -v 工程:/app <镜像> sleep infinity` + `docker cp` 重拷脚本
- **`docker exec -d <c> bash x.sh` 的后台脚本不随容器持久**：容器被删/重建后 /tmp 里的脚本丢失（log 也不存在）→ 重建后必须 `docker cp` 重拷脚本再 exec；exec 后查进度先 `docker exec <c> bash -c 'tail log'` 确认 log 存在，别直接 tail 宿主 /tmp（路径在容器内）
- **ad-hoc 验证脚本断言"容器命令存在"别用 `split(关键字)[1][:N]` 窗口（2026-08-08 四连败教训）**：关键字（如 `train_vla_touch.py`/`zmax-std`）在文件里出现多次（注释/文档字符串/远程分支都有）时，`split` 取第一个出现位置，前 N 字符窗口内常没有 docker 命令 → 误报"✗ 非容器"、浪费 3-4 轮排查；且注释措辞被协作者（飞书端）改过（如"本地训练切容器运行"→"训练强制容器"）后旧断言直接 IndexError。**正确写法：行级上下文**——`lines = src.splitlines()`，找到含关键字的行 `i`，取 `"\n".join(lines[i-span//2:i+span])` 再查 `docker", "run`/`zmax-std`；或直接 grep 实测行号（如 `grep -n` 得到 5107）按行号区间断言。**规则：验证脚本断言的是代码事实（grep 可得），不是注释/字符串措辞——断言前先 `grep -c` 关键命令确认计数再写脚本**
- **批量 sed 给 site-packages 补 import 的两大坑（2026-08-08 实测）**：① `sed -i '1i import torch'` 会把 import 插到 `from __future__` 之前 → `SyntaxError: from __future__ imports must occur at the beginning of the file`（必须先删掉再插到 future 行之后）；② `grep -q 'import torch'` 判断"已修"会被**块内缩进 import**（如 tensor_parallel.py 29 行 `    import torch` 在 if 块里）骗过 → 顶层仍没有 → 继续崩——修后要 `head -3` 确认顶层真的 import 了，且 sed 顶层插入统一插在 `# Licensed` 注释行之后

## 远程磁盘满 + 容器镜像 tag 检查坑（2026-08-08 实测）

- **远程磁盘 100% → 容器训练秒崩 `OSError: Not enough disk space`**（报错在 datasets `builder.download_and_prepare`——下载/生成缓存无空间）。查 `df -h /`（`/var/lib/docker` 40G+ 常见元凶）。**清理序列**：`docker builder prune -f` → `docker system prune -f` → `rm -f /tmp/*.tar /tmp/*.whl`（siglip.tar 585M 等）→ `docker rmi` 旧镜像（保留 zmax-train:latest/final）——实测 100%→80%（腾出 ~39G 即可恢复训练）
- **on_train 远程分支镜像检查假阳性（GUI 显示\"🐳 远程容器训练已启动\"但实际没训）**：`if ! docker images -q zmax-train:latest` ——远程镜像 tag 只有 `zmax-train:final/full` 没有 `:latest` → 条件恒真 → 走 BUILDING 后台构建分支（`nohup docker build ... & echo BUILDING`）→ 训练从未提交、GPU 0%、容器不存在。**修：`docker tag zmax-train:final zmax-train:latest`（一次即可），且 `docker rm -f zmax_train 2>/dev/null;` 放在 `docker run` 前防名字冲突**（旧容器残留时同名 run 直接失败）
- 容器秒退且 `remote_train.log` 里只有容器 ID：`docker run -d > log` 收 ID 是正常行为——**看 `docker logs <c>`，或前台跑一次不带 `-d` 看真实报错**（磁盘满就是这个路径查出来的）

## 训练/容器状态 → 飞书 dataworld 通知（2026-08-08 老倪要求"修好了给飞书发消息"）

容器训练跑通/状态变更时，老倪要求主动发飞书通知（用户从飞书端监控）：
```bash
cd ~/.hermes && APP_ID=$(grep FEISHU_APP_ID .env | cut -d= -f2 | tr -d '"') && \
APP_SECRET=$(grep FEISHU_APP_SECRET .env | cut -d= -f2 | tr -d '"') && \
TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json" -d "{\"app_id\":\"$APP_ID\",\"app_secret\":\"$APP_SECRET\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('tenant_access_token',''))") && \
curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"receive_id":"oc_c0b4048546145c5c581ddd1a9e8f565d","msg_type":"text","content":"{\"text\":\"🐳 消息内容\\n✅ …\"}"}'
```
要点：dataworld 群 chat_id `oc_c0b4048546145c5c581ddd1a9e8f565d`；凭据在 `~/.hermes/.env`（FEISHU_APP_ID/SECRET，本会话用 xspace 机器人 App）；成功返回 `"code":0`；中文消息里的 `\n` 在 content JSON 里要写 `\\n`。

### 📤 飞书发文件（mp4/PDF）— media vs file 消息类型（2026-08-09 实测，230055 根因）

发视频/报告到群用 `im/v1/files` 上传 + `im/v1/messages` 发消息，两个**必须记住的坑**：
1. **上传后发消息类型必须匹配文件类型**：`mp4` → `msg_type: "media"`（视频消息），`pdf` → `msg_type: "file"`（文件消息）。**用 `file` 发 mp4 报 230055 `The type of file upload does not match the type of message being sent`**。规则：`msg_type = "media" if file_type == "mp4" else "file"`
2. **urllib multipart/JSON 请求必须显式 `Content-Length` 头**（python3.14 实测）：不带 → `HTTP 400 Bad Request`，且 400 响应体才是真正错误（230055 等）。上传 multipart body 和 `_post` JSON 都加 `"Content-Length": str(len(body))`
- 上传 multipart 字段顺序：`file_type` → `file_name` → `file`（二进制）；`file_type` 值是 `mp4`/`pdf` 等，`file_name` 是文件名
- 上传成功拿 `data.file_key` → 发消息 `content: json.dumps({"file_key": fkey})`
- 三文件一次发齐（对比视频 + 单模型视频 + PDF 报告）实测成功；诊断 400 时**捕获 HTTPError 读 `e.read().decode()` 看业务码**（如 230055），别只看 HTTP 状态

## 🐛 arm64 推理镜像本地交叉构建（2026-08-09 x86 4060 实测——无 buildx 插件 + QEMU 模拟）

x86 主机构建 arm64（Mac/Orin 部署）镜像：docker.io 的 docker 默认**无 buildx 插件**，且
`apt install docker-buildx` 在 Ubuntu 源里常 Ign 失败——**从 ghfast.top 镜像下载 release 二进制**：
```bash
# ① buildx 插件 (官方 GitHub 直连超时 → ghfast.top 镜像加速)
curl -sL -o /tmp/buildx "https://ghfast.top/https://github.com/docker/buildx/releases/download/v0.14.0/buildx-v0.14.0.linux-amd64"
sudo mkdir -p /usr/libexec/docker/cli-plugins && sudo cp /tmp/buildx /usr/libexec/docker/cli-plugins/docker-buildx && sudo chmod +x ...
docker buildx version   # github.com/docker/buildx v0.14.0
# ② QEMU binfmt (arm64 模拟执行, 必须 --privileged)
sudo docker run --privileged --rm tonistiigi/binfmt --install arm64
# ③ 多平台构建器 (创建后 inspect --bootstrap 拉 buildkit, 首次可能 context deadline exceeded → sleep 30 重试)
docker buildx create --name multi --platform linux/amd64,linux/arm64 --use
docker buildx inspect multi --bootstrap   # 等 STATUS: running
# ④ 构建 arm64 单阶段 (--load 导回本地; --target infer 只建推理阶段)
sudo docker buildx build --platform linux/arm64 --target infer -t zmax-infer:arm64 --load -f docker/Dockerfile .
```
**arm64 依赖铁律**（QEMU 模拟下编译 C/Rust 包极慢/失败 → 全部锁二进制 wheel 版本）：
- `av==14.1.0`（`av<15,>=13.0` 会被解析到无 arm64 wheel 的版本 → 源码编译 PyAV 失败）
- `tokenizers==0.22.2`（transformers 5.5.4 要求 `tokenizers<=0.23.0,>=0.22.0` — lock 里 0.21.4 会
  `ResolutionImpossible`）
- `huggingface-hub>=1.5.0,<2.0`（transformers 5.5.4 硬要求，lock 曾写 <0.37 冲突）
- **验证 lock 全量可装再构建**：`docker run --rm --platform linux/arm64 --entrypoint pip python:3.12-slim
  install --only-binary :all: --dry-run -r <(cat lock)` 无 error 输出才跑 buildx（省 3-4 轮 QEMU 慢构建）
- 镜像验证：`docker run --rm --platform linux/arm64 --entrypoint bash <img> -c "python -c 'import torch; print(torch.__version__)'"`
  （arm64 下 torch 是 `2.11.0+cpu`，非 cu128 — 正常）
- 推理镜像大小：arm64 CPU 版 ~6GB（含模型权重内置），`docker save | gzip` 后 ~5.9GB

## ⚠️ ECS scp 大文件 Connection closed — 小文件 base64 通道（2026-08-09 实测）

ECS（阿里云宝塔）scp 传 >~100MB 文件全部 `Connection closed`（87MB 模型能传，500MB/900MB 分块全断，
重试/keepalive/split 分块均无效——疑似云安全组大连接限制）。**能用**的通道：
- **小文件 (<100MB)**：scp 或 **base64 经 SSH 写文件**（scp 也断时）：
  `python3 -c "import base64;print(base64.b64encode(open(f,'rb').read()).decode())" > /tmp/b64.txt` 然后
  `ssh host "echo '$(cat /tmp/b64.txt)' | base64 -d > /path/file" && chmod 644`（7.7KB JSON 实测可行）
- **大文件 (GB 级)**：scp 死路 → 换路径：web 端 4090 上传 / Mac 直传 / HTTP 上传接口 /
  ECS 侧 nginx 调 `client_max_body_size`——别在 scp 上反复试（每轮 5-10 分钟白等）
- **端口注意**：ECS 22 可能被封 → `-P 23`；SSH 失败多次会临时封锁（等 30s 再试）
- 部署核对：上传后**必须 ls + chmod 644 + curl 本机验证**（`-rw------- 600 root` 的文件 nginx 访问 403，
  控制台日志"✅ 已上传"可能没落盘——之前 act_latest 声称上传但文件不存在，手动重传才真实存在）

## 远程 GPU 服务器通用坑

- **大权重跨网络传输是死路——优先在有权重缓存的机器训练（2026-08-08 实测）**：AWE 需要 SigLIP
  权重（本地 `~/.cache/huggingface/hub/models--google--siglip-base-patch16-224` 776MB），远程无缓存
  只能从 HF 下载或从本地传。实测：scp 775MB tar 传 30+ 分钟只到 55% 中断（网络慢），rsync 续传也卡
  死（0% CPU 挂着不传）→ **AWE 远程训练 2 小时没跑起来**；切回本地 4060（SigLIP 缓存完整 +
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 离线模式）→ **秒起训练 335/2000 步**。
  **规则：训练机器选择先看 HF 权重缓存在哪**——远程没缓存的大模型（SmolVLA/SigLIP/AWE），
  本地有缓存就本地训；远程只跑数据已在远程且权重可下载的模型（ACT/MLP）。别把时间耗在传权重上。
- 多端版本必须对齐（老倪 2026-08-08 "版本差挺大/中版本保持一致"）：本地 / GitHub /
  远程服务器三处 git 版本要一致。远程落后时 `git pull` 会被**远程本地修改**挡住
  （config root 指向 grab6 等训练配置）→ **先 `git stash` 再 pull**（stash 保留远程
  特有训练配置，不回推污染主仓库）。对齐后三方 `git log --oneline -1` 验证同一 SHA。
- 服务器可能缺 curl → 用 `wget -qO-`（`curl -fsSL` 全静默失败）
- sshpass 的 `-p` 会吞 ssh 的 `-p <port>` → 用 `-o Port=<port>`
- apt 源装包失败先查 `apt-get update` 是否真有该包（`Unable to locate package` = 源没配/路径错）
- GitHub release 大文件（deb ~20MB）在国内服务器常超时/404——先确认 asset 准确文件名（带 `-1` 修订号）再 wget

## 📥 远程训练完成自动拉回模型（2026-08-09 老倪"模型要拉回本地，模型引擎能看到路径"）

训练容器退出后自动把 checkpoint 拉回本地并注册，供模型引擎显示 + Simulink rollout/报告消费。链路与坑详见 `references/remote-model-pullback-render.md`，要点：
- **拉回目标结构必须匹配 rollout 的查找逻辑**：`rollout_video.py` 读 `reports/train_curve_<policy>.json` 的 `ckpt` 字段 → `os.path.join(ROOT, ckpt)` 当 base_dir → 拼 `base/last/pretrained_model`。**所以 ckpt 必须指向 `outputs/train/<name>_<ts>/checkpoints`（含 checkpoints 层）**，不是顶层目录——否则 `FileNotFoundError: checkpoint 不存在`（容器内 `os.path.isdir` 判 False）
- 拉回三件套：① scp 远程 `checkpoints/last/pretrained_model` → 本地同结构 ② 写 `reports/train_curve_<policy>.json`（policy 名映射：ACT→act、SmolVLA→smolvla…）③ 注册 `models/saved/registry.json` + 回填模型引擎 `ckpt_edit`（可编辑路径）+ `_refresh_saved_models()`
- **控制台 QTimer 拉流线程可能没在跑**（训练由看护/其他窗口提交时）→ 拉回不自动触发，手动执行同一套逻辑即可（scp + 写 json）
- **DatasetModule `max([])` 启动崩溃**：拉回目录 checkpoints 下只有 `last/`（无数字步数目录）→ `max([int(b) for b in os.listdir(ck) if b.isdigit()])` 空列表崩 → 空列表回退 0 + try/except

## 🎥 rollout 容器无头渲染（xvfb/EGL，2026-08-09 实测）

`rollout_video.py` 渲染 metaworld 视频需要显示环境：
- `MUJOCO_GL=glfw` 需 X11（`GLFWError: X11: Failed to open display :0`）——容器里没有
- `MUJOCO_GL=egl` 需系统 `libegl1`（否则 `AttributeError: 'NoneType' object has no attribute 'eglQueryString'`）
- **Debian 13 (trixie) 容器装渲染依赖**：`apt-get install -y libglfw3 libegl1 xvfb`，然后 `xvfb-run -a -s '-screen 0 1280x1024x24' python rollout_video.py ...` 无头渲染
- **`docker commit` 固化依赖的坑**：apt 安装是异步的，`which Xvfb` 成功 ≠ 装完（xvfb-run 可能还没落盘）——commit 前容器内确认 `which Xvfb xvfb-run` 都在；commit 出 tag 后**用新 tag 起干净容器重新验证**（如 `zmax-std:render` 跑 xvfb-run 冒烟）
- 远程 GPU 拉回的模型在本地容器（zmax-std:1.0）渲染时注意本地也要有渲染依赖或 xvfb

## 🔭 远程训练监控看护（2026-08-09 老倪"你盯着，断了找原因自动再运行"）

用户要求盯到训练完、断了自动重启时用后台轮询脚本（60s）：`docker ps --filter name=zmax_train` → Up 则 `docker logs | grep -oE '[0-9]+/2000' | tail -1` 读进度、6 分钟无进展强制重启；容器没了 → grep `2000/2000` 判完成（否则自动 `docker run -d ...` 重启）；完成才退出（notify_on_complete）。**判断"完成"以日志里的最终步数为准**（`2000/2000` 或 `100%|`），不是容器退出本身。

## ⚠️ Model Zoo 远程队列误判"完成"循环刷屏（2026-08-09 老倪"你都显示自动交付了"）

`_zoo_next` 用 `pgrep -f lerobot_train` 判本地训练——**远程容器训练时本地无此进程 → 每 15s 轮询误判"🏁 Model Zoo 完整训练完成"并重复触发自动交付**（生成视频/PDF/发飞书刷屏）。修复：① `_zoo_finalized` 标志——完成分支只触发一次自动交付 ② `_zoo_remote_wait`——on_train 返回"容器化远程提交"时改查远程 `docker ps -q --filter name=zmax_train`，在跑则等、退出才推进队列 ③ 新一轮训练重置 `_zoo_finalized`。**规则：远程容器训练模式下，队列推进判定不能靠本地 pgrep，要查远程 docker 容器**。

## 🐛 子线程日志丢消息 — QTimer.singleShot 跨线程不可靠（2026-08-09 实测，推翻旧"singleShot 回主线程"建议）

PyQt5 下非主线程 `QTimer.singleShot(0, lambda: ...)` / `QMetaObject.invokeMethod` 跨线程调度**会丢消息**（用户点上传只见"开始…"再无下文，线程里日志全丢）。**可靠方案：队列 + 主线程 QTimer 定时 flush**——`_log` 非主线程时 `self._log_queue.append(text)`，`QTimer(self).start(200)` 每 200ms 调 `_flush_log_queue` 把队列逐条 `_append_log`。验证：offscreen 实例化 + 原始 `_log` 路径（零 monkeypatch）+ 8s 事件循环，断言子线程日志全部出现。

## ⚠️ ssh 远程命令 f-string 转义（2026-08-09 三连败教训）

远程命令拼 f-string 时 awk/引号转义极坑：`\\$3`（源码 2 反斜杠）渲染 `\$3` → shell 双引号内 awk 收到 `$3` ✓；`\\\\$3`（4 反斜杠）渲染 `\\$3` → awk 报 `unexpected character '\'` ✗。**patch 工具改写含反斜杠的 f-string 极易双重转义搞坏语法**——改这类行用 Python 字节级替换（`chr(92)` 显式拼反斜杠）或 `git checkout` 恢复后精确重建；改完必须 `ast.parse` + eval 该 f-string 验证渲染结果，别只看语法过。

## 参考

- Mac 端 arm64 容器部署链路 + 原生构建 vs 交叉编译(含 x86 本地 buildx 实操路径) + ECS nginx 日志验证 Mac 拉取: `references/mac-native-arm64-deploy.md`
- Z-MAX 应用实例（--device 命令/Dockerfile/加速器全流程）：`~/.hermes/skills/software-development/zmax-console/references/20260808-container-edges-novae.md`
- 远程拉回模型 + 无头渲染 + 监控看护细节：`references/remote-model-pullback-render.md`
