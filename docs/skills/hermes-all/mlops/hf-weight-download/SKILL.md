---
name: hf-weight-download
description: HF权重下载卡死解决, ignore_patterns跳onnx, 断点续传, 离线加载验证。
---

# HF 权重下载卡死解决方案 (SmolVLM2 等大模型)

## 触发
- huggingface 下载卡在 0% / .incomplete 文件堆积
- SmolVLA/SmolVLM 权重加载失败

## 根因
- HF 网络到特定仓库不稳定 (官方源 + 镜像都可能断)
- snapshot_download 默认下载全部 38 文件 (含 1.4G onnx 不需要)

## 解决方案
1. **跳过不需要的文件**: `snapshot_download(repo, ignore_patterns=['onnx/*'])`
2. **断点续传**: huggingface_hub 自动续传 .incomplete, 多次重试
3. **长跑重试**: for 循环 20 次 × timeout 550s, 失败 sleep 20 重试
4. **验证**: `TRANSFORMERS_OFFLINE=1 AutoModel.from_pretrained(repo)` 能加载=成功
5. **只下必需文件**: `hf_hub_download(repo, 'model.safetensors')` 单文件断点续传

## 训练时
```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1  # 离线加载 (有缓存时)
```

## 注意
- 不要 rm -rf *.incomplete 会误删已下载分片 (缓存 2.4G→245M 教训)
- onnx 文件 (1.4G+) 训练不需要, 跳过
