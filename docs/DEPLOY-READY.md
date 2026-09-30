# Mac 部署管线 · 就绪状态

> 小芳 @ 2026-07-13 · 等 xspace 数据管线 + web 模型

## 当前就绪

| 阶段 | 状态 | 工具 |
|:---:|:---:|------|
| Orin 通信 | ✅ | FastAPI :8765 |
| 真机数据流 | ✅ | HTTP JSON + JPEG |
| Sys-1 ACT 推理 | ✅ | 42ms MPS |
| 模型加载 | ✅ | ZmaxSys1Policy |
| 代码同步 | ✅ | Git mac→main |
| 部署脚本 | ✅ | rsync → Orin |
| 配网自启 | ✅ | setup_network.sh |

## 部署流程 (等待 xspace 训练完成后)

```bash
# 1. Pull 训练好的模型
cd /Users/mikeni/lerobot-smolvla-lew
git pull origin main

# 2. 同步到 Orin
rsync -avz src/ nvidia@192.168.23.10:~/xspace/lerobot-smolvla-lew/src/

# 3. 验证推理
python3 -c "from lerobot.policies.zmax_sys1 import ZmaxSys1Policy; model = ZmaxSys1Policy(); print('Model:', model)"

# 4. 开机自启部署
scripts/setup_network.sh  # 已配置
```

## 等待上游

| 依赖 | 负责人 |
|------|:---:|
| RoboGen+MetaWorld 数据管线 | @xspace |
| Sys-10~22 模型训练 | @web |

> 部署管线已就绪，等模型和数据。
