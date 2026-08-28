# 2026-08-08 容器化模型引擎 + edges 索引错位 + 无VAE结论

## 1. 远程 GPU Docker 容器化训练（模型引擎）

**--device GPU 透传（免 nvidia-container-toolkit）**：
国内 GPU 服务器装 nvidia-container-toolkit 极难（curl 缺失/官方源 Release 404/GitHub CDN 受限）。
替代：手动设备透传，torch.cuda 完全可用：
```
docker run -d --rm \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm \
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  -v ~/repo:/app -w /app --name zmax_train zmax-train:latest \
  python -m lerobot.scripts.lerobot_train --config-path cfg.yaml
```
验证：`docker run --rm --device ... 镜像 python -c "import torch; print(torch.cuda.is_available())"` → True。

**Dockerfile 坑**（pytorch 官方镜像 Python 3.10 < pyproject >=3.12）：
- `pip install --ignore-requires-python -e .`（不加会拒绝安装 lerobot）
- 必须**全依赖**安装（`--no-deps` 会漏 termcolor/tensorboard 等 → 训练启动 ModuleNotFoundError 秒退）
- 镜像内无 nvidia-smi（pytorch 官方镜像不带）→ 容器 GPU 测试用 torch.cuda 而非 nvidia-smi

**国内镜像加速器**（Docker Hub 直连失败 "unable to prepare context/registry-1.docker.io"）：
```
/etc/docker/daemon.json → {"registry-mirrors": ["https://docker.m.daocloud.io", ...]} + systemctl restart docker
```

**其他坑**：
- `docker run -d` 的 stdout 重定向 = 容器 ID；训练日志在 `docker logs zmax_train`（宿主文件只看到容器 ID）——验证/查进度用 docker logs
- `systemctl restart docker`（如装 toolkit 时）会**杀正在跑的 docker build**（buildkit 进程消失、log 卡死）——构建期间不要重启 docker
- 服务器缺 curl 用 wget（`wget -qO-` 代替 `curl -fsSL`）
- SSH `-p 24212` 被 sshpass 吞 → 必须 `-o Port=24212`

## 2. simulink edges 索引错位（SmolVLM2/SigLIP 没接）

**症状**：模板加载后某些节点入0出0（SmolVLM2/SmolVLM2·LEW/SigLIP），部分节点连线错位。
**根因**：load_reference_app 里跳过共享节点（`continue`）→ `ids` 列表 = 实际创建顺序（少了共享），但 edges/link_specs 数值 = **定义索引**（含共享）→ 之后所有索引偏 1。
**修复**：记录 `index_to_id[i] = n["id"]`（定义索引→实际 id），links 用 `index_to_id.get(fi/ti)` 转换，不再用 `ids[fi]`。
**通用教训**：定义顺序索引 ≠ 创建后列表索引——凡有 skip 就必须显式映射。

## 3. 无 VAE 结论（静界对照实验 2026-08-08）

| 版本 | 数据 | 叠加 | VAE | 结果 |
|---|---|---|---|---|
| overlay2 | 17条纯接近 | ✅ | ✅ | ❌ 不动 |
| big | 68条纯接近 | ✅ | ✅ | ❌ 不动 |
| **novae** | 68条纯接近 | ✅ | ❌ | ✅ 动了(0.066m) |

**无 VAE 是决定性**：VAE encoder 训练时偷看未来动作（作弊），推理时 latent=0 → 模型傻眼"不会动"；
latent += state 叠加放大了该坑。无 VAE 后 latent 恒 0 + state = 干净信号 → 学 state→动作 直映射（像 MLP）。
控制台升级：ACT 行 VAE 节点标"🚫 VAE 编码器（无）"use_vae:false；config_act_pegdata.yaml use_vae:false；node_logic 默认 False。
