# Z700 模型整体 docker 部署 → Mac M1 (2026-08-12)

需求: Z700 的 3 个模型整体放进 docker 镜像, 部署到小芳 Mac(M1, arm64), 后续方便再转 Orin。
用户原话: "容器相当于一个 vehicle, 要有模型整体, 部署到 mac 上时候, 如何能方便的部署到 orin 上呢?怎么留接口最方便? 现在你是在考虑 系统1" — 镜像 = 可迁移载体, 服务接口 = 部署抽象层, Mac/Orin 跑同一套容器+API。

## Z700 模型构成 (实测确认 = 3 模型)

| # | 模型 | 文件 | 大小 |
|---|------|------|------|
| 1 | 🎯 YOLO 感知 (hand/peg/hole 检测) | `runs/detect/outputs/yolo_peg/peg_full/weights/best.pt` | 22MB (yolov8s, mAP50 .994) |
| 2 | 🧠 左脑 LeftBrainMLP | `outputs/train/left_right_<ts>/checkpoints/last/pretrained_model/model.pt` 内 `left` 键 | (双脑共 2.5MB) |
| 3 | 🧠 右脑 RightBrainWM | 同上 `right` 键 | 同上 |

- **model.pt 顶层键 = `['left', 'right', 'obs_dim', 'act_dim']`**(torch.load 实测)——左脑/右脑权重在同一文件, 部署时拆开加载
- 外加状态机配置 `config/state_machines/`(44KB, 非模型)
- **RightBrainWM.forward(obs, act) 是双输入**(obs+action 拼接)→ next_obs, contact(不是单输入! 部署服务里 `m.right(t)` 单输入会崩/错)

## 镜像三件套 (docker/z700_infer/)

```
docker/z700_infer/
├── Dockerfile        FROM arm64v8/python:3.11-slim; apt libgl1 libglib2.0-0 (opencv 需要);
│                     pip install requirements; COPY models/ + infer_service.py + modeling.py;
│                     CMD uvicorn infer_service:app --port 8001
├── requirements.txt  torch==2.3.1 (arm64 官方 wheel, CPU 推理; M1 无 CUDA, MPS 可选)
│                     ultralytics==8.4.115 (与训练 .venv 同版本) numpy<2.0 fastapi uvicorn PyYAML
├── modeling.py       LeftBrainMLP/RightBrainWM 定义 (从 src/lerobot/policies/left_right/
│                     modeling_left_right.py 提取纯网络部分, 去掉 PreTrainedPolicy/lerobot 依赖)
└── infer_service.py  FastAPI: GET /health (模型加载状态) · POST /detect (base64 图→检测框)
                      · POST /predict (obs 43D→action 4D + contact + next_obs)
```

- 加载路径约定: `models/yolo_best.pt` + `models/left_right/model.pt` + `models/statemachine.yaml`(Dockerfile COPY models/)
- 懒加载: startup 事件加载全部, health 报告各模型是否就绪

## 部署链路 (Mac 端)

1. **模型包(25MB, 小)走 ECS relay**(现有链路: 4060 → datadrive.world/api/relay → Mac `cicd_pull_deploy.py` 同款拉取); **镜像本身(1-2GB, 含 torch)不走 relay**(弹栈队列+内存限制) → **镜像在 Mac 上本地构建**(`docker build`, M1 原生 arm64 快; 4060 x86 交叉构建 QEMU 慢且复杂, 没必要)
2. Mac: `curl -o z700_models.tar.gz <包URL>` → `tar xzf -C models/` → `docker build -t z700-infer .` → `docker run -d -p 8001:8001 z700-infer`
3. 接口抽象: /detect /predict 是部署层 API, **Orin 复用同一容器+同一服务**(换模型文件即可) — 这就是"容器=vehicle, 接口=留的口子"

## 验证 (镜像内代码在 4060 本地可验)

- modeling.py + infer_service.py 语法 + **用 .venv torch 加载真实 model.pt**: `LeftBrainMLP(obs_dim, act_dim).load_state_dict(sd["left"])` 键必须匹配; 前向 `act=left(obs)` shape (1,act_dim), `nxt, contact = right(obs, act)` shape (1,obs_dim)/(1,1), contact∈(0,1)
- Dockerfile 断言: arm64v8/python 基础镜像 + COPY models/
- 系统 python3 无 torch → 验证脚本必须 `.venv/bin/python` 跑
- 镜像内依赖 (torch/ultralytics/fastapi) 只在容器里, 4060 本地 py_compile 即可 (Pyright 报 missing import 是环境误报)

## 坑

- **右脑双输入**: RightBrainWM.forward(obs, act) — infer_service 里 `m.right(t, action)`, 别写成单输入
- **arm64 基础镜像**: `arm64v8/python:3.11-slim`(Mac M1 必须 arm64; x86 镜像拉下来也跑不了)
- **openvino/opencv 系统库**: arm64v8 slim 无 libgl → Dockerfile apt 装 libgl1 libglib2.0-0
- docker CLI 可能被包装成 FAKE-DOCKER(环境态) — 用前 `docker info` 确认, 别默认可用
