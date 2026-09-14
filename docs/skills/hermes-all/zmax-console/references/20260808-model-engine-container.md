# 2026-08-08 模型引擎容器化 + 参数联动 + 远程提交防假阳性

## 🐳 容器化模型引擎（取代 venv 方案 — 老倪"参考容器化方案"）
远程 GPU 训练统一走 Docker：
- 仓库根 `Dockerfile`：`FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime` + `COPY . /app` + `pip install -e .`（torch 镜像自带, 免重下; V100 sm_70 支持）
- `.dockerignore`：data/outputs/reports/*.mp4/*.pdf/*.pt 排除
- 提交命令（studio `_start_remote_training` + simulink on_train 远程分支同款）：
  ```
  cd ~/lerobot-smolvla-lew && \
  if ! docker images -q zmax-train:latest >/dev/null 2>&1; then \
    nohup docker build -t zmax-train:latest . > /tmp/docker_build.log 2>&1 & echo BUILDING; \
  else docker run -d --rm --gpus all -v ~/lerobot-smolvla-lew:/app -w /app --name zmax_train \
    zmax-train:latest python -m lerobot.scripts.lerobot_train --config-path <cfg> \
    > /tmp/remote_train.log 2>&1; echo RUNNING; fi
  ```
- BUILDING → 日志提示"镜像构建中, 完成后重跑"; RUNNING → sleep 3 验证 `docker ps --filter name=zmax_train` + 日志无 Error/Traceback
- 远程环境轮询 `_poll_remote_env`（每 30s: venv/lerobot 就绪 → 标签变绿"✅ 就绪"; 安装中显示日志尾）

## ⚠️ 远程训练"已启动"假阳性（老倪两次抓到）
1. `nohup python ... & echo $!` 返回 pid 但进程秒崩（python 不存在/路径错/lerobot 未装）→ 日志"已启动"误导
2. `ps aux | grep [l]erobot_train` 匹配**提交命令的 ssh shell 自身** → 假"存活"
根治：提交后 sleep 3 验证——进程/容器列表 + 日志 tail 无 Error/Traceback/No such file。

## 🔧 服务器部署关键
- lerobot 要求 **Python ≥3.12**（3.10 的 venv 装不上——`pip install -e .` 报 "requires a different Python"）→ deadsnakes 装 3.12 或容器化
- lerobot 是 **pip 包**（site-packages 的 `lerobot.scripts.lerobot_train`）——**不是仓库 lerobot/ 目录**——必须 `python -m lerobot.scripts.lerobot_train`（`lerobot/scripts/lerobot_train.py` 相对路径会 No such file）
- ssh 端口：`sshpass ... ssh -p 24212` 的 **-p 会被吞（连 port 22）→ 必须 `-o Port=24212`**
- Ubuntu 22.04 无 pip → `apt install python3-pip`（ensurepip 也没有）

## 🧠 模型参数联动（老倪: "选择好模型后参数得跟着变化"）
`_on_model_changed(name)` 三件事：
1. 参数区标题跟随（`param_group.setTitle(f" {name} Parameters ")`）
2. steps/batch/lr 读对应 config（`^\s*{key}:\s*([\d.eE+-]+)` 正则——**lr 在 optimizer 缩进下, 必须 \s***; QSpinBox 无 decimals()——try float 再 int 回退）
3. ARCH_PRESET 每模型硬编码（obs/chunk/vlm/expert/width/freeze/wm/attn）——**vlm/expert=0 的模型（ACT/MLP/专家）禁用对应 spinbox**（setEnabled(False)+setValue(minimum); >0 恢复并 setValue）
4. 产物探测（glob outputs/train/*tag* → ckpt 步数/时间显示）

## 🐛 dict.get 默认参数 KeyError 坑（本次根因）
`{"a":1}.get(name, {"b":2}[name])` —— **默认参数无条件求值**（即使 get 命中）→ name 不在默认 dict 时 KeyError 秒崩（方法 try/except 吞掉 → 后续逻辑全不执行, 表现为"参数没变"）
修复：`dict1.get(name) or dict2.get(name, fallback)`（两个 get 串联, 不求值未命中默认）
排查法：临时把 `except Exception: pass` 改成 `except Exception as e: print(repr(e))` —— 信号槽异常 PyQt 吞掉不打 stderr。

## 🔗 几何条件连线（老倪: "还是没有连线"）
edges 补：(4, 5, "latent+几何") StateAdapter→🧩; (5, 7/12/16/21/27) 🧩→各模型主干。共享节点定义放 node_specs **末尾**（不占原索引保 edges 编号不变）；布局引用名匹配。
多端口节点渲染：paint else 分支——`len(inputs)>1 or len(outputs)>1` 时按定义画端口+标签（bbox/latent→latent+），否则按连线数画单端口（无连线=中间一点 → 看起来"没有输入输出"）。

## 🔄 外部会话（飞书端）并发改代码
飞书端/其他会话会直接改本地工作区文件（未提交）+ push 远端：
- patch 前先 `git status --short` + `git fetch` 对齐（"modified since last read" 警告 = 外部改过, 重读再改）
- 老倪看不到改动 ≠ 没改 —— 可能 GUI 没重启（kill -9 后守护 systemd/gateway 会自动拉起新实例读最新代码）
- GUI 有守护（auto_restart, 父进程 systemd/gateway）——kill 后自动拉起, 多个实例时全部 kill 再启动一个
