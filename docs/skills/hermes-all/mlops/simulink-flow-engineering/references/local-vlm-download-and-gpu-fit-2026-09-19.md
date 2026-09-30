# 本地 VLM 落地: 下载 + 显存 (2026-09-19 实测, 与 vlm-result-panel-and-node 配套)

把本地开源 VLM (Qwen2.5-VL-3B) 装进画布节点时踩的两个环境陷阱 — 都不是"模型太大", 而是环境把它挤掉了。

## ① 磁盘守护会删掉"正在下载"的权重 → 下载中途崩
现象: `snapshot_download` 报 `FileNotFoundError: .../*.incomplete`, 缓存从 4.9GB 掉回 12MB。
根因: 磁盘红线守护脚本会清理 `~/.cache/huggingface` 下的 `*.incomplete`; 被下载器占用的分片被删 → 崩。
**修法 (已验证下完 7.1GB 完好)**: 缓存根指到不受守护扫描的目录并用镜像:
```bash
HF_HOME=/home/ubuntu/zmax_data/hf_home HF_ENDPOINT=https://hf-mirror.com \
gui-venv311/bin/python -c "from huggingface_hub import snapshot_download as s; print(s('Qwen/Qwen2.5-VL-3B-Instruct', allow_patterns=['*.json','*.safetensors','*.txt','*.py','*.model']))"
```
**下完必须核验**: `snapshots/*/` 里是否 `config.json` + 全部 `*.safetensors`, `du -sh` 对量级;
别只看"进程退出码 0"。随后把 **snapshot 绝对路径**写进客户端当本地模型默认值。

## ② 8GB 卡装不下 bf16 的 3B 级 VLM
实测: 3B bf16 **≈6.5GB**, 卡上另有 ~1GB 常驻 (GUI/采集/检测) → 加载即
`OutOfMemoryError: Tried to allocate 2.00 MiB ... 8.62 MiB free`。
对策(按优先): **4bit 量化(≈2.5GB)** > 更小模型 > CPU(慢但可跑)。
排查: `nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv` 看清谁占显存;
先回收自己起过的残留 worker (实测 5 个 python 各占 100~270MB, 加起来就是压死骆驼的那点余量)。
⚠️ "只差 2MB" 也照样失败 —— 这类 OOM 的根因是**余量被常驻进程吃掉**, 不要误判为"模型太大"。

## ③ 客户端要能强制选 provider
`.env` 里有 API key 时, provider 解析会永远走云端 → 本地模型轮不到, 表现为"我明明下了本地模型还在调 API"。
留一个显式开关 (本项目: `SS_VLM_PROVIDER=local`) 并把它写进节点说明。
