# ACT 推理环境清单（2026-08-01 实测，RTX 4060 Laptop / WSL）

## 环境
- venv: `~/.venvs/act`（Python 3.12.13，经 `~/.hermes/bin/uv python install 3.12` 安装）
- torch 2.6.0+cu124, torchvision 0.21.0+cu124（阿里云镜像 curl 直链 + `--no-deps`）
- nvidia 全套运行时库（cublas/cudnn/cufft/cusolver/cusparse/nccl/nvrtc/nvjitlink/cupti/nvtx/curand/cusparselt — 全部 `--no-deps`）
- lerobot 0.5.2（`pip install --no-deps -e .`）
- 关键版本：transformers 5.5.4（lerobot 要求 >=5.4.0,<5.6.0）、tokenizers 0.22.2（0.23.0 不存在）、huggingface_hub 0.3x-0.9x（<1.0）、numpy 2.2.6（<2.3）
- 验证通过: `torch.cuda.is_available()=True`, 识别 RTX 4060

## 控制台改造（commit 64f04d5，lerobot-smolvla-lew 仓库）
- `tools/gui/inference_server.py`: POLICY_TYPES 注册表 {smolvla, act} + `load_policy()`；ACT 分支 `patched_spi_act` — 按 `policy.config.input_features` 键名构建 obs（state 键含 "state"、image 键含 "image"，0-1 归一化）→ `policy.select_action(obs)` → TimedAction 列表；不走 SmolVLA 的 tokenizer/定制预处理
- `tools/gui/inference_client.py`: `send_policy(checkpoint_path, policy_type=..., device=...)`
- `tools/gui/studio.py`: InferencePanel 策略下拉框（SmolVLA/ACT），切换自动更新模型路径提示
- `tools/gui/act_infer.py`: 独立验证脚本，`--random` 模式跳过下载

## 验证配方（跳过 HF 下载）
```bash
~/.venvs/act/bin/python tools/gui/act_infer.py --device cuda --steps 2 --random
```
- ACTConfig 必须用 PolicyFeature 对象（不是 dict）：
  ```python
  from lerobot.configs.types import FeatureType, PolicyFeature
  input_features={
      "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(6,)),
      "observation.images.cam_high": PolicyFeature(type=FeatureType.VISUAL, shape=(3, 480, 640)),
  }
  output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(7,))}
  ```
- 实测：51.6M 参数（resnet18 backbone）、chunk=50、首轮推理 219ms（含初始化）、输出 (1,7) 动作（6轴+夹爪）
- `--random` 首次运行会下载 resnet18 ImageNet 预训练权重 44.7M（torchvision 缓存），非卡死

## Pitfalls
- HF Hub 被网络层拦截：huggingface.co 与 hf-mirror.com 均返回 401 "Invalid username or password"（代理拦截，非模型 gated）→ 预训练模型必须走本地路径 `local_files_only=True` 或用户提供；ModelScope 主站可达但 API 路径需另查
- CUDA tensor 转 numpy 必须先 `.cpu()`: `np.asarray(out.detach().cpu())`
- 控制台 run_studio.sh 优先找 conda lerobot 环境；本机用 `~/.venvs/act` 需手动指定 python 路径
