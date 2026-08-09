# 🐛 2026-08-09 老倪: 远程训练入口 — 禁用 cuDNN (9.19 + 驱动550 组合 conv 崩 CUDNN_STATUS_NOT_INITIALIZED)
import torch
torch.backends.cudnn.enabled = False
import sys
sys.argv = ['lerobot_train'] + sys.argv[1:]
from lerobot.scripts.lerobot_train import main
main()
